"""Listing sources: Inside Airbnb's public US datasets (one CSV per market).

Inside Airbnb (https://insideairbnb.com) republishes Airbnb's public listing
data for ~34 US markets every quarter. It is the bulk source here; the
listing page itself (see listing_page.py) is fetched only for the extra
photos and the host's accessibility amenities.
"""

import base64
import csv
import gzip
import io
import json
import re
import urllib.request
from datetime import date
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, List, Optional

GET_THE_DATA = "https://insideairbnb.com/get-the-data/"
USER_AGENT = "airbnb-accessibility-rater/0.1 (accessibility research)"
_US_URL = re.compile(
    r"https://data\.insideairbnb\.com/united-states/([a-z]{2})/([a-z0-9-]+)/(\d{4}-\d{2}-\d{2})/data/listings\.csv\.gz"
)

csv.field_size_limit(10**8)


@dataclass
class Region:
    state: str
    name: str
    date: str
    url: str

    @property
    def key(self) -> str:
        return f"{self.state}/{self.name}"


@dataclass
class Listing:
    id: str
    url: str
    region: str
    name: str
    description: str
    property_type: str
    room_type: str
    accommodates: str
    bathrooms_text: str
    bedrooms: str
    amenities: List[str]
    picture_url: str
    latitude: str = ""
    longitude: str = ""
    price: str = ""
    neighbourhood: str = ""
    beds: str = ""
    bathrooms: Optional[float] = None
    min_nights: Optional[int] = None
    max_nights: Optional[int] = None
    rating: Optional[float] = None
    reviews: int = 0
    superhost: bool = False
    # {"start": "YYYY-MM-DD", "bits": base64 of one bit per night, 1 = open}
    availability: Optional[dict] = None
    # Filled in by listing_page.fetch() when the page is fetched.
    photo_urls: List[str] = field(default_factory=list)
    amenity_groups: dict = field(default_factory=dict)
    accessibility_tour: List[dict] = field(default_factory=list)
    page_fetched: bool = False


# Inside Airbnb's folder names don't always title-case into the name people search for.
MARKET_NAMES = {
    "dc/washington-dc": "Washington",
    "nv/clark-county-nv": "Las Vegas (Clark County)",
    "or/salem-or": "Salem",
    "mn/twin-cities-msa": "Minneapolis-St. Paul (Twin Cities)",
    "fl/broward-county": "Fort Lauderdale (Broward County)",
    "ca/santa-clara-county": "San Jose (Santa Clara County)",
    "ny/new-york-city": "New York City",
}


def market_label(region_key: str) -> str:
    state, _, name = region_key.partition("/")
    return f"{MARKET_NAMES.get(region_key) or name.replace('-', ' ').title()}, {state.upper()}"


def _get(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def discover_us_regions() -> List[Region]:
    """Return the latest dataset for every US market listed on Inside Airbnb."""
    html = _get(GET_THE_DATA).decode("utf-8", "replace")
    latest = {}
    for m in _US_URL.finditer(html):
        state, name, date = m.groups()
        region = Region(state, name, date, m.group(0))
        if region.key not in latest or date > latest[region.key].date:
            latest[region.key] = region
    return sorted(latest.values(), key=lambda r: r.key)


def download(region: Region, cache_dir: Path, filename: str = "listings.csv.gz") -> Path:
    path = cache_dir / region.state / region.name / region.date / filename
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".part")
        tmp.write_bytes(_get(region.url.replace("listings.csv.gz", filename)))
        tmp.rename(path)
    return path


def read_calendar(path: Path) -> dict:
    """Map listing id -> availability for the 368 nights after the snapshot date.

    Streams the file and keeps 46 bytes per listing, so even NYC's ~13M
    calendar rows fit in a few MB.
    """
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        return calendar_from_rows(csv.DictReader(f))


def calendar_from_rows(rows) -> dict:
    bits = {}
    start = None
    if True:
        for row in rows:
            d = date.fromisoformat(row["date"])
            if start is None:
                start = d  # rows start at the scrape date
            b = bits.get(row["listing_id"])
            if b is None:
                b = bits[row["listing_id"]] = bytearray(46)
            i = (d - start).days
            if row["available"] == "t" and 0 <= i < 368:
                b[i // 8] |= 1 << (i % 8)
    if start is None:
        return {}
    s = start.isoformat()
    return {k: {"start": s, "bits": base64.b64encode(bytes(b)).decode("ascii")} for k, b in bits.items()}


def stream_rows(region: Region, filename: str = "listings.csv.gz"):
    """Read a dataset straight from Inside Airbnb without saving it to disk."""
    req = urllib.request.Request(region.url.replace("listings.csv.gz", filename), headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=300) as resp:
        text = io.TextIOWrapper(gzip.GzipFile(fileobj=resp), encoding="utf-8", newline="")
        yield from csv.DictReader(text)


def read_listings(path: Path, region_key: str) -> Iterator[Listing]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as f:
        yield from listings_from_rows(csv.DictReader(f), region_key)


def listings_from_rows(rows, region_key: str) -> Iterator[Listing]:
    if True:
        for row in rows:
            try:
                amenities = json.loads(row.get("amenities") or "[]")
            except json.JSONDecodeError:
                amenities = []
            yield Listing(
                id=row["id"],
                url=row.get("listing_url") or f"https://www.airbnb.com/rooms/{row['id']}",
                region=region_key,
                name=row.get("name", ""),
                description=_strip_html(row.get("description", "")),
                property_type=row.get("property_type", ""),
                room_type=row.get("room_type", ""),
                accommodates=row.get("accommodates", ""),
                bathrooms_text=row.get("bathrooms_text", ""),
                bedrooms=row.get("bedrooms", ""),
                amenities=amenities,
                picture_url=row.get("picture_url", ""),
                latitude=row.get("latitude", ""),
                longitude=row.get("longitude", ""),
                price=row.get("price", ""),
                neighbourhood=row.get("neighbourhood_cleansed") or row.get("neighbourhood") or "",
                beds=row.get("beds", ""),
                bathrooms=_bathrooms(row.get("bathrooms") or row.get("bathrooms_text") or ""),
                min_nights=_int(row.get("minimum_nights")),
                max_nights=_int(row.get("maximum_nights")),
                rating=_float(row.get("review_scores_rating")),
                reviews=_int(row.get("number_of_reviews")) or 0,
                superhost=row.get("host_is_superhost") == "t",
            )


def select_regions(all_regions: List[Region], wanted: Optional[List[str]]) -> List[Region]:
    """Filter by 'all', a state code ('ny'), or a market ('ny/new-york-city' or 'new-york-city')."""
    if not wanted or wanted == ["all"]:
        return all_regions
    out = []
    for r in all_regions:
        for w in wanted:
            w = w.lower().strip()
            if w in (r.state, r.name, r.key):
                out.append(r)
                break
    return out


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _bathrooms(text: str) -> Optional[float]:
    if "half" in text.lower():
        return 0.5
    m = re.search(r"\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def _strip_html(text: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()
