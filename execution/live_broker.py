import os
import json
import logging
import httpx
from datetime import datetime, timezone
from typing import List, Dict, Any
from models import TradeSignal, PortfolioState, Position, OrderSide
from execution.base_broker import BaseBroker
from config import cfg
from strategy.risk import RiskManager
from registry.stations import resolve_station
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING

logger = logging.getLogger(__name__)

class LiveBroker(BaseBroker):
    def __init__(self):
        self._setup_proxy()
        self._init_client()

    def _setup_proxy(self):
        """Enforces all outbound py_clob_client_v2 network calls to route through wireproxy."""
        if cfg.PROXY_HTTP:
            os.environ["HTTP_PROXY"] = cfg.PROXY_HTTP
            os.environ["HTTPS_PROXY"] = cfg.PROXY_HTTP
            os.environ["ALL_PROXY"] = cfg.PROXY_SOCKS5
            try:
                import py_clob_client_v2.http_helpers.helpers as h
                h._http_client = httpx.Client(proxy=cfg.PROXY_HTTP, http2=True, timeout=30.0)
                logger.info(f"Configured py_clob_client_v2 proxy via {cfg.PROXY_HTTP}")
            except Exception as e:
                logger.warning(f"Failed to hook _http_client proxy: {e}")

    def _init_client(self):
        if not cfg.POLY_PRIVATE_KEY:
            logger.warning("POLY_PRIVATE_KEY not set. Live broker initialized in dormant mode.")
            self.client = None
            return

        try:
            from py_clob_client_v2.client import ClobClient
            from py_clob_client_v2.clob_types import ApiCreds
            creds = None
            if cfg.POLY_API_KEY and cfg.POLY_API_SECRET:
                creds = ApiCreds(
                    api_key=cfg.POLY_API_KEY,
                    api_secret=cfg.POLY_API_SECRET,
                    api_passphrase=cfg.POLY_PASSPHRASE
                )

            self.client = ClobClient(
                host=cfg.CLOB_API_BASE,
                chain_id=cfg.POLY_CHAIN_ID,
                key=cfg.POLY_PRIVATE_KEY,
                signature_type=cfg.POLY_SIGNATURE_TYPE,
                funder=cfg.POLY_FUNDER if cfg.POLY_FUNDER else None,
                creds=creds
            )

            # If creds were not explicitly provided, derive them automatically via V2 EIP-712
            if not creds:
                logger.info("Deriving or creating Polymarket API credentials via V2 SDK...")
                derived_creds = self.client.create_or_derive_api_key()
                self.client.set_api_creds(derived_creds)
                logger.info(f"Successfully authenticated with derived Polymarket V2 API key: {derived_creds.api_key[:8]}...")

            logger.info("Polymarket CLOB V2 client initialized and authenticated for live trading.")
        except Exception as e:
            logger.error(f"Failed to initialize V2 CLOB client: {e}")
            self.client = None

    def get_portfolio_state(self) -> PortfolioState:
        if not self.client:
            return PortfolioState(cash_usdc=0.0)

        cash = 0.0
        positions = {}
        pos_val = 0.0
        risk_data_complete = bool(cfg.POLY_FUNDER)

        # 1. Query on-chain pUSD balance with multi-RPC fallback
        if cfg.POLY_FUNDER:
            import requests
            rpcs = [
                'https://polygon.drpc.org',
                'https://polygon-bor-rpc.publicnode.com'
            ]
            pusd = '0xc011a7e12a19f7b1f670d46f03b03f3342e82dfb'
            addr = cfg.POLY_FUNDER.lower().replace('0x', '').zfill(64)
            data = '0x70a08231' + addr
            payload = {'jsonrpc': '2.0', 'method': 'eth_call', 'params': [{'to': pusd, 'data': data}, 'latest'], 'id': 1}

            for rpc in rpcs:
                try:
                    r = requests.post(rpc, json=payload, timeout=8).json()
                    res = r.get('result', '0x0')
                    cash = int(res, 16) / 1e6
                    logger.info(f"Live On-chain pUSD Balance via {rpc}: ${cash:,.2f}")
                    break
                except Exception as e:
                    logger.debug(f"RPC {rpc} check failed: {e}")

        # Fallback check via CLOB client
        if cash == 0.0 and self.client:
            try:
                from py_clob_client_v2.clob_types import BalanceAllowanceParams, AssetType
                res = self.client.get_balance_allowance(BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=cfg.POLY_SIGNATURE_TYPE))
                raw_bal = float(res.get("balance", 0.0))
                cash = raw_bal / 1e6
            except Exception as e:
                risk_data_complete = False
                logger.warning("Collateral balance unavailable")

        # 2. Query open positions via Polymarket Data API
        if cfg.POLY_FUNDER:
            try:
                import requests
                pos_url = f"https://data-api.polymarket.com/positions?user={cfg.POLY_FUNDER}"
                position_rows = []
                for offset in range(0, 10000, 500):
                    r = requests.get(pos_url, params={"limit": 500, "offset": offset, "sizeThreshold": 0}, timeout=20)
                    r.raise_for_status()
                    page = r.json()
                    if not isinstance(page, list):
                        raise ValueError("Invalid positions response")
                    position_rows.extend(page)
                    if len(page) < 500:
                        break
                else:
                    raise ValueError("Positions pagination exceeded safety limit")
                if r.status_code == 200:
                    for p in position_rows:
                        size = float(p.get("size", 0.0))
                        if size > 0:
                            tok_id = p.get("asset", "")
                            is_redeemable = bool(p.get("redeemable", False))
                            percent_pnl = float(p.get("percentPnl", 0.0))
                            raw_cur = float(p.get("curPrice", p.get("avgPrice", 0.0)))
                            cost = float(p.get("initialValue", 0.0))

                            # Accurately differentiate resolved winners vs resolved losses
                            if is_redeemable and percent_pnl <= -99.0:
                                # Finalized market that expired worthless
                                cur_p = 0.0
                                is_winner = False
                            elif is_redeemable and (percent_pnl > 0 or raw_cur >= 0.99):
                                # Finalized market that resolved as a winning payout ($1.00/share)
                                cur_p = 1.0
                                is_winner = True
                            else:
                                cur_p = raw_cur
                                is_winner = False

                            # Exclude settled 100% losses from active open positions
                            if is_redeemable and not is_winner and cur_p == 0.0:
                                continue

                            positions[tok_id] = Position(
                                token_id=tok_id,
                                market_id=p.get("conditionId", ""),
                                condition_id=p.get("conditionId", ""),
                                contract_title=p.get("title", ""),
                                bracket_label=p.get("outcome", ""),
                                shares=size,
                                avg_entry_price=float(p.get("avgPrice", 0.0)),
                                total_cost_usdc=cost,
                                current_market_price=cur_p,
                                unrealized_pnl_usdc=(size * cur_p) - cost,
                                city=(resolve_station(p.get("title", "")).city if resolve_station(p.get("title", "")) else ""),
                                redeemable=is_winner
                            )
                            pos_val += (size * cur_p)
                else:
                    risk_data_complete = False
            except Exception as e:
                risk_data_complete = False
                logger.warning(f"Failed to fetch live positions from data API: {e}")

        pending_buys = False
        try:
            orders = self.client.get_open_orders()
            if not isinstance(orders, list):
                raise ValueError("Invalid open orders response")
            pending_buys = any(o.get("side", "").upper() == "BUY" for o in orders)
        except Exception:
            risk_data_complete = False
        realized = 0.0
        try:
            with open("/root/polymarket-weathernext/data/live_ledger.json") as handle:
                realized = float(json.load(handle).get("realized_pnl_usdc", 0.0))
        except (OSError, ValueError):
            pass
        total_val = cash + pos_val
        logger.info(f"Live Portfolio: Cash: ${cash:,.2f} | Positions: ${pos_val:,.2f} | Total: ${total_val:,.2f}")
        state = PortfolioState(
            cash_usdc=cash,
            total_portfolio_value_usdc=total_val,
            positions=positions,
            realized_pnl_usdc=realized,
            unrealized_pnl_usdc=sum(p.unrealized_pnl_usdc for p in positions.values()),
            risk_data_complete=risk_data_complete,
            pending_buy_orders=pending_buys
        )
        self._sync_ledger(state)
        return state

    def _sync_ledger(self, state: PortfolioState, new_trade: dict = None):
        ledger_path = "/root/polymarket-weathernext/data/live_ledger.json"
        existing_trades = []
        existing_orders = []
        realized_pnl = 0.0
        if os.path.exists(ledger_path):
            try:
                with open(ledger_path, "r") as f:
                    data = json.load(f)
                    existing_trades = data.get("trades", [])
                    existing_orders = data.get("orders", [])
                    realized_pnl = data.get("realized_pnl_usdc", 0.0)
            except Exception:
                pass

        if new_trade:
            existing_orders.append(new_trade)

        pos_dict = {}
        for tok_id, pos in state.positions.items():
            pos_dict[tok_id] = {
                "market_id": pos.market_id,
                "condition_id": pos.condition_id,
                "contract_title": pos.contract_title,
                "bracket_label": pos.bracket_label,
                "shares": pos.shares,
                "avg_entry_price": pos.avg_entry_price,
                "total_cost_usdc": pos.total_cost_usdc,
                "current_market_price": pos.current_market_price,
                "unrealized_pnl_usdc": pos.unrealized_pnl_usdc,
                "redeemable": pos.redeemable,
                "city": pos.city
            }

        unrealized = sum(p.unrealized_pnl_usdc for p in state.positions.values())
        ledger_content = {
            "mode": "LIVE",
            "funder": cfg.POLY_FUNDER,
            "cash_usdc": state.cash_usdc,
            "total_portfolio_value_usdc": state.total_portfolio_value_usdc,
            "realized_pnl_usdc": realized_pnl,
            "unrealized_pnl_usdc": unrealized,
            "positions": pos_dict,
            "trades": existing_trades,
            "orders": existing_orders,
            "accounting_status": "legacy PnL incomplete; see audit reconciliation",
            "live_trading_enabled": cfg.LIVE_TRADING_ENABLED,
            "live_entries_enabled": cfg.LIVE_ENTRIES_ENABLED,
            "risk_data_complete": state.risk_data_complete
        }
        try:
            temp_path = ledger_path + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(ledger_content, f, indent=2)
            os.replace(temp_path, ledger_path)
        except Exception as e:
            logger.warning(f"Failed to sync live ledger: {e}")

    def settle_resolved_positions(self) -> List[dict]:
        """
        Inspects live positions from Polymarket data API.
        - Identifies resolved winners (redeemable with payout $1.00/share).
        - Identifies resolved losses (percentPnl <= -99.0%).
        - Finalizes realized PnL and records settlement in live_ledger.json.
        """
        resolved = []
        if not cfg.POLY_FUNDER:
            return resolved

        import requests
        try:
            pos_url = f"https://data-api.polymarket.com/positions?user={cfg.POLY_FUNDER}"
            r = requests.get(pos_url, timeout=20)
            if r.status_code != 200:
                return resolved

            ledger_path = "/root/polymarket-weathernext/data/live_ledger.json"
            existing_trades = []
            realized_pnl = 0.0
            if os.path.exists(ledger_path):
                try:
                    with open(ledger_path, "r") as f:
                        data = json.load(f)
                        existing_trades = data.get("trades", [])
                        realized_pnl = float(data.get("realized_pnl_usdc", 0.0))
                except Exception:
                    pass

            settled_tokens = {t.get("token_id") or t.get("event_title") for t in existing_trades if t.get("resolution")}

            for p in r.json():
                size = float(p.get("size", 0.0))
                tok_id = p.get("asset", "")
                is_redeemable = bool(p.get("redeemable", False))
                percent_pnl = float(p.get("percentPnl", 0.0))
                cost = float(p.get("initialValue", 0.0))
                title = p.get("title", "")
                outcome = p.get("outcome", "")

                if is_redeemable and percent_pnl <= -99.0:
                    # Finalized loss
                    if tok_id not in settled_tokens and title not in settled_tokens:
                        loss = -cost
                        realized_pnl = round(realized_pnl + loss, 2)
                        record = {
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "event_title": title,
                            "bracket": outcome,
                            "token_id": tok_id,
                            "resolution": "EXPIRED_LOSS",
                            "shares": size,
                            "payout_usdc": 0.0,
                            "realized_profit_usdc": loss
                        }
                        existing_trades.append(record)
                        settled_tokens.add(tok_id)
                        logger.info(f"SETTLEMENT (LIVE): {title} [{outcome}] expired worthless. Realized loss: ${loss:.2f}")
                        resolved.append(record)
                elif is_redeemable and (percent_pnl > 0 or float(p.get("curPrice", 0)) >= 0.99):
                    payout = round(size * 1.0, 2)
                    profit = round(payout - cost, 2)
                    logger.info(f"🎉 [LIVE REDEEMABLE WINNER] {title} [{outcome}]: {size} shares @ $1.00 = ${payout:.2f} payout (Profit: ${profit:+.2f}). Ready to claim.")
                    resolved.append({
                        "token_id": tok_id,
                        "status": "REDEEMABLE_WINNER",
                        "title": title,
                        "shares": size,
                        "payout": payout,
                        "profit": profit
                    })

            # Save updated realized PnL and trades if changes were made
            if resolved and os.path.exists(ledger_path):
                try:
                    with open(ledger_path, "r") as f:
                        data = json.load(f)
                    data["realized_pnl_usdc"] = realized_pnl
                    data["trades"] = existing_trades
                    # Ensure expired lost tokens are removed from active positions in ledger
                    for r_item in resolved:
                        if r_item.get("resolution") == "EXPIRED_LOSS":
                            data["positions"].pop(r_item.get("token_id", ""), None)
                    with open(ledger_path, "w") as f:
                        json.dump(data, f, indent=2)
                except Exception as e:
                    logger.warning(f"Failed to update ledger with settled positions: {e}")

        except Exception as e:
            logger.warning(f"Error checking settled positions: {e}")

        return resolved

    def execute_signals(self, signals: List[TradeSignal]) -> List[dict]:
        if not cfg.LIVE_TRADING_ENABLED:
            logger.warning("Live execution is disabled; no orders submitted")
            return []
        if not self.client:
            logger.error("Cannot execute live signals: Live broker is dormant or missing credentials.")
            return []

        from py_clob_client.clob_types import OrderArgs
        executed = []

        # Check existing active orders on CLOB to prevent duplicate postings or balance locking errors
        resting_tokens = {}
        try:
            res_orders = self.client.get_open_orders()
            if not isinstance(res_orders, list):
                raise ValueError("Invalid open orders response")
            if isinstance(res_orders, list):
                for o in res_orders:
                    if str(o.get("status", "")).upper() in {"LIVE", "ORDER_STATUS_LIVE"}:
                        tok = o.get("asset_id") or o.get("token_id")
                        if tok:
                            resting_tokens[tok] = o
        except Exception as e:
            logger.warning(f"Open-order check failed; refusing execution: {e}")
            return []

        for sig in signals:
            try:
                side_str = "BUY" if sig.side == OrderSide.BUY else "SELL"
                if side_str == "BUY":
                    if not cfg.LIVE_ENTRIES_ENABLED:
                        continue
                    # Re-check current holdings and reservations before every new buy.
                    if not RiskManager.filter_and_scale_signals([sig], self.get_portfolio_state()):
                        continue
                label = sig.bracket.label if sig.bracket else sig.target_token_id

                if sig.target_token_id in resting_tokens:
                    existing = resting_tokens[sig.target_token_id]
                    if existing.get("side") == side_str:
                        logger.info(f"Resting order already active on CLOB for {label} ({side_str} {existing.get('original_size')}x @ ${existing.get('price')}). Skipping duplicate.")
                        continue

                shares = float(sig.recommended_shares)
                tick = Decimal(str(self.client.get_tick_size(sig.target_token_id)))
                rounding = ROUND_FLOOR if side_str == "BUY" else ROUND_CEILING
                price = float((Decimal(str(sig.target_price)) / tick).to_integral_value(rounding=rounding) * tick)
                if shares <= 0 or not 0 < price < 1:
                    continue

                order_args = OrderArgs(
                    token_id=sig.target_token_id,
                    price=price,
                    size=shares,
                    side=side_str
                )
                resp = self.client.create_and_post_order(order_args)
                if not isinstance(resp, dict) or not resp.get("success") or not resp.get("orderID"):
                    logger.error("Exchange rejected order for %s: %s", sig.target_token_id, resp)
                    continue
                logger.info("LIVE ORDER ACCEPTED: %s %s @ %s, status=%s", side_str, shares, price, resp.get("status"))
                label = sig.bracket.label if sig.bracket else sig.target_token_id

                trade_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "event_title": sig.contract.event_title if sig.contract else label,
                    "bracket": label,
                    "side": side_str,
                    "shares": shares,
                    "record_type": "ORDER_SUBMISSION",
                    "token_id": sig.target_token_id,
                    "limit_price": price,
                    "requested_notional_usdc": round(shares * price, 6),
                    "status": resp.get("status"),
                    "model_prob": sig.model_prob,
                    "rationale": sig.rationale,
                    "order_id": resp.get("orderID", "") if isinstance(resp, dict) else str(resp),
                    "response": resp
                }
                cur_state = self.get_portfolio_state()
                self._sync_ledger(cur_state, new_trade=trade_entry)

                resting_tokens[sig.target_token_id] = {"side": side_str, "original_size": shares, "price": price}
                executed.append({"status": "SUBMITTED", "response": resp, "signal": label})
                if side_str == "BUY":
                    break  # Allow balance/position APIs to catch up before another entry.
            except Exception as e:
                label = sig.bracket.label if sig.bracket else sig.target_token_id
                logger.error(f"Live order failed for {label}: {e}")
        return executed
