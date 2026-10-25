"""Shared paths and parameters for the Saskatchewan emergency healthcare access project."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
GDB = ROOT / "data" / "sk_health_access.gdb"
OUTPUTS = ROOT / "outputs"
FIGURES = ROOT / "figures"
MAPS = ROOT / "maps"
APRX = ROOT / "SK_Health_Access.aprx"

# NAD 1983 Statistics Canada Lambert: equal-area-friendly conformal projection used by StatCan
SR_WKID = 3347
SK_PRUID = "47"

# Drive-time thresholds (minutes) used for service areas and coverage summaries
BREAKS = [15, 30, 60, 90]
COVERAGE_CUTOFF = 30  # minutes, used for location-allocation
TRAVEL_MODE = "Driving Time"

# Eight largest cities: name -> 2021 census subdivision UID
CITIES = {
    "Saskatoon": "4711066", "Regina": "4706027", "Prince Albert": "4715066",
    "Moose Jaw": "4707039", "Yorkton": "4709012", "Swift Current": "4708004",
    "North Battleford": "4716029", "Lloydminster": "4717029",
}
CITY_BREAKS = [5, 10, 15]  # minutes; provincial bands are too coarse inside cities
ND = GDB / "Transport" / "Roads_ND"

# Default speeds (km/h) by NRN road class, used when the NRN speed field is missing
DEFAULT_SPEED = {
    "Freeway": 110, "Expressway / Highway": 100, "Arterial": 80,
    "Collector": 70, "Local / Street": 50, "Local / Strata": 40,
    "Local / Unknown": 50, "Alleyway / Lane": 20, "Ramp": 60,
    "Resource / Recreation": 50, "Rapid Transit": 0, "Service Lane": 30,
    "Winter": 0,
}
UNPAVED_FACTOR = 0.8  # gravel and dirt roads are driven slower than the posted limit
