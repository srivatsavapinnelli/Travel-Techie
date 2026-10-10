"""
Sample destination data for the Trip Navigator.

Destinations: Goa, Jaipur, Manali, Kerala (Kochi & Alleppey), Hyderabad.

IMPORTANT: this is SAMPLE data. Coordinates are approximate (good enough to draw
a map and plan a route, not surveyed) and costs are rough per-person INR figures,
not live prices. Every stop has an "Open in Maps" link in the UI so you can verify
a location. To add a destination, add another key to DESTINATIONS with the same
shape: nothing else in the code has to change.

Place row:  id, name, lat, lng, cost (INR per person), visit_min, rating, category, region
Stay row:   id, label, lat, lng, price per night per room (INR), rating, food per person per day (INR)
"""
from __future__ import annotations

_KEYS_P = ("id", "name", "lat", "lng", "cost", "visit_min", "rating", "category", "region")
_KEYS_S = ("id", "label", "lat", "lng", "price_per_night", "rating", "food_per_person_day")


def _dest(tagline, center, region_labels, config, places, stays):
    return {
        "tagline": tagline,
        "center": center,
        "region_labels": region_labels,
        # avg_speed_kmh / road_factor only drive the pre-routing ESTIMATES (real distances come from OSRM);
        # cab_rate_per_km and cab_reserve_per_day drive the local transport cost.
        "config": config,
        "places": [dict(zip(_KEYS_P, row)) for row in places],
        "stays": [dict(zip(_KEYS_S, row)) for row in stays],
    }


# ---------------------------------------------------------------------------
# GOA
# ---------------------------------------------------------------------------
_GOA = _dest(
    "Beaches, forts and Portuguese heritage",
    (15.4989, 73.8278),
    {"north": "North Goa coast", "central": "Old Goa & Panjim", "south": "South & East Goa"},
    {"avg_speed_kmh": 35, "road_factor": 1.35, "cab_rate_per_km": 14, "cab_reserve_per_day": 800},
    [
        ("chapora",    "Chapora Fort",                    15.6055, 73.7360,    0,  45, 4.3, "heritage",  "north"),
        ("vagator",    "Vagator Beach",                   15.5981, 73.7447,    0,  90, 4.3, "beach",     "north"),
        ("anjuna",     "Anjuna Beach",                    15.5736, 73.7413,    0,  90, 4.2, "beach",     "north"),
        ("baga",       "Baga Beach",                      15.5553, 73.7517,    0, 120, 4.2, "beach",     "north"),
        ("watersport", "Water sports at Baga",            15.5560, 73.7510, 1800, 120, 4.3, "adventure",  "north"),
        ("calangute",  "Calangute Beach",                 15.5439, 73.7553,    0,  90, 4.1, "beach",     "north"),
        ("aguada",     "Fort Aguada",                     15.4925, 73.7737,    0,  60, 4.4, "heritage",  "north"),
        ("basilica",   "Basilica of Bom Jesus",           15.5009, 73.9116,    0,  45, 4.6, "heritage",  "central"),
        ("se",         "Se Cathedral",                    15.5037, 73.9120,    0,  30, 4.5, "heritage",  "central"),
        ("fontainhas", "Fontainhas Latin Quarter",        15.4987, 73.8310,    0,  90, 4.5, "culture",   "central"),
        ("cruise",     "Mandovi River sunset cruise",     15.5010, 73.8272,  500,  60, 4.0, "cruise",     "central"),
        ("miramar",    "Miramar Beach",                   15.4818, 73.8084,    0,  60, 4.0, "beach",     "central"),
        ("donapaula",  "Dona Paula viewpoint",            15.4520, 73.8000,    0,  45, 4.2, "viewpoint", "central"),
        ("spice",      "Spice plantation, Ponda",         15.4030, 74.0150,  600, 120, 4.2, "culture",    "central"),
        ("grande",     "Scuba at Grande Island",          15.3991, 73.7603, 3500, 300, 4.4, "adventure",  "south"),
        ("dudhsagar",  "Dudhsagar Falls (jeep safari)",   15.3144, 74.3143,  800, 240, 4.5, "nature",     "south"),
        ("palolem",    "Palolem Beach",                   15.0100, 74.0232,    0, 120, 4.5, "beach",     "south"),
    ],
    [
        ("budget", "Budget guesthouse, Calangute", 15.5439, 73.7553, 1800, 3.9,  600),
        ("mid",    "Mid-range hotel, Panjim",      15.4989, 73.8278, 4200, 4.2,  900),
        ("resort", "Beach resort, Candolim",       15.5180, 73.7620, 8500, 4.6, 1500),
    ],
)

