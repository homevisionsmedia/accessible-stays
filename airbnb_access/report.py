"""Self-contained HTML report with an Airbnb-style search: where, when, who, filters, map."""

import json
import re
from pathlib import Path

from . import features, scoring, sources

CONF_RANK = {"high": 0, "medium": 1, "low": 2}
TEMPLATE = Path(__file__).with_name("report_template.html")


def build(jsonl: Path, out: Path, max_rows: int = 20000):
    rows = []
    with jsonl.open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            rows.append(_row(r["listing"], r["rating"]))
    total = len(rows)
    rows.sort(key=lambda x: (x["overall"], CONF_RANK.get(x["confidence"], 3)))
    rows = rows[:max_rows]
    config = {
        "labels": {k: v["label"] for k, v in scoring.CATEGORIES.items()},
        "features": features.meta(),
        "total": total,
    }
    html = (TEMPLATE.read_text(encoding="utf-8")
            .replace("__DATA__", _js(rows))
            .replace("__CONFIG__", _js(config)))
    out.write_text(html, encoding="utf-8")


def _row(l, g):
    photo = (g.get("photos_reviewed") or l.get("photo_urls") or [l.get("picture_url")])[0]
    return {
        "id": l["id"], "url": l["url"], "region": l["region"],
        "market": sources.market_label(l["region"]),
        "hood": l.get("neighbourhood", ""), "name": l["name"], "type": l["property_type"],
        "room": l.get("room_type", ""), "lat": _num(l.get("latitude")), "lng": _num(l.get("longitude")),
        "price": _num(re.sub(r"[$,]", "", l.get("price") or "")),
        "guests": _num(l.get("accommodates")), "bedrooms": _num(l.get("bedrooms")),
        "beds": _num(l.get("beds")), "baths": l.get("bathrooms"),
        "minN": l.get("min_nights"), "maxN": l.get("max_nights"),
        "stars": l.get("rating"), "reviews": l.get("reviews", 0), "superhost": l.get("superhost", False),
        "avail": l.get("availability"), "feat": l.get("features", []),
        "photo": _thumb(photo), "overall": g["overall"], "verdict": g["verdict"],
        "method": g["method"], "confidence": g["confidence"], "summary": g.get("summary", ""),
        "categories": g["categories"], "barriers": g["hard_barriers"],
        "questions": g.get("questions_for_host", []), "photos": g.get("photo_observations", []),
        "declared": l.get("accessibility_amenities", []), "note": g.get("note", ""),
    }


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _js(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def _thumb(url):
    if not url:
        return ""
    url = url.replace("https://a0.muscache.com/pictures/", "https://a0.muscache.com/im/pictures/")
    return f"{url.split('?')[0]}?im_w=480"
