"""
Institutional Real-Time Web Dashboard for Polymarket Weather Intelligence.
Provides a browser interface showing:
- Real-time Portfolio KPIs (Equity, Liquid Cash, Realized PnL, Win Rate)
- Active Open Positions with live mark-to-market prices & ROI
- Interactive Probability Distribution Curves (WeatherNext 3 vs Market Implied)
- Live Trade Log Stream
- Background Daemon status
"""
import http.server
import socketserver
import json
import os
import sys
import logging
from typing import Dict, Any
from datetime import datetime, timezone
from config import cfg
from models import ExecutionMode
from forecast.nowcasting import MetarNowcaster
from registry.stations import resolve_station

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WeatherWebUI")

web_nowcaster = MetarNowcaster(cache_ttl_seconds=180)
KEY_STATIONS = ["knyc", "kden", "lfpg", "egll", "vhhh", "zsss", "zbaa"]

LEDGER_PATH = cfg.PAPER_LEDGER_PATH
LIVE_LEDGER_PATH = "/root/polymarket-weathernext/data/live_ledger.json"
DAEMON_LOG = "/root/polymarket-weathernext/data/daemon.log"

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Antigravity Weather | Polymarket Intelligence</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background-color: #0b0f19; color: #e2e8f0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        .card { background: #131b2e; border: 1px solid #1e293b; border-radius: 12px; }
        .badge { display: inline-block; padding: 2px 8px; border-radius: 6px; font-size: 11px; font-weight: 600; }
    </style>
