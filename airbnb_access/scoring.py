"""The 1-10 scale, the breakdown categories, and how they combine.

1 = ideal for a wheelchair user, 10 = not accessible, do not recommend.
Both the heuristic and the Claude review fill in the same categories, and
the overall score is always computed here so that it means the same thing
for every listing.
"""

CATEGORIES = {
    "entrance": {
        "label": "Arrival & entrance",
        "weight": 0.30,
        "question": "Can a wheelchair user get from the street or parking to inside the unit? Steps, ramps, elevators, path surface, entrance door width (32 in / 81 cm or more).",
    },
    "bathroom": {
        "label": "Bathroom",
        "weight": 0.25,
        "question": "Step-free bathroom access, door width, roll-in or step-free shower vs. tub, grab bars, shower chair, toilet height, turning space.",
    },
    "interior": {
        "label": "Moving around inside",
        "weight": 0.20,
        "question": "Single level or elevator vs. internal stairs, lofts and ladders; hallway and doorway width; thresholds, sunken rooms, clutter, rugs.",
    },
    "bedroom": {
        "label": "Bedroom",
        "weight": 0.15,
        "question": "Step-free access to a bedroom, door width, bed height and clear space beside the bed; bunks, lofts, sofa beds and floor mattresses count against it.",
    },
    "parking": {
        "label": "Parking & approach",
        "weight": 0.05,
        "question": "Accessible or on-site parking close to the entrance; steep hills, gravel, long or uneven paths.",
    },
    "host_features": {
        "label": "Host-declared accessibility",
        "weight": 0.05,
        "question": "What the host explicitly lists in Airbnb's accessibility features (and photos of them) or states in the description.",
    },
}

VERDICTS = [
    (2, "Highly recommended"),
    (4, "Recommended"),
    (6, "Use caution - confirm details with host"),
    (7, "Unverified - confirm accessibility with host before booking"),
    (9, "Not recommended"),
    (10, "Not accessible - do not recommend"),
]


def overall(category_scores: dict, blocking_barrier: bool, hard_barriers: list) -> int:
    total = sum(CATEGORIES[k]["weight"] * category_scores[k] for k in CATEGORIES)
    score = int(round(total))
    if hard_barriers:
        # A single barrier (e.g. the only shower is a tub) outweighs a good average.
        score = max(score, 7)
    if blocking_barrier:
        # Cannot get in, or cannot reach any bedroom/bathroom without stairs.
        score = 10
    return min(10, max(1, score))


def verdict(score: int) -> str:
    for upper, text in VERDICTS:
        if score <= upper:
            return text
    return VERDICTS[-1][1]
