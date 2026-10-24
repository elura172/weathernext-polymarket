from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import Mock
import json
import pytest
from config import cfg
from models import Position, PortfolioState, OrderSide, TradeSignal, UnitType
from execution.paper_broker import PaperBroker
from execution.live_broker import LiveBroker
from strategy.convergence import ConvergenceEngine
from strategy.risk import RiskManager
from polymarket.clob_client import ClobMarketClient
from polymarket.gamma_client import GammaClient
from forecast.public_fallback import PublicFallbackProvider


def signal(side=OrderSide.BUY, price=.1, shares=20, token='yes'):
    return TradeSignal(SimpleNamespace(city='Toronto', event_title='Highest temperature in Toronto'),
                       SimpleNamespace(market_id='m', condition_id='c', label='27°C'),
                       side, token, price, .4, price, .3, .3, shares, shares*price, 'test')


def position(token='yes', cost=2, shares=20):
    return Position(token, 'm', 'c', 'Will the highest temperature in Toronto be 27°C?',
                    'Yes', shares, cost/shares, cost)


def broker(tmp_path, bids=(), asks=()):
    book={'bids':[{'price':p,'size':s} for p,s in bids], 'asks':[{'price':p,'size':s} for p,s in asks]}
    return PaperBroker(str(tmp_path/'paper.json'), 100, SimpleNamespace(get_order_book=lambda _:deepcopy(book)))


def test_paper_does_not_fill_maker_ask_or_create_phantom_profit(tmp_path):
    b=broker(tmp_path,bids=[(.01,100)],asks=[(.99,100)])
    p=position();b.state['positions']['yes']=vars(p).copy()
    assert b.execute_signals([signal(OrderSide.SELL,.949)]) == []
    assert b.state['cash_usdc']==100
    b.mark_to_market()
    assert b.get_portfolio_state().total_portfolio_value_usdc == pytest.approx(100.2)


def test_paper_buy_consumes_depth_and_limit(tmp_path):
    b=broker(tmp_path,bids=[(.08,100)],asks=[(.09,3),(.1,2),(.11,100)])
    fills=b.execute_signals([signal(),signal()])
    assert len(fills)==1
    assert fills[0]['shares']==5
    assert fills[0]['fill_price']==pytest.approx(.094)
    assert b.state['cash_usdc']==pytest.approx(99.53)
    assert fills[0]['status']=='PARTIALLY_FILLED'


def test_paper_sell_uses_actual_bid_and_cost_basis(tmp_path):
    b=broker(tmp_path,bids=[(.2,5),(.15,3),(.08,100)])
    b.state['positions']['yes']=vars(position()).copy()
    fill=b.execute_signals([signal(OrderSide.SELL,.1)])[0]
    assert fill['shares']==8
    assert fill['realized_profit_usdc']==pytest.approx(.65)
    assert b.state['positions']['yes']['total_cost_usdc']==pytest.approx(1.2)


def test_paper_cash_cap_and_no_ask(tmp_path):
    b=broker(tmp_path,asks=[(.1,1000)])
    b.state['cash_usdc']=.25
    b.execute_signals([signal(shares=100)])
    assert b.state['positions']['yes']['shares']==pytest.approx(2.5)
    assert b.state['cash_usdc']==pytest.approx(0)


def test_legacy_paper_refused(tmp_path):
    p=tmp_path/'legacy.json';p.write_text(json.dumps({'cash_usdc':2420153}))
    with pytest.raises(ValueError,match='Legacy'):
        PaperBroker(str(p))


@pytest.mark.parametrize('quotes,probs', [({'yes':(0,.999,.999)},{'yes':.8}), ({'yes':(.8,.9,.85)}, {})])
def test_no_exit_without_bid_or_weather_probability(quotes,probs):
    port=PortfolioState(100, {'yes':position()},102)
    assert ConvergenceEngine.evaluate_convergence_orders(port,quotes,probs)==[]