# ---------------------------------------------------------------------------
# JAIPUR
# ---------------------------------------------------------------------------
_JAIPUR = _dest(
    "Forts, palaces and bazaars of the Pink City",
    (26.9124, 75.8000),
    {"old_city": "Old Pink City", "amber": "Amer & hill forts", "south": "South Jaipur & outskirts"},
    {"avg_speed_kmh": 25, "road_factor": 1.4, "cab_rate_per_km": 12, "cab_reserve_per_day": 700},
    [
        ("hawamahal", "Hawa Mahal",                          26.9239, 75.8267,   50,  30, 4.5, "heritage",  "old_city"),
        ("citypalace","City Palace",                         26.9258, 75.8237,  400,  90, 4.6, "heritage",  "old_city"),
        ("jantar",    "Jantar Mantar observatory",           26.9247, 75.8246,  200,  45, 4.5, "heritage",  "old_city"),
        ("albert",    "Albert Hall Museum",                  26.9118, 75.8195,   50,  60, 4.3, "culture",   "old_city"),
        ("johari",    "Johari Bazaar shopping walk",         26.9188, 75.8266,    0,  90, 4.2, "shopping",  "old_city"),
        ("lassi",     "Lassi and street-food stop",          26.9156, 75.8072,  400,  60, 4.4, "food",      "old_city"),
        ("galta",     "Galtaji temple complex",              26.9187, 75.8592,    0,  60, 4.1, "religious", "old_city"),
        ("amber",     "Amber Fort",                          26.9855, 75.8513,  200, 120, 4.7, "heritage",  "amber"),
        ("jaigarh",   "Jaigarh Fort",                        26.9853, 75.8446,  150,  75, 4.4, "heritage",  "amber"),
        ("panna",     "Panna Meena ka Kund stepwell",        26.9871, 75.8560,    0,  30, 4.2, "heritage",  "amber"),
        ("jalmahal",  "Jal Mahal (photo stop)",              26.9535, 75.8466,    0,  30, 4.1, "viewpoint", "amber"),
        ("nahargarh", "Nahargarh Fort sunset",               26.9372, 75.8155,  200,  90, 4.5, "viewpoint", "amber"),
        ("birla",     "Birla Mandir",                        26.8920, 75.8157,    0,  40, 4.5, "religious", "south"),
        ("sisodia",   "Sisodia Rani Garden",                 26.8990, 75.8554,   50,  45, 4.0, "nature",    "south"),
        ("chokhi",    "Chokhi Dhani village dinner",         26.7690, 75.8430, 1200, 180, 4.3, "culture",   "south"),
    ],
    [
        ("budget", "Budget stay near Hawa Mahal",      26.9220, 75.8230, 1500, 3.9,  500),
        ("mid",    "Mid-range hotel, C-Scheme",        26.9066, 75.8003, 4000, 4.2,  800),
        ("resort", "Heritage palace hotel, Bani Park", 26.9300, 75.7925, 9000, 4.6, 1400),
    ],
)

