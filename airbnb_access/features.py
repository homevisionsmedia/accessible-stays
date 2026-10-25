"""Amenities normalized into the filter options of the report's search panel.

Groups and labels follow Airbnb's own Filters panel. Matching is on the
amenity names hosts select (e.g. "Free washer - In unit" -> washer).
"""

import re

# (key, label, group, pattern)
FEATURES = [
    ("step_free_entrance", "Step-free guest entrance", "Accessibility features", r"step-free guest entrance"),
    ("wide_entrance", "Guest entrance wider than 32 in", "Accessibility features", r"guest entrance wider than"),
    ("step_free_path", "Step-free path to entrance", "Accessibility features", r"step-free path"),
    ("accessible_parking", "Accessible parking spot", "Accessibility features", r"(?:accessible|disabled) parking"),
    ("step_free_bedroom", "Step-free bedroom access", "Accessibility features", r"step-free bedroom"),
    ("wide_bedroom", "Bedroom entrance wider than 32 in", "Accessibility features", r"bedroom entrance wider than"),
    ("step_free_bathroom", "Step-free bathroom access", "Accessibility features", r"step-free bathroom"),
    ("wide_bathroom", "Bathroom entrance wider than 32 in", "Accessibility features", r"bathroom entrance wider than"),
    ("step_free_shower", "Step-free shower", "Accessibility features", r"step-free shower"),
    ("shower_grab_bar", "Shower grab bar", "Accessibility features", r"shower grab bar"),
    ("toilet_grab_bar", "Toilet grab bar", "Accessibility features", r"toilet grab bar"),
    ("shower_chair", "Shower or bath chair", "Accessibility features", r"shower or bath chair"),
    ("hoist", "Ceiling or mobile hoist", "Accessibility features", r"hoist"),
    ("single_level", "Single level home", "Accessibility features", r"single level home"),
    ("elevator", "Elevator", "Accessibility features", r"\belevator\b"),
    ("wifi", "Wifi", "Amenities", r"\bwifi\b"),
    ("kitchen", "Kitchen", "Amenities", r"\bkitchen\b"),
    ("washer", "Washer", "Amenities", r"\bwasher\b"),
    ("dryer", "Dryer", "Amenities", r"(?<!hair )\bdryer\b"),
    ("ac", "Air conditioning", "Amenities", r"air conditioning|\bac\b"),
    ("heating", "Heating", "Amenities", r"\bheating\b"),
    ("workspace", "Dedicated workspace", "Amenities", r"dedicated workspace"),
    ("tv", "TV", "Amenities", r"\b(?:hd)?tv\b"),
    ("free_parking", "Free parking on premises", "Amenities", r"free (?:driveway |carport |garage |residential garage )?parking on premises"),
    ("ev_charger", "EV charger", "Amenities", r"ev charger"),
    ("pool", "Pool", "Amenities", r"\bpool\b(?! table)"),
    ("hot_tub", "Hot tub", "Amenities", r"hot tub"),
    ("crib", "Crib", "Amenities", r"\bcrib\b"),
    ("bbq", "BBQ grill", "Amenities", r"bbq grill"),
    ("fireplace", "Indoor fireplace", "Amenities", r"indoor fireplace"),
    ("gym", "Gym", "Amenities", r"\bgym\b|exercise equipment"),
    ("self_checkin", "Self check-in", "Booking options", r"self check-in"),
    ("pets", "Allows pets", "Booking options", r"pets allowed"),
]

_COMPILED = [(k, re.compile(p, re.I)) for k, _, _, p in FEATURES]


def tags(amenities):
    """Feature keys present in a list of available amenity names."""
    found = []
    for key, pattern in _COMPILED:
        if any(pattern.search(a) for a in amenities):
            found.append(key)
    return found


def meta():
    return [{"key": k, "label": l, "group": g} for k, l, g, _ in FEATURES]