def test_quote_sort_and_ask_only():
    c=ClobMarketClient();r=Mock();r.json.return_value={'bids':[{'price':'.01','size':'3'},{'price':'.2','size':'4'}], 'asks':[{'price':'.99','size':'4'},{'price':'.3','size':'5'}]}
    c.session.get=Mock(return_value=r)
    assert c.get_market_quote('yes')==(.2,.3,.25)
    r.json.return_value={'bids':[], 'asks':[{'price':'.999','size':'100'}]}
    assert c.get_market_quote('yes')==(0,.999,0)
    r.raise_for_status.side_effect=ValueError('network error')
    assert c.get_order_book('yes') is None


def test_city_and_contract_exposure_and_pending_orders(monkeypatch):
    monkeypatch.setattr(cfg,'MAX_CITY_ALLOCATION',.25)
    monkeypatch.setattr(cfg,'MAX_CONTRACT_ALLOCATION',.15)
    port=PortfolioState(100, {'yes':position(cost=14)},100)
    result=RiskManager.filter_and_scale_signals([signal(shares=100)],port)
    assert result[0].recommended_spend_usdc==pytest.approx(1)
    port.positions['yes'].total_cost_usdc=15
    assert RiskManager.filter_and_scale_signals([signal()],port)==[]
    port.positions={};port.pending_buy_orders=True
    assert RiskManager.filter_and_scale_signals([signal()],port)==[]
    port.pending_buy_orders=False;port.risk_data_complete=False
    assert RiskManager.filter_and_scale_signals([signal()],port)==[]


def test_city_cap_across_distinct_contracts():
    p=position(cost=25);p.condition_id='other'
    assert RiskManager.filter_and_scale_signals([signal()],PortfolioState(100,{'yes':p},100))==[]


def test_wrong_day_forecast_rejected(monkeypatch):
    resp=Mock(status_code=200)
    resp.json.return_value={'hourly':{'time':[f'2026-09-05T{h:02d}:00' for h in range(24)],'temperature_2m':[20]*24}}
    monkeypatch.setattr('forecast.public_fallback.requests.get',Mock(return_value=resp))
    provider=PublicFallbackProvider()
    assert provider.get_hourly_forecast('cyyz',1,1,'2026-09-04',UnitType.CELSIUS) is None
    assert provider.get_hourly_forecast('cyyz',1,1,'2026-09-05',UnitType.CELSIUS).t_max==20


def test_only_official_final_outcome_settles(monkeypatch):
    resp=Mock();data={'closed':True,'umaResolutionStatus':'resolved','clobTokenIds':'["yes","no"]','outcomePrices':'["0","1"]'}
    resp.json.return_value=data
    monkeypatch.setattr('polymarket.gamma_client.requests.get',Mock(return_value=resp))
    g=GammaClient()
    assert g.get_resolved_token_outcome('m','yes') is False
    assert g.get_resolved_token_outcome('m','no') is True
    data['umaResolutionStatus']='proposed'
    assert g.get_resolved_token_outcome('m','yes') is None


def live_broker():
    b=LiveBroker.__new__(LiveBroker);b.client=Mock()
    b.client.get_open_orders.return_value=[]
    b.client.get_tick_size.return_value='.01'
    b.get_portfolio_state=Mock(return_value=PortfolioState(100,{},100))
    b._sync_ledger=Mock()
    return b


def test_live_disabled_no_network(monkeypatch):
    monkeypatch.setattr(cfg,'LIVE_TRADING_ENABLED',False)
    b=live_broker();assert b.execute_signals([signal()])==[]
    assert not b.client.mock_calls


def test_live_rejected_order_not_recorded(monkeypatch):
    monkeypatch.setattr(cfg,'LIVE_TRADING_ENABLED',True)
    monkeypatch.setattr(cfg,'LIVE_ENTRIES_ENABLED',True)
    b=live_broker();b.client.create_and_post_order.return_value={'success':False,'errorMsg':'rejected'}
    assert b.execute_signals([signal()])==[]
    b._sync_ledger.assert_not_called()


