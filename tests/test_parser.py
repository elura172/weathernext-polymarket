"""
Unit tests for Polymarket Weather Contract & Bracket Parser.
"""
from polymarket.parser import parse_bracket_bounds, parse_weather_event
from models import MetricType, UnitType

def test_parse_bracket_bounds():
    # Tail below
    q1 = "Will the highest temperature in Dallas be 83°F or below on September 3?"
    min_t, max_t, label = parse_bracket_bounds(q1, UnitType.FAHRENHEIT, 1.0)
    assert min_t == float("-inf")
    assert max_t == 83.5
    assert label == "83°F or below"

    # Single degree
    q2 = "Will the highest temperature in Dallas be 84°F on September 3?"
    min_t, max_t, label = parse_bracket_bounds(q2, UnitType.FAHRENHEIT, 1.0)
    assert min_t == 83.5
    assert max_t == 84.5
    assert label == "84°F"

    # Tail higher
    q3 = "Will the highest temperature in Dallas be 87°F or higher on September 3?"
    min_t, max_t, label = parse_bracket_bounds(q3, UnitType.FAHRENHEIT, 1.0)
    assert min_t == 86.5
    assert max_t == float("inf")
    assert label == "87°F or higher"

    # Range
    q4 = "Will the highest temperature in London be 20-21°C on September 4?"
    min_t, max_t, label = parse_bracket_bounds(q4, UnitType.CELSIUS, 1.0)
    assert min_t == 19.5
    assert max_t == 21.5
    assert label == "20-21°C"

    # Direct bracket labels (without 'Will the highest ... be')
    min_t, max_t, label = parse_bracket_bounds("66-67°F", UnitType.FAHRENHEIT, 1.0)
    assert min_t == 65.5
    assert max_t == 67.5
    assert label == "66-67°F"

    min_t, max_t, label = parse_bracket_bounds("26°C", UnitType.CELSIUS, 1.0)
    assert min_t == 25.5
    assert max_t == 26.5
    assert label == "26°C"

    min_t, max_t, label = parse_bracket_bounds("33°C or higher", UnitType.CELSIUS, 1.0)
    assert min_t == 32.5
    assert max_t == float("inf")

def test_parse_weather_event_structure():
    mock_event = {
        "id": "12345",
        "title": "Highest temperature in Dallas on September 3?",
        "slug": "highest-temperature-in-dallas-on-september-3-2026",
        "description": "The resolution source for this market will be information from NOAA... https://www.weather.gov/wrh/timeseries?site=kdal",
        "resolutionSource": "https://www.weather.gov/wrh/timeseries?site=kdal",
        "markets": [
            {
                "id": "1",
                "question": "Will the highest temperature in Dallas be 83°F or below on September 3?",
                "conditionId": "0xabc",
                "clobTokenIds": '["tok1", "tok2"]',
                "outcomePrices": '["0.10", "0.90"]',
                "endDateIso": "2026-09-03T23:59:59Z"
            },
            {
                "id": "2",
                "question": "Will the highest temperature in Dallas be 84°F on September 3?",
                "conditionId": "0xdef",
                "clobTokenIds": '["tok3", "tok4"]',
                "outcomePrices": '["0.40", "0.60"]',
                "endDateIso": "2026-09-03T23:59:59Z"
            }
        ]
    }
    contract = parse_weather_event(mock_event)
    assert contract is not None
    assert contract.city == "Dallas"
    assert contract.station_icao == "kdal"
    assert contract.metric == MetricType.T_MAX
    assert contract.unit == UnitType.FAHRENHEIT
    assert len(contract.brackets) == 2
