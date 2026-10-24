"""
Oracle specification and parsing helpers for Polymarket resolution sources.
"""
import re
from typing import Optional, Tuple

def extract_station_from_url(url: str) -> Optional[str]:
    """Extract station ICAO from official NOAA WRH or weather agency URLs."""
    if not url:
        return None
    # Pattern 1: NOAA WRH timeseries: ?site=kdal or &site=kdal
    match = re.search(r'[?&]site=([a-zA-Z0-9]+)', url, re.IGNORECASE)
    if match:
        return match.group(1).lower()
    
    # Pattern 2: NOAA station page /stations/kdal
    match = re.search(r'/stations/([a-zA-Z0-9]{4})', url, re.IGNORECASE)
    if match:
        return match.group(1).lower()

    # Pattern 3: Hong Kong Observatory
    if "weather.gov.hk" in url:
        return "vhhh"
        
    return None

def parse_resolution_precision(description: str) -> float:
    """Detect whether oracle resolves to whole degrees (1.0) or tenths (0.1)."""
    desc_lower = description.lower()
    if "one decimal place" in desc_lower or "0.1" in desc_lower:
        return 0.1
    return 1.0
