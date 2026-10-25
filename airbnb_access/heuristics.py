"""Fast keyword/amenity rating. No photos, no API calls.

Used two ways: as a pre-filter (listings that are plainly inaccessible,
e.g. a fourth-floor walk-up, are not worth a Claude review) and as the
rating when no Claude review runs. Every category starts at 7, "unverified":
silence about accessibility is not evidence of it.
"""

import re

from . import scoring
from .sources import Listing

UNVERIFIED = 7

# (category, pattern, delta, label). Negative delta = more accessible.
TEXT_RULES = [
    # Explicit host statements
    ("host_features", r"\b(wheelchair|handicap(?:ped)?|ada)[- ](?:accessible|friendly|compliant)\b", -4, "Description says wheelchair/ADA accessible"),
    ("entrance", r"\b(wheelchair|handicap(?:ped)?|ada)[- ](?:accessible|friendly|compliant)\b", -2, "Description says wheelchair/ADA accessible"),
    # Entrance
    ("entrance", r"\b(?:step[- ]free|no steps|zero[- ]step|zero[- ]entry|no stairs|stair[- ]free|without stairs)\b", -3, "No steps mentioned"),
    ("entrance", r"\bramp(?:ed)?\b", -2, "Ramp mentioned"),
    ("entrance", r"\b(?:ground[- ]floor|ground[- ]level|street[- ]level|first[- ]floor)\b", -2, "Ground/first floor"),
    ("entrance", r"\b(?:walk[- ]?up|no elevator|no lift)\b", +3, "Walk-up / no elevator"),
    ("entrance", r"\b(?:\d+|one|two|three|four|five|several|a few|many|multiple|steep)\s+(?:flights?|steps|stairs)\b", +2, "Stairs counted in description"),
    ("entrance", r"\bflights? of stairs\b", +2, "Flight of stairs"),
    ("entrance", r"\b(?:2nd|3rd|4th|5th|6th|second|third|fourth|fifth|sixth|top)[- ]floor\b", +2, "Upper floor"),
    ("entrance", r"\bsteep (?:hill|driveway|stairs|steps|path|walk)\b", +2, "Steep approach"),
    ("entrance", r"\b(?:stairs|staircase|stairway|steps)\b", +1, "Stairs mentioned"),
    # Interior
    ("interior", r"\b(?:single[- ](?:level|story|storey|floor)|one[- ](?:level|story|storey)|all on one (?:level|floor)|ranch[- ]style)\b", -3, "Single level"),
    ("interior", r"\bwide (?:doorways|doors|hallways|halls)\b", -2, "Wide doorways/hallways"),
    ("interior", r"\bspiral stair", +3, "Spiral staircase"),
    ("interior", r"\bladder\b", +3, "Ladder"),
    ("interior", r"\blofts?\b", +2, "Loft"),
    ("interior", r"\b(?:split[- ]level|multi[- ]level|sunken|two[- ]stor(?:y|ey)|three[- ]stor(?:y|ey)|townhouse|townhome|duplex)\b", +2, "Multiple levels"),
    ("interior", r"\b(?:stairs|staircase|stairway)\b", +1, "Stairs mentioned"),
    # Bedroom
    ("bedroom", r"\b(?:bedroom|bed|suite) (?:is )?on (?:the )?(?:main|first|ground|entry) (?:floor|level)\b", -2, "Bedroom on main floor"),
    ("bedroom", r"\bbunk", +2, "Bunk beds"),
    ("bedroom", r"\b(?:upstairs bedrooms?|bedrooms? (?:are |is )?(?:up|down)stairs|loft(?:ed)? bed)\b", +3, "Bedroom up/down stairs"),
    # Bathroom
    ("bathroom", r"\b(?:roll[- ]in shower|curbless shower|zero[- ]entry shower|step[- ]free shower|barrier[- ]free shower)\b", -3, "Roll-in / curbless shower"),
    ("bathroom", r"\bwalk[- ]in shower\b", -1, "Walk-in shower (may still have a curb)"),
    ("bathroom", r"\bgrab ?bars?\b", -2, "Grab bars"),
    ("bathroom", r"\bshower (?:chair|bench|seat|stool)\b", -1, "Shower seat"),
    ("bathroom", r"\b(?:raised|comfort[- ]height|ada|accessible) toilet\b", -1, "Accessible-height toilet"),
    ("bathroom", r"\b(?:bath(?:room)?s? (?:is |are )?(?:up|down)stairs|upstairs bath(?:room)?s?)\b", +3, "Bathroom up/down stairs"),
    ("bathroom", r"\b(?:tub/shower|shower/tub|tub[- ]shower combo|shower over (?:the )?(?:bath|tub)|claw[- ]?foot)\b", +2, "Shower in a tub"),
    # Parking
    ("parking", r"\b(?:accessible|handicap(?:ped)?|disabled|ada) parking\b", -3, "Accessible parking"),
    ("parking", r"\b(?:driveway|garage|off[- ]street parking|parking (?:on|at) (?:the )?(?:premises|property))\b", -1, "On-site parking"),
    ("parking", r"\b(?:gravel|uneven|dirt road|unpaved|hike|hiking trail to)\b", +2, "Uneven or unpaved approach"),
]