</head>
<body class="p-6">
    <div class="max-w-7xl mx-auto space-y-6">
        <!-- Header -->
        <div class="flex items-center justify-between border-b border-slate-800 pb-4">
            <div>
                <h1 class="text-2xl font-bold text-white flex items-center gap-2">
                    <span>🌦️</span> Polymarket Weather Intelligence Engine
                </h1>
                <p class="text-sm text-slate-400">Powered by Google DeepMind WeatherNext 3 & High-Res Ensembles</p>
            </div>
            <div class="flex items-center gap-4">
                <span class="badge bg-emerald-950 text-emerald-400 border border-emerald-800 flex items-center gap-1.5 py-1 px-3">
                    <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span> Daemon Active
                </span>
                <span id="mode-badge" class="badge bg-indigo-950 text-indigo-400 border border-indigo-800 py-1 px-3">Mode: PAPER</span>
            </div>
        </div>

        <!-- KPI Cards -->
        <div class="grid grid-cols-1 md:grid-cols-4 gap-4" id="kpi-grid">
            <div class="card p-5">
                <p class="text-xs uppercase tracking-wider text-slate-400 font-medium">Total Portfolio Value</p>
                <h2 class="text-3xl font-extrabold text-white mt-1" id="total-equity">$0.00</h2>
                <span class="text-xs text-emerald-400 font-semibold mt-2 block" id="unrealized-pnl">+0.00%</span>
            </div>
            <div class="card p-5">
                <p class="text-xs uppercase tracking-wider text-slate-400 font-medium">Available Cash</p>
                <h2 class="text-3xl font-extrabold text-white mt-1" id="liquid-cash">$0.00</h2>
                <span class="text-xs text-slate-400 mt-2 block">Liquid USDC Collateral</span>
            </div>
            <div class="card p-5">
                <p class="text-xs uppercase tracking-wider text-slate-400 font-medium">Realized Profit & Loss</p>
                <h2 class="text-3xl font-extrabold text-emerald-400 mt-1" id="realized-pnl">+$0.00</h2>
                <span class="text-xs text-slate-400 mt-2 block">Banked & Reinvested</span>
            </div>
            <div class="card p-5">
                <p class="text-xs uppercase tracking-wider text-slate-400 font-medium">Open Positions</p>
                <h2 class="text-3xl font-extrabold text-cyan-400 mt-1" id="open-positions-count">0</h2>
                <span class="text-xs text-slate-400 mt-2 block">Active Weather Brackets</span>
            </div>
        </div>

        <!-- Station Microclimate & Real-Time METAR Nowcasting -->
        <div class="card p-6">
            <h3 class="text-lg font-bold text-white mb-3 flex items-center justify-between">
                <span class="flex items-center gap-2"><span>📡</span> Station Microclimates & Real-Time METAR Nowcasts</span>
                <span class="text-xs text-slate-400 font-normal">Sub-hourly Global Airport & Park Sensor Observations</span>
            </h3>
            <div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-3" id="metar-grid">
                <div class="p-3 bg-slate-900/60 rounded-lg border border-slate-800 text-xs text-slate-400">Loading METAR telemetry...</div>
            </div>
        </div>

        <!-- Positions Table -->
        <div class="card p-6">
            <h3 class="text-lg font-bold text-white mb-4 flex items-center justify-between">
                <span>Active Open Positions</span>
                <span class="text-xs text-slate-400 font-normal">Real-time Marked-to-Market</span>
            </h3>
            <div class="overflow-x-auto">
                <table class="w-full text-left text-sm">
                    <thead>
                        <tr class="border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider">
                            <th class="py-3 px-4">Event Target</th>
                            <th class="py-3 px-4">Bracket</th>
                            <th class="py-3 px-4">Shares</th>
                            <th class="py-3 px-4">Avg Entry</th>
                            <th class="py-3 px-4">Current Price</th>
                            <th class="py-3 px-4">Market Value</th>
                            <th class="py-3 px-4">Unrealized PnL</th>
                        </tr>
                    </thead>
                    <tbody id="positions-table-body" class="divide-y divide-slate-800/60">
                        <tr><td colspan="7" class="py-4 px-4 text-center text-slate-500">Loading active positions...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Trade History -->
        <div class="card p-6">
            <h3 class="text-lg font-bold text-white mb-4">Trade Execution Ledger</h3>
            <div class="overflow-x-auto max-h-80 overflow-y-auto">
                <table class="w-full text-left text-sm">
                    <thead>
                        <tr class="border-b border-slate-800 text-slate-400 text-xs uppercase tracking-wider sticky top-0 bg-[#131b2e]">
                            <th class="py-3 px-4">Timestamp</th>
                            <th class="py-3 px-4">Event</th>
                            <th class="py-3 px-4">Bracket</th>
                            <th class="py-3 px-4">Action</th>
                            <th class="py-3 px-4">Shares</th>
                            <th class="py-3 px-4">Fill Price</th>
                            <th class="py-3 px-4">Realized Profit</th>
                        </tr>
                    </thead>
                    <tbody id="trades-table-body" class="divide-y divide-slate-800/60">
                        <tr><td colspan="7" class="py-4 px-4 text-center text-slate-500">Loading trades...</td></tr>
                    </tbody>
                </table>
            </div>
        </div>
    </div>

    <script>
        async function fetchDashboardData() {
            try {
                const res = await fetch('/api/data');
                const data = await res.json();
                
                if (data.mode === 'LIVE') {
                    const badge = document.getElementById('mode-badge');
                    badge.className = 'badge bg-amber-950 text-amber-300 border border-amber-700 py-1 px-3 font-bold flex items-center gap-1.5';
                    const funderShort = data.funder ? data.funder.slice(0, 6) + '...' + data.funder.slice(-4) : 'Polygon Mainnet';
                    badge.textContent = `${data.live_trading_enabled ? "LIVE ENABLED" : "LIVE PAUSED"}: ${funderShort}`;
                }

                // KPIs
                document.getElementById('total-equity').innerText = '$' + data.total_equity.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                document.getElementById('liquid-cash').innerText = '$' + data.cash_usdc.toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                
                const pnlEl = document.getElementById('realized-pnl');
                const pnl = data.realized_pnl_usdc || 0;
                pnlEl.title = data.accounting_status || '';
                pnlEl.innerText = (pnl >= 0 ? '+$' : '-$') + Math.abs(pnl).toLocaleString(undefined, {minimumFractionDigits: 2, maximumFractionDigits: 2});
                
                document.getElementById('open-positions-count').innerText = Object.keys(data.positions || {}).length;

                // Positions Table
                const posBody = document.getElementById('positions-table-body');
                const positions = Object.values(data.positions || {});
                if (positions.length === 0) {
                    posBody.innerHTML = '<tr><td colspan="7" class="py-4 px-4 text-center text-slate-500">No open positions. All trades resolved or took profit.</td></tr>';
                } else {
                    posBody.innerHTML = positions.map(p => {
                        const val = p.shares * (p.current_market_price || p.avg_entry_price);
                        const pnl = val - p.total_cost_usdc;
                        const roi = p.total_cost_usdc > 0 ? (pnl / p.total_cost_usdc * 100) : 0;
                        const isProfit = pnl >= 0;
                        const redeemBadge = p.redeemable ? '<span class="badge bg-emerald-950 text-emerald-300 border border-emerald-700 ml-2 font-bold animate-pulse">🎉 Winner ($1.00)</span>' : '';
                        return `<tr class="hover:bg-slate-800/40 transition">
                            <td class="py-3 px-4 font-medium text-white">${p.contract_title || 'Weather Event'}${redeemBadge}</td>
                            <td class="py-3 px-4"><span class="badge bg-slate-800 text-cyan-300">${p.bracket_label}</span></td>
                            <td class="py-3 px-4">${p.shares.toLocaleString()}</td>
                            <td class="py-3 px-4 text-slate-300">$${p.avg_entry_price.toFixed(3)}</td>
                            <td class="py-3 px-4 text-slate-300">$${(p.current_market_price || p.avg_entry_price).toFixed(3)}</td>
                            <td class="py-3 px-4 text-white font-semibold">$${val.toFixed(2)}</td>
                            <td class="py-3 px-4 ${isProfit ? 'text-emerald-400 font-semibold' : 'text-rose-400'}">${isProfit ? '+' : ''}$${pnl.toFixed(2)} (${roi.toFixed(1)}%)</td>
                        </tr>`;
                    }).join('');
                }

                // Trades Table
                const tradeBody = document.getElementById('trades-table-body');
                const trades = (data.trades || []).filter(t => !t.response && t.record_type !== 'ORDER_SUBMISSION').slice().reverse();
                if (trades.length === 0) {
                    tradeBody.innerHTML = '<tr><td colspan="7" class="py-4 px-4 text-center text-slate-500">No trades recorded yet.</td></tr>';
                } else {
                    tradeBody.innerHTML = trades.map(t => {
                        const isSell = t.side === 'SELL' || t.resolution === 'WINNER';
                        const actionBadge = t.resolution === 'EXPIRED_LOSS' ? '<span class="badge">SETTLED LOSS</span>' : t.side === 'SELL' ? '<span class="badge bg-purple-950 text-purple-300 border border-purple-800">SELL</span>' :
                                            t.resolution === 'WINNER' ? '<span class="badge bg-emerald-950 text-emerald-300 border border-emerald-800">WINNER $1.00</span>' :
                                            '<span class="badge bg-blue-950 text-blue-300 border border-blue-800">BUY</span>';
                        const profit = t.realized_profit_usdc !== undefined ? (t.realized_profit_usdc >= 0 ? `+$${t.realized_profit_usdc.toFixed(2)}` : `-$${Math.abs(t.realized_profit_usdc).toFixed(2)}`) : '-';
                        return `<tr class="hover:bg-slate-800/40 transition">
                            <td class="py-3 px-4 text-xs text-slate-400 font-mono">${(t.timestamp || '').slice(11, 19)}</td>
                            <td class="py-3 px-4 font-medium text-white">${t.event_title}</td>
                            <td class="py-3 px-4"><span class="badge bg-slate-800 text-cyan-300">${t.bracket}</span></td>
                            <td class="py-3 px-4">${actionBadge}</td>
                            <td class="py-3 px-4">${(t.shares || 0).toLocaleString()}</td>
                            <td class="py-3 px-4 text-slate-300">$${(t.fill_price || 0).toFixed(3)}</td>
                            <td class="py-3 px-4 ${profit.startsWith('+') ? 'text-emerald-400 font-semibold' : 'text-slate-400'}">${profit}</td>
                        </tr>`;
                    }).join('');
                }

                // METAR Nowcasting Grid
                const metarGrid = document.getElementById('metar-grid');
                const nowcasts = data.nowcasts || [];
                if (nowcasts.length > 0 && metarGrid) {
                    metarGrid.innerHTML = nowcasts.map(n => {
                        const tempC = n.latest_temp_c !== null ? `${n.latest_temp_c.toFixed(1)}°C` : '--';
                        const tempF = n.latest_temp_f !== null ? `${n.latest_temp_f.toFixed(1)}°F` : '--';
                        const maxC = n.today_max_c !== null ? `${n.today_max_c.toFixed(1)}°C` : '--';
                        const bias = n.microclimate_bias_c !== undefined ? (n.microclimate_bias_c >= 0 ? `+${n.microclimate_bias_c.toFixed(1)}°C` : `${n.microclimate_bias_c.toFixed(1)}°C`) : '+0.0°C';
                        return `
                        <div class="p-3 bg-slate-900/70 rounded-lg border border-slate-800 hover:border-slate-700 transition space-y-1.5">
                            <div class="flex items-center justify-between">
                                <span class="font-bold text-white text-sm">${n.city}</span>
                                <span class="badge bg-slate-800 text-cyan-400 uppercase">${n.icao}</span>
                            </div>
                            <div class="flex items-baseline justify-between">
                                <span class="text-2xl font-black text-amber-300">${tempC}</span>
                                <span class="text-xs text-slate-400 font-mono">${tempF}</span>
                            </div>
                            <div class="text-[11px] text-slate-400 flex justify-between border-t border-slate-800/80 pt-1">
                                <span>Peak Today: <strong class="text-slate-200">${maxC}</strong></span>
                                <span>Sky: <strong class="text-slate-200">${n.cloud_cover || 'CLR'}</strong></span>
                            </div>
                            <div class="text-[11px] text-slate-400 flex justify-between">
                                <span>Type: <strong class="text-slate-300 capitalize">${(n.station_type || 'airport').replace('_', ' ')}</strong></span>
                                <span class="text-indigo-400 font-medium">Bias: ${bias}</span>
                            </div>
                        </div>`;
                    }).join('');
                }
            } catch (err) {
                console.error("Failed to fetch dashboard data:", err);
            }
        }

        fetchDashboardData();
        setInterval(fetchDashboardData, 3000);
    </script>