def test_live_submission_not_a_fill_and_no_duplicate(monkeypatch):
    monkeypatch.setattr(cfg,'LIVE_TRADING_ENABLED',True)
    b=live_broker();b.client.create_and_post_order.return_value={'success':True,'orderID':'id','status':'live'}
    s=signal(OrderSide.SELL,.949)
    results=b.execute_signals([s,s])
    assert len(results)==1 and results[0]['status']=='SUBMITTED'
    record=b._sync_ledger.call_args.kwargs['new_trade']
    assert record['limit_price']==.95
    assert 'fill_price' not in record and 'spend_usdc' not in record


def test_open_order_failure_blocks_live(monkeypatch):
    monkeypatch.setattr(cfg,'LIVE_TRADING_ENABLED',True)
    b=live_broker();b.client.get_open_orders.side_effect=RuntimeError('timeout')
    assert b.execute_signals([signal(OrderSide.SELL)])==[]
    b.client.create_and_post_order.assert_not_called()


def test_daemon_passes_weather_probabilities_to_exits(monkeypatch):
    from daemon import WeatherTradingDaemon
    d=WeatherTradingDaemon.__new__(WeatherTradingDaemon)
    d.clob=Mock();d.clob.get_market_quote.return_value=(.01,.999,.5045)
    d.broker=Mock()
    evaluate=Mock(return_value=[])
    monkeypatch.setattr(ConvergenceEngine,'evaluate_convergence_orders',evaluate)
    probabilities={'yes':.002}
    d._check_convergence_exits(PortfolioState(100,{'yes':position()},102),probabilities)
    assert evaluate.call_args.args[2] == probabilities


def test_cycle_refreshes_portfolio_after_exits(monkeypatch):
    from daemon import WeatherTradingDaemon
    d=WeatherTradingDaemon.__new__(WeatherTradingDaemon)
    before=PortfolioState(100,{},100);after=PortfolioState(50,{},50)
    d.broker=Mock();d.broker.get_portfolio_state.side_effect=[before,before,after,after]
    d.wn=SimpleNamespace(initialized=False)
    d.get_active_weather_provider=Mock(return_value=object())
    d._check_settlements=Mock();d._collect_signals=Mock(return_value=([signal()],{'yes':.4}))
    d._check_convergence_exits=Mock()
    filtering=Mock(return_value=[])
    monkeypatch.setattr(RiskManager,'filter_and_scale_signals',filtering)
    d.run_cycle(1)
    assert filtering.call_args.args[1] is after


def test_live_entries_disabled_independently(monkeypatch):
    monkeypatch.setattr(cfg,'LIVE_TRADING_ENABLED',True)
    monkeypatch.setattr(cfg,'LIVE_ENTRIES_ENABLED',False)
    b=live_broker()
    assert b.execute_signals([signal()])==[]
    b.client.create_and_post_order.assert_not_called()


def test_expired_events_do_not_consume_scan_limit():
    from daemon import WeatherTradingDaemon
    d=WeatherTradingDaemon.__new__(WeatherTradingDaemon);d.max_events=1
    expired=SimpleNamespace(event_id='old',target_date='2000-01-01',timezone='UTC',brackets=[])
    fresh=SimpleNamespace(event_id='new',target_date='2099-01-01',timezone='UTC',brackets=[],station_icao='cyyz',lat=1,lon=1,unit=UnitType.CELSIUS)
    d.gamma=Mock();d.gamma.fetch_active_weather_events.return_value=[expired,fresh]
    provider=Mock();provider.get_hourly_forecast.return_value=None
    assert d._collect_signals(PortfolioState(100),provider)==([], {})
    provider.get_hourly_forecast.assert_called_once()
    assert provider.get_hourly_forecast.call_args.kwargs['target_date']=='2099-01-01'