# Phrases that would otherwise trigger the wrong rule above.
NEGATIONS = [
    # "steps from downtown" is about distance, not stairs
    (r"\b(?:just |only |mere |a few |few |within )?steps? (?:away|from)\b|\b(?:just|only|mere) steps\b", "nearby"),
    (r"\bno (?:stairs|steps)\b", "step-free"),
    (r"\bnot (?:wheelchair|handicap(?:ped)?|ada)[- ](?:accessible|friendly|compliant)\b", "NOT_ACCESSIBLE"),
]

NOT_ACCESSIBLE = re.compile(
    r"NOT_ACCESSIBLE|\bnot (?:be )?(?:suitable|recommended|ideal|appropriate|accessible) for (?:guests |people |those |anyone )?(?:with |in |using |who use )?(?:limited mobility|mobility|a wheelchair|wheelchairs|wheelchair users|disabilit|elderly|walkers)"
    r"|\bnot (?:wheelchair )?accessible\b|\bunable to accommodate wheelchairs?\b",
    re.I,
)

AMENITY_RULES = [
    ("entrance", "step-free guest entrance", -4),
    ("entrance", "step-free path", -2),
    ("entrance", "guest entrance wider than", -2),
    ("entrance", "elevator", -3),
    ("interior", "elevator", -1),
    ("interior", "single level home", -3),
    ("interior", "hoist", -1),
    ("bedroom", "single level home", -1),
    ("bedroom", "step-free bedroom access", -3),
    ("bedroom", "bedroom entrance wider than", -2),
    ("bedroom", "accessible-height bed", -1),
    ("bathroom", "single level home", -1),
    ("bathroom", "step-free bathroom access", -2),
    ("bathroom", "bathroom entrance wider than", -2),
    ("bathroom", "step-free shower", -3),
    ("bathroom", "grab bar", -1),
    ("bathroom", "shower or bath chair", -1),
    ("bathroom", "accessible-height toilet", -1),
    ("parking", "accessible parking", -4),
    ("parking", "disabled parking", -4),
    ("parking", "free parking on premises", -2),
    ("parking", "free street parking", -1),
]

ACCESSIBILITY_AMENITY_KEYS = (
    "step-free", "wider than 32", "wider than 81", "grab bar", "hoist", "accessible-height",
    "accessible parking", "disabled parking", "shower or bath chair", "single level home",
)

HARD_TYPES = re.compile(
    r"tree ?house|boat|houseboat|tent|yurt|cave|camper|\brv\b|tipi|teepee|dome|lighthouse|tower|windmill|barn|hut|shepherd|bus\b|campsite|island",
    re.I,
)