# ---------------------------------------------------------------------------
# MANALI
# ---------------------------------------------------------------------------
_MANALI = _dest(
    "Mountains, snow and adventure in Himachal",
    (32.2396, 77.1887),
    {"town": "Manali town & Old Manali", "solang": "Solang & Rohtang side", "naggar": "Naggar & Kullu valley"},
    {"avg_speed_kmh": 22, "road_factor": 2.0, "cab_rate_per_km": 20, "cab_reserve_per_day": 1200},
    [
        ("hadimba",   "Hadimba Devi Temple",                       32.2478, 77.1800,    0,  45, 4.5, "religious", "town"),
        ("mall",      "Mall Road & Tibetan market",                32.2432, 77.1892,    0,  90, 4.2, "shopping",  "town"),
        ("oldmanali", "Old Manali cafes and bridge walk",          32.2552, 77.1835,    0,  90, 4.4, "culture",   "town"),
        ("manu",      "Manu Temple",                               32.2549, 77.1773,    0,  30, 4.0, "religious", "town"),
        ("vashisht",  "Vashisht hot springs & temple",             32.2646, 77.1894,    0,  60, 4.2, "culture",   "town"),
        ("jogini",    "Jogini Falls trek",                         32.2815, 77.1884,    0, 150, 4.4, "nature",    "town"),
        ("solang",    "Solang Valley",                             32.3160, 77.1580,    0, 120, 4.5, "nature",    "solang"),
        ("paraglide", "Paragliding at Solang",                     32.3150, 77.1585, 3500,  90, 4.6, "adventure", "solang"),
        ("snowfun",   "Solang snow activities (ropeway/ATV)",      32.3170, 77.1565, 1500,  90, 4.1, "adventure", "solang"),
        ("rohtang",   "Rohtang Pass (seasonal, permit needed)",    32.3716, 77.2466, 1000, 200, 4.5, "nature",    "solang"),
        ("naggar",    "Naggar Castle & Roerich Gallery",           32.1235, 77.1728,  100,  90, 4.3, "heritage",  "naggar"),
        ("raghunath", "Raghunath Temple, Kullu",                   31.9570, 77.1090,    0,  45, 4.3, "religious", "naggar"),
        ("rafting",   "Beas river rafting",                        32.0850, 77.1750, 1000, 120, 4.4, "adventure", "naggar"),
    ],
    [
        ("budget", "Hostel in Old Manali",        32.2552, 77.1835, 1200, 4.0,  500),
        ("mid",    "Hotel on Mall Road",          32.2432, 77.1892, 3800, 4.2,  800),
        ("resort", "Valley-view resort, Prini",   32.2690, 77.1790, 8500, 4.6, 1400),
    ],
)

# ---------------------------------------------------------------------------
# KERALA (Kochi & Alleppey)
# ---------------------------------------------------------------------------
_KERALA = _dest(
    "Heritage Kochi, backwaters and beaches",
    (9.9312, 76.2673),
    {"fort": "Fort Kochi & Mattancherry", "city": "Ernakulam city", "backwaters": "Backwaters (Kumbalangi & Alleppey)", "cherai": "Cherai beach"},
    {"avg_speed_kmh": 28, "road_factor": 1.45, "cab_rate_per_km": 13, "cab_reserve_per_day": 700},
    [
        ("nets",      "Chinese fishing nets",                9.9658, 76.2417,    0,  45, 4.3, "culture",   "fort"),
        ("stfrancis", "St. Francis Church",                  9.9644, 76.2432,    0,  30, 4.2, "heritage",  "fort"),
        ("santacruz", "Santa Cruz Basilica",                 9.9650, 76.2410,    0,  30, 4.4, "religious", "fort"),
        ("mattan",    "Mattancherry (Dutch) Palace",         9.9577, 76.2597,    5,  45, 4.1, "heritage",  "fort"),
        ("jewtown",   "Jew Town & Paradesi Synagogue",       9.9570, 76.2590,   10,  60, 4.3, "culture",   "fort"),
        ("kathakali", "Kathakali performance",               9.9660, 76.2440,  500,  90, 4.3, "culture",   "fort"),
        ("marine",    "Marine Drive promenade",              9.9769, 76.2754,    0,  60, 4.1, "viewpoint", "city"),
        ("lulu",      "Lulu Mall",                          10.0272, 76.3088,    0, 120, 4.5, "shopping",  "city"),
        ("mangala",   "Mangalavanam bird sanctuary",         9.9945, 76.2753,    0,  60, 4.0, "nature",    "city"),
        ("hillpalace","Hill Palace Museum, Tripunithura",    9.9497, 76.3460,   30,  90, 4.2, "heritage",  "city"),
        ("kumbalangi","Kumbalangi eco-village",              9.8870, 76.2850,  300, 120, 4.2, "culture",   "backwaters"),
        ("alleppey",  "Alleppey backwater cruise (day)",     9.4981, 76.3388, 1500, 360, 4.7, "nature",    "backwaters"),
        ("cherai",    "Cherai Beach",                       10.1420, 76.1780,    0, 120, 4.3, "beach",     "cherai"),
    ],
    [
        ("budget", "Homestay, Fort Kochi",             9.9650, 76.2430, 2000, 4.1,  600),
        ("mid",    "Hotel on MG Road, Ernakulam",      9.9680, 76.2860, 4300, 4.3,  900),
        ("resort", "Heritage resort, Fort Kochi",      9.9640, 76.2420, 9500, 4.6, 1500),
    ],
)