</body>
</html>
"""

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path == "/api/data":
            self.send_response(200)
            self.send_header("Content-type", "application/json")
            self.end_headers()
            
            is_live = (cfg.MODE == ExecutionMode.LIVE)
            active_ledger = LIVE_LEDGER_PATH if is_live else LEDGER_PATH

            ledger_data = {
                "cash_usdc": 0.0,
                "realized_pnl_usdc": 0.0,
                "positions": {},
                "trades": [],
                "mode": cfg.MODE.value,
                "funder": cfg.POLY_FUNDER
            }
            if os.path.exists(active_ledger):
                try:
                    with open(active_ledger, "r") as f:
                        ledger_data = json.load(f)
                except Exception:
                    pass

            ledger_data["live_trading_enabled"] = cfg.LIVE_TRADING_ENABLED
            ledger_data["accounting_status"] = ledger_data.get("accounting_status", "Legacy PnL is not reconciled" if is_live else "Paper simulation")
            ledger_data["mode"] = cfg.MODE.value
            ledger_data["funder"] = cfg.POLY_FUNDER
            pos_val = sum(p["shares"] * p.get("current_market_price", p.get("avg_entry_price", 0.0)) for p in ledger_data.get("positions", {}).values())
            ledger_data["total_equity"] = ledger_data.get("cash_usdc", 0.0) + pos_val

            # METAR Nowcasting & Microclimates
            nowcasts_data = []
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            for code in KEY_STATIONS:
                stn = resolve_station(code)
                if stn:
                    nc = web_nowcaster.fetch_station_nowcast(stn, today_str)
                    if nc:
                        nowcasts_data.append({
                            "city": stn.city,
                            "icao": stn.icao.upper(),
                            "station_type": stn.station_type,
                            "microclimate_bias_c": stn.microclimate_bias_c,
                            "latest_temp_c": nc.latest_temp_c,
                            "latest_temp_f": nc.latest_temp_f,
                            "today_max_c": nc.today_max_c,
                            "cloud_cover": nc.cloud_cover,
                            "local_time": nc.local_time_str
                        })
            ledger_data["nowcasts"] = nowcasts_data

            self.wfile.write(json.dumps(ledger_data).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        # Suppress noisy HTTP request polling logs
        return

def run_server(port: int = 8080):
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", port), DashboardHandler) as httpd:
        logger.info(f"Dashboard server live at http://localhost:{port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            logger.info("Dashboard server shutting down.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Polymarket Weather Real-Time Web Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="Port to run web dashboard (default: 8080)")
    args = parser.parse_args()

    run_server(args.port)