def available_amenities(listing: Listing):
    if listing.amenity_groups:
        return [
            a["title"]
            for title, items in listing.amenity_groups.items()
            if title.lower() != "not included"
            for a in items
            if a["available"]
        ]
    return listing.amenities


def rate(listing: Listing) -> dict:
    text = f"{listing.name}\n{listing.description}".lower()
    for pattern, replacement in NEGATIONS:
        text = re.sub(pattern, replacement, text, flags=re.I)
    amenities = [a.lower() for a in available_amenities(listing)]
    has_elevator = any("elevator" in a for a in amenities) or bool(re.search(r"(?<!no )\belevator\b", text))

    scores = {k: UNVERIFIED for k in scoring.CATEGORIES}
    evidence = {k: [] for k in scoring.CATEGORIES}
    hard_barriers = []

    for cat, pattern, delta, label in TEXT_RULES:
        m = re.search(pattern, text, re.I)
        if not m:
            continue
        if has_elevator and label in ("Upper floor", "Stairs mentioned", "Stairs counted in description", "Flight of stairs"):
            continue
        scores[cat] += delta
        evidence[cat].append(f'{label}: "...{_snippet(text, m)}..."')

    for cat, key, delta in AMENITY_RULES:
        match = next((a for a in amenities if key in a), None)
        if match:
            scores[cat] += delta
            evidence[cat].append(f"Amenity: {match}")

    declared = [a for a in amenities if any(k in a for k in ACCESSIBILITY_AMENITY_KEYS)]
    scores["host_features"] += round(2 - 1.5 * len(declared))
    if listing.accessibility_tour:
        scores["host_features"] -= 2
        evidence["host_features"].append(f"Accessibility photo tour with {len(listing.accessibility_tour)} item(s)")

    if HARD_TYPES.search(listing.property_type or ""):
        for cat in ("entrance", "interior"):
            scores[cat] += 3
            evidence[cat].append(f"Property type: {listing.property_type}")
        hard_barriers.append(f"Unusual structure ({listing.property_type})")
    elif "loft" in (listing.property_type or "").lower():
        scores["interior"] += 2
        evidence["interior"].append(f"Property type: {listing.property_type}")

    if re.search(r"walk[- ]?up|no elevator|no lift", text) and not has_elevator and re.search(
        r"\b(?:2nd|3rd|4th|5th|6th|second|third|fourth|fifth|sixth|top)[- ]floor\b", text
    ):
        hard_barriers.append("Upper-floor walk-up with no elevator")
    if re.search(r"spiral stair|\bladder\b", text):
        hard_barriers.append("Spiral staircase or ladder")
    if re.search(r"upstairs bedrooms?|bedrooms? (?:are |is )?upstairs", text) and not has_elevator \
            and not any("single level" in a for a in amenities):
        hard_barriers.append("Bedrooms are upstairs")

    blocking = bool(NOT_ACCESSIBLE.search(text))
    if blocking:
        hard_barriers.insert(0, "Host states the listing is not accessible")

    scores = {k: min(10, max(1, v)) for k, v in scores.items()}
    score = scoring.overall(scores, blocking, hard_barriers, method="heuristic")
    return {
        "method": "heuristic",
        "overall": score,
        "verdict": scoring.verdict(score),
        "confidence": "low",
        "categories": {
            k: {"score": scores[k], "findings": "; ".join(evidence[k]) or "No information found (unverified)."}
            for k in scoring.CATEGORIES
        },
        "hard_barriers": hard_barriers,
        "blocking_barrier": blocking,
        "questions_for_host": [],
        "photo_observations": [],
        "summary": "Keyword and amenity check only; photos were not reviewed.",
    }


def _snippet(text, m, width=50):
    start, end = max(0, m.start() - width), min(len(text), m.end() + width)
    return re.sub(r"\s+", " ", text[start:end]).strip()