# ---------------------------------------------------------------------------
# HYDERABAD
# ---------------------------------------------------------------------------
_HYDERABAD = _dest(
    "Nizam-era heritage, biryani and film city",
    (17.3850, 78.4867),
    {"old_city": "Old City", "city": "Central Hyderabad", "west": "Golconda & Hitec side", "outskirts": "Outskirts (Ramoji)"},
    {"avg_speed_kmh": 22, "road_factor": 1.4, "cab_rate_per_km": 13, "cab_reserve_per_day": 700},
    [
        ("charminar", "Charminar",                           17.3616, 78.4747,   25,  45, 4.4, "heritage",  "old_city"),
        ("meccamasjid","Mecca Masjid",                       17.3604, 78.4736,    0,  30, 4.4, "religious", "old_city"),
        ("laad",      "Laad Bazaar bangle shopping",         17.3620, 78.4730,    0,  60, 4.1, "shopping",  "old_city"),
        ("chowmahalla","Chowmahalla Palace",                 17.3578, 78.4717,   80,  90, 4.5, "heritage",  "old_city"),
        ("salarjung", "Salar Jung Museum",                   17.3713, 78.4804,   50, 120, 4.4, "culture",   "old_city"),
        ("zoo",       "Nehru Zoological Park",               17.3510, 78.4513,   60, 180, 4.1, "nature",    "old_city"),
        ("hussain",   "Hussain Sagar & Buddha statue",       17.4239, 78.4738,  100,  60, 4.3, "viewpoint", "city"),
        ("birla",     "Birla Mandir",                        17.4062, 78.4691,    0,  45, 4.5, "religious", "city"),
        ("necklace",  "Necklace Road promenade",             17.4150, 78.4640,    0,  60, 4.1, "nature",    "city"),
        ("biryani",   "Biryani and Irani chai food trail",   17.3880, 78.4740,  700,  90, 4.6, "food",      "city"),
        ("golconda",  "Golconda Fort & light show",          17.3833, 78.4011,  150, 150, 4.5, "heritage",  "west"),
        ("qutb",      "Qutb Shahi Tombs",                    17.3948, 78.3947,   25,  60, 4.3, "heritage",  "west"),
        ("shilpa",    "Shilparamam crafts village",          17.4529, 78.3810,   60,  90, 4.1, "culture",   "west"),
        ("ramoji",    "Ramoji Film City",                    17.2543, 78.6808, 1800, 480, 4.3, "adventure", "outskirts"),
    ],
    [
        ("budget", "Budget hotel, Abids",            17.3890, 78.4760, 1600, 3.9,  500),
        ("mid",    "Hotel in Banjara Hills",         17.4120, 78.4390, 4500, 4.3,  900),
        ("resort", "Luxury hotel, Hitec City",       17.4435, 78.3772, 8500, 4.6, 1500),
    ],
)

DESTINATIONS = {
    "Goa": _GOA,
    "Jaipur": _JAIPUR,
    "Manali": _MANALI,
    "Kerala": _KERALA,
    "Hyderabad": _HYDERABAD,
}
