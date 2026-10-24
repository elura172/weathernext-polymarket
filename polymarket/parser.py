"""
Polymarket Weather Contract & Bracket Parser.
Converts raw Gamma API JSON objects into typed WeatherContract and Bracket models.
"""
import re
import json
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any, Tuple
from models import WeatherContract, Bracket, MetricType, UnitType
from registry.stations import resolve_station
from registry.oracles import extract_station_from_url, parse_resolution_precision

MONTH_MAP = {
    "january": 1, "february": 2, "march": 3, "april": 4,
    "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12
}

def parse_date_from_text(text: str, fallback_iso: str = "") -> str:
    """Parse date from title string like 'September 3' or 'on September 4?'."""
    match = re.search(r'on\s+([A-Za-z]+)\s+(\d{1,2})', text, re.IGNORECASE)
    if match:
        month_name = match.group(1).lower()
        day = int(match.group(2))
        month = MONTH_MAP.get(month_name)
        if month:
            # Polymarket target year (infer current year or 2026 from ISO)
            year = 2026
            if fallback_iso and len(fallback_iso) >= 4:
                try:
                    year = int(fallback_iso[:4])
                except ValueError:
                    pass
            return f"{year:04d}-{month:02d}-{day:02d}"
    if fallback_iso:
        return fallback_iso[:10]
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")

def parse_bracket_bounds(question: str, unit: UnitType, precision: float) -> Tuple[float, float, str]:
    """
    Parse temperature bounds from market question or bracket label.
    Examples:
      - 'Will the highest temperature in Dallas be 83°F or below on September 3?' -> (-inf, 83.5, '83°F or below')
      - 'Will the highest temperature in Dallas be 84°F on September 3?' -> (83.5, 84.5, '84°F')
      - '66-67°F' -> (65.5, 67.5, '66-67°F')
      - '26°C' -> (25.5, 26.5, '26°C')
    """
    # Half-step boundary for discrete integer resolution
    delta = 0.5 if precision >= 1.0 else 0.05
    unit_sym = "°" + unit.value

    # Pattern 1: X or below / lower
    m_below = re.search(r'(?:be\s+)?(?:between\s+)?([-\d.]+)\s*(?:°?[FCfc])?\s+or\s+(?:below|lower)', question, re.IGNORECASE)
    if m_below:
        val = float(m_below.group(1))
        label = f"{val:g}{unit_sym} or below"
        return float("-inf"), val + delta, label

    # Pattern 2: X or higher / above
    m_higher = re.search(r'(?:be\s+)?(?:between\s+)?([-\d.]+)\s*(?:°?[FCfc])?\s+or\s+(?:higher|above)', question, re.IGNORECASE)
    if m_higher:
        val = float(m_higher.group(1))
        label = f"{val:g}{unit_sym} or higher"
        return val - delta, float("inf"), label

    # Pattern 3: Range X-Y (e.g. between 84-85°F or 82-83°F or 66-67°F)
    m_range = re.search(r'(?:be\s+)?(?:between\s+)?([-\d.]+)\s*-\s*([-\d.]+)\s*(?:°?[FCfc])?', question, re.IGNORECASE)
    if m_range:
        low = float(m_range.group(1))
        high = float(m_range.group(2))
        label = f"{low:g}-{high:g}{unit_sym}"
        return low - delta, high + delta, label

    # Pattern 4: Exact single degree (e.g., be 84°F or 26°C)
    m_single = re.search(r'(?:be\s+)?([-\d.]+)\s*(?:°?[FCfc])?', question, re.IGNORECASE)
    if m_single:
        val = float(m_single.group(1))
        label = f"{val:g}{unit_sym}"
        return val - delta, val + delta, label

    return float("-inf"), float("inf"), question

def parse_weather_event(event_data: Dict[str, Any]) -> Optional[WeatherContract]:
    """Parse a full Polymarket event into a WeatherContract with its sub-brackets."""
    title = event_data.get("title", "")
    slug = event_data.get("slug", "")
    markets = event_data.get("markets", [])
    if not markets:
        return None

    title_lower = title.lower()
    
    # 1. Metric Type
    if "highest" in title_lower or "high temp" in title_lower or "max" in title_lower:
        metric = MetricType.T_MAX
    elif "lowest" in title_lower or "low temp" in title_lower or "min" in title_lower:
        metric = MetricType.T_MIN
    else:
        return None  # Not a high/low temperature market

    # 2. Extract station and oracle information
    first_market = markets[0]
    res_source = first_market.get("resolutionSource") or event_data.get("resolutionSource") or ""
    description = first_market.get("description") or event_data.get("description") or ""

    station_code = extract_station_from_url(res_source)
    station = None
    if station_code:
        station = resolve_station(station_code)

    if not station:
        # Fallback: lookup by city name in title
        station = resolve_station(title)

    if not station:
        return None  # Could not map to a recognized meteorological oracle station

    # 3. Unit (°F vs °C)
    q_sample = first_market.get("question", "").lower()
    desc_lower = description.lower()
    if "degrees fahrenheit" in desc_lower or "°f" in q_sample or "°f" in title_lower:
        unit = UnitType.FAHRENHEIT
    elif "degrees celsius" in desc_lower or "°c" in q_sample or "°c" in title_lower:
        unit = UnitType.CELSIUS
    elif station.default_unit == "F":
        unit = UnitType.FAHRENHEIT
    else:
        unit = UnitType.CELSIUS

    precision = parse_resolution_precision(description)

    # 4. Target Date
    target_date = parse_date_from_text(title, fallback_iso=first_market.get("endDateIso", ""))

    # 5. Parse Brackets
    parsed_brackets: List[Bracket] = []
    for m in markets:
        q = m.get("question", "")
        min_t, max_t, label = parse_bracket_bounds(q, unit, precision)
        
        # Token IDs (Yes is outcome index 0, No is outcome index 1 in binary markets)
        clob_ids = m.get("clobTokenIds")
        if isinstance(clob_ids, str):
            try:
                clob_ids = json.loads(clob_ids)
            except Exception:
                clob_ids = []
        token_yes = clob_ids[0] if len(clob_ids) > 0 else ""
        token_no = clob_ids[1] if len(clob_ids) > 1 else ""

        # Prices
        prices = m.get("outcomePrices")
        if isinstance(prices, str):
            try:
                prices = json.loads(prices)
            except Exception:
                prices = [0.0, 0.0]
        price_yes = float(prices[0]) if len(prices) > 0 else 0.0
        price_no = float(prices[1]) if len(prices) > 1 else 0.0

        parsed_brackets.append(
            Bracket(
                market_id=str(m.get("id")),
                condition_id=str(m.get("conditionId", "")),
                token_id_yes=token_yes,
                token_id_no=token_no,
                label=label,
                min_temp=min_t,
                max_temp=max_t,
                market_price_yes=price_yes,
                market_price_no=price_no,
            )
        )

    # Sort brackets ascending by min_temp
    parsed_brackets.sort(key=lambda b: b.min_temp)

    return WeatherContract(
        event_id=str(event_data.get("id")),
        event_title=title,
        event_slug=slug,
        city=station.city,
        station_icao=station.icao,
        station_name=station.name,
        lat=station.lat,
        lon=station.lon,
        timezone=station.timezone,
        metric=metric,
        unit=unit,
        target_date=target_date,
        resolution_source_url=res_source,
        precision=precision,
        brackets=parsed_brackets,
        raw_description=description
    )
