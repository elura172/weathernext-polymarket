"""
Registry of official meteorological stations used in Polymarket weather contracts.
Maps station ICAO / identifiers to coordinates, timezones, and resolution conventions.
"""
from dataclasses import dataclass
from typing import Optional, Dict

@dataclass(frozen=True)
class StationMetadata:
    icao: str
    name: str
    city: str
    country: str
    lat: float
    lon: float
    timezone: str
    default_unit: str  # "F" or "C"
    precision: float   # 1.0 or 0.1
    elevation_m: float = 0.0
    microclimate_bias_c: float = 0.0  # Station-specific microclimate / UHI offset in °C vs regional grid
    station_type: str = "airport"     # "airport", "urban_park", "coastal_airport", "mountain_plains"
    metar_icao: Optional[str] = None

    @property
    def effective_metar_icao(self) -> str:
        return (self.metar_icao or self.icao).upper()

STATION_CATALOG: Dict[str, StationMetadata] = {
    # United States (NWS / NOAA WRH)
    "kdal": StationMetadata("kdal", "Dallas Love Field", "Dallas", "USA", 32.8471, -96.8517, "America/Chicago", "F", 1.0, 148.0, 0.3, "airport", "KDAL"),
    "kdfw": StationMetadata("kdfw", "Dallas/Fort Worth Intl", "Dallas", "USA", 32.8998, -97.0403, "America/Chicago", "F", 1.0, 185.0, 0.1, "airport", "KDFW"),
    "knyc": StationMetadata("knyc", "NYC Central Park", "New York", "USA", 40.7829, -73.9654, "America/New_York", "F", 1.0, 48.0, 0.6, "urban_park", "KNYC"),
    "klga": StationMetadata("klga", "LaGuardia Airport", "New York", "USA", 40.7769, -73.8740, "America/New_York", "F", 1.0, 6.0, 0.8, "coastal_airport", "KLGA"),
    "kjfk": StationMetadata("kjfk", "JFK International", "New York", "USA", 40.6413, -73.7781, "America/New_York", "F", 1.0, 4.0, -0.3, "coastal_airport", "KJFK"),
    "kord": StationMetadata("kord", "Chicago O'Hare Intl", "Chicago", "USA", 41.9742, -87.9073, "America/Chicago", "F", 1.0, 203.0, 0.2, "airport", "KORD"),
    "kmdw": StationMetadata("kmdw", "Chicago Midway", "Chicago", "USA", 41.7868, -87.7522, "America/Chicago", "F", 1.0, 189.0, 0.7, "airport", "KMDW"),
    "kden": StationMetadata("kden", "Denver International", "Denver", "USA", 39.8561, -104.6737, "America/Denver", "F", 1.0, 1655.0, -0.2, "mountain_plains", "KDEN"),
    "kbkf": StationMetadata("kbkf", "Buckley Space Force Base", "Denver", "USA", 39.7017, -104.7517, "America/Denver", "F", 1.0, 1722.0, 0.1, "airport", "KBKF"),
    "khou": StationMetadata("khou", "Houston Hobby", "Houston", "USA", 29.6454, -95.2789, "America/Chicago", "F", 1.0, 14.0, 0.3, "airport", "KHOU"),
    "kiah": StationMetadata("kiah", "Houston Bush Intercontinental", "Houston", "USA", 29.9902, -95.3368, "America/Chicago", "F", 1.0, 30.0, 0.1, "airport", "KIAH"),
    "kmia": StationMetadata("kmia", "Miami International", "Miami", "USA", 25.7959, -80.2870, "America/New_York", "F", 1.0, 3.0, 0.2, "coastal_airport", "KMIA"),
    "kaus": StationMetadata("kaus", "Austin-Bergstrom Intl", "Austin", "USA", 30.1975, -97.6664, "America/Chicago", "F", 1.0, 150.0, 0.2, "airport", "KAUS"),
    "katl": StationMetadata("katl", "Atlanta Hartsfield-Jackson", "Atlanta", "USA", 33.6407, -84.4277, "America/New_York", "F", 1.0, 313.0, 0.3, "airport", "KATL"),
    "klax": StationMetadata("klax", "Los Angeles International", "Los Angeles", "USA", 33.9416, -118.4085, "America/Los_Angeles", "F", 1.0, 38.0, -0.5, "coastal_airport", "KLAX"),
    "ksfo": StationMetadata("ksfo", "San Francisco International", "San Francisco", "USA", 37.6213, -122.3790, "America/Los_Angeles", "F", 1.0, 4.0, -0.8, "coastal_airport", "KSFO"),

    # Canada & Americas
    "cyyz": StationMetadata("cyyz", "Toronto Pearson Intl", "Toronto", "Canada", 43.6777, -79.6248, "America/Toronto", "C", 1.0, 173.0, 0.2, "airport", "CYYZ"),
    "sbsp": StationMetadata("sbsp", "São Paulo Congonhas", "Sao Paulo", "Brazil", -23.6261, -46.6564, "America/Sao_Paulo", "C", 1.0, 802.0, 0.4, "airport", "SBSP"),
    "saez": StationMetadata("saez", "Buenos Aires Ezeiza", "Buenos Aires", "Argentina", -34.8222, -58.5358, "America/Argentina/Buenos_Aires", "C", 1.0, 20.0, 0.1, "airport", "SAEZ"),
    "mmmx": StationMetadata("mmmx", "Mexico City Benito Juárez", "Mexico City", "Mexico", 19.4361, -99.0719, "America/Mexico_City", "C", 1.0, 2230.0, -0.2, "mountain_plains", "MMMX"),
    "mppt": StationMetadata("mppt", "Panama City Tocumen", "Panama City", "Panama", 9.0714, -79.3835, "America/Panama", "C", 1.0, 14.0, 0.2, "coastal_airport", "MPTO"),

    # Europe
    "egll": StationMetadata("egll", "London Heathrow", "London", "UK", 51.4700, -0.4543, "Europe/London", "C", 1.0, 25.0, 0.4, "airport", "EGLL"),
    "lfpg": StationMetadata("lfpg", "Paris Charles de Gaulle", "Paris", "France", 49.0097, 2.5479, "Europe/Paris", "C", 1.0, 119.0, 0.2, "airport", "LFPG"),
    "eham": StationMetadata("eham", "Amsterdam Schiphol", "Amsterdam", "Netherlands", 52.3105, 4.7683, "Europe/Amsterdam", "C", 1.0, -3.0, -0.3, "coastal_airport", "EHAM"),
    "eddm": StationMetadata("eddm", "Munich Airport", "Munich", "Germany", 48.3537, 11.7860, "Europe/Berlin", "C", 1.0, 453.0, 0.1, "airport", "EDDM"),
    "lemd": StationMetadata("lemd", "Madrid Barajas", "Madrid", "Spain", 40.4839, -3.5680, "Europe/Madrid", "C", 1.0, 610.0, 0.3, "airport", "LEMD"),
    "limc": StationMetadata("limc", "Milan Malpensa", "Milan", "Italy", 45.6301, 8.7255, "Europe/Rome", "C", 1.0, 234.0, 0.1, "airport", "LIMC"),
    "epwa": StationMetadata("epwa", "Warsaw Chopin", "Warsaw", "Poland", 52.1672, 20.9679, "Europe/Warsaw", "C", 1.0, 110.0, 0.2, "airport", "EPWA"),
    "efhk": StationMetadata("efhk", "Helsinki Vantaa", "Helsinki", "Finland", 60.3172, 24.9633, "Europe/Helsinki", "C", 1.0, 55.0, 0.1, "airport", "EFHK"),
    "uuee": StationMetadata("uuee", "Moscow Sheremetyevo", "Moscow", "Russia", 55.9726, 37.4146, "Europe/Moscow", "C", 1.0, 192.0, 0.2, "airport", "UUEE"),
    "ltfm": StationMetadata("ltfm", "Istanbul Airport", "Istanbul", "Turkey", 41.2753, 28.7519, "Europe/Istanbul", "C", 1.0, 99.0, 0.1, "coastal_airport", "LTFM"),
    "ltac": StationMetadata("ltac", "Ankara Esenboga", "Ankara", "Turkey", 40.1281, 32.9951, "Europe/Istanbul", "C", 1.0, 953.0, 0.0, "mountain_plains", "LTAC"),

    # Asia & Pacific
    "vhhh": StationMetadata("vhhh", "Hong Kong Observatory", "Hong Kong", "Hong Kong", 22.3022, 114.1747, "Asia/Hong_Kong", "C", 0.1, 32.0, 0.5, "urban_park", "VHHH"),
    "rksi": StationMetadata("rksi", "Seoul Incheon Intl", "Seoul", "South Korea", 37.4602, 126.4407, "Asia/Seoul", "C", 1.0, 7.0, -0.3, "coastal_airport", "RKSI"),
    "rkpk": StationMetadata("rkpk", "Busan Gimhae Intl", "Busan", "South Korea", 35.1795, 128.9382, "Asia/Seoul", "C", 1.0, 4.0, -0.2, "coastal_airport", "RKPK"),
    "zsss": StationMetadata("zsss", "Shanghai Hongqiao", "Shanghai", "China", 31.1979, 121.3363, "Asia/Shanghai", "C", 1.0, 3.0, 0.6, "airport", "ZSSS"),
    "zbaa": StationMetadata("zbaa", "Beijing Capital Intl", "Beijing", "China", 40.0799, 116.6031, "Asia/Shanghai", "C", 1.0, 35.0, 0.5, "airport", "ZBAA"),
    "zggp": StationMetadata("zggp", "Guangzhou Baiyun", "Guangzhou", "China", 23.3924, 113.2988, "Asia/Shanghai", "C", 1.0, 15.0, 0.4, "airport", "ZGSD"),
    "zgsz": StationMetadata("zgsz", "Shenzhen Bao'an", "Shenzhen", "China", 22.6393, 113.8107, "Asia/Shanghai", "C", 1.0, 4.0, 0.3, "coastal_airport", "ZGSZ"),
    "zuuu": StationMetadata("zuuu", "Chengdu Shuangliu", "Chengdu", "China", 30.5785, 103.9471, "Asia/Shanghai", "C", 1.0, 504.0, 0.3, "airport", "ZUUU"),
    "zuck": StationMetadata("zuck", "Chongqing Jiangbei", "Chongqing", "China", 29.7192, 106.6417, "Asia/Shanghai", "C", 1.0, 416.0, 0.4, "mountain_plains", "ZUCK"),
    "zhhh": StationMetadata("zhhh", "Wuhan Tianhe", "Wuhan", "China", 30.7838, 114.2081, "Asia/Shanghai", "C", 1.0, 34.0, 0.3, "airport", "ZHHH"),
    "zsqd": StationMetadata("zsqd", "Qingdao Jiaodong", "Qingdao", "China", 36.2661, 120.0883, "Asia/Shanghai", "C", 1.0, 12.0, -0.3, "coastal_airport", "ZSQD"),
    "rctp": StationMetadata("rctp", "Taipei Taoyuan Intl", "Taipei", "Taiwan", 25.0797, 121.2342, "Asia/Taipei", "C", 1.0, 32.0, 0.2, "airport", "RCTP"),
    "wsss": StationMetadata("wsss", "Singapore Changi", "Singapore", "Singapore", 1.3644, 103.9915, "Asia/Singapore", "C", 1.0, 7.0, 0.3, "coastal_airport", "WSSS"),
    "wmkk": StationMetadata("wmkk", "Kuala Lumpur Intl", "Kuala Lumpur", "Malaysia", 2.7456, 101.7099, "Asia/Kuala_Lumpur", "C", 1.0, 21.0, 0.2, "airport", "WMKK"),
    "rpll": StationMetadata("rpll", "Manila Ninoy Aquino", "Manila", "Philippines", 14.5086, 121.0194, "Asia/Manila", "C", 1.0, 23.0, 0.4, "airport", "RPLL"),
    "oejn": StationMetadata("oejn", "Jeddah King Abdulaziz", "Jeddah", "Saudi Arabia", 21.6796, 39.1565, "Asia/Riyadh", "C", 1.0, 15.0, 0.3, "coastal_airport", "OEJN"),
    "opkc": StationMetadata("opkc", "Karachi Jinnah Intl", "Karachi", "Pakistan", 24.9065, 67.1608, "Asia/Karachi", "C", 1.0, 30.0, 0.2, "airport", "OPKC"),
    "llbg": StationMetadata("llbg", "Tel Aviv Ben Gurion", "Tel Aviv", "Israel", 32.0055, 34.8854, "Asia/Jerusalem", "C", 1.0, 41.0, 0.2, "airport", "LLBG"),
    "nzwn": StationMetadata("nzwn", "Wellington International", "Wellington", "New Zealand", -41.3276, 174.8076, "Pacific/Auckland", "C", 1.0, 12.0, -0.4, "coastal_airport", "NZWN"),
    "fact": StationMetadata("fact", "Cape Town International", "Cape Town", "South Africa", -33.9715, 18.6021, "Africa/Johannesburg", "C", 1.0, 42.0, -0.3, "coastal_airport", "FACT"),
    "vilk": StationMetadata("vilk", "Lucknow Chaudhary Charan Singh", "Lucknow", "India", 26.7606, 80.8893, "Asia/Kolkata", "C", 1.0, 123.0, 0.2, "airport", "VILK"),
}

# City name alias mapping to station code
CITY_TO_STATION: Dict[str, str] = {
    "dallas": "kdal",
    "new york": "knyc",
    "nyc": "knyc",
    "chicago": "kord",
    "denver": "kden",
    "houston": "khou",
    "miami": "kmia",
    "austin": "kaus",
    "atlanta": "katl",
    "los angeles": "klax",
    "san francisco": "ksfo",
    "toronto": "cyyz",
    "sao paulo": "sbsp",
    "buenos aires": "saez",
    "mexico city": "mmmx",
    "panama city": "mppt",
    "london": "egll",
    "paris": "lfpg",
    "amsterdam": "eham",
    "munich": "eddm",
    "madrid": "lemd",
    "milan": "limc",
    "warsaw": "epwa",
    "helsinki": "efhk",
    "moscow": "uuee",
    "istanbul": "ltfm",
    "ankara": "ltac",
    "hong kong": "vhhh",
    "seoul": "rksi",
    "busan": "rkpk",
    "shanghai": "zsss",
    "beijing": "zbaa",
    "guangzhou": "zggp",
    "shenzhen": "zgsz",
    "chengdu": "zuuu",
    "chongqing": "zuck",
    "wuhan": "zhhh",
    "qingdao": "zsqd",
    "taipei": "rctp",
    "singapore": "wsss",
    "kuala lumpur": "wmkk",
    "manila": "rpll",
    "jeddah": "oejn",
    "karachi": "opkc",
    "tel aviv": "llbg",
    "wellington": "nzwn",
    "cape town": "fact",
    "lucknow": "vilk",
}

def resolve_station(identifier: str) -> Optional[StationMetadata]:
    """Look up station by ICAO code or city name."""
    clean_id = identifier.lower().strip()
    if clean_id in STATION_CATALOG:
        return STATION_CATALOG[clean_id]
    if clean_id in CITY_TO_STATION:
        return STATION_CATALOG[CITY_TO_STATION[clean_id]]
    # Substring match on city
    for city_name, station_code in CITY_TO_STATION.items():
        if city_name in clean_id:
            return STATION_CATALOG[station_code]
    return None
