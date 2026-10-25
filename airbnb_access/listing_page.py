"""Fetch one public listing page (airbnb.com/rooms/<id>) for photos and amenities.

The Inside Airbnb CSV carries only the cover photo and omits Airbnb's
"Accessibility features" amenities, so this is what lets the review see the
host's full photo set and accessibility declarations.

Politeness: requests are serialized through a shared rate limiter (default
one every 3 s), use an honest User-Agent, and only touch /rooms/<id>, which
Airbnb's robots.txt allows. There is no CAPTCHA or bot-detection evasion; if
Airbnb blocks or rate-limits, the listing falls back to CSV data only.
Airbnb's Terms of Service restrict automated access, so review them before
running this at volume.
"""

import json
import re
import threading
import time
import urllib.error
import urllib.request

from .sources import USER_AGENT, Listing

_STATE_SCRIPT = re.compile(
    r'<script[^>]*id="data-deferred-state-\d+"[^>]*>(.*?)</script>', re.S
)
_PHOTO = re.compile(r"https://a0\.muscache\.com/(?:im/)?pictures/[^\"?\\\s]+\.(?:jpe?g|png|webp)", re.I)
_PHOTO_SECTIONS = ("PHOTO_TOUR", "HERO")
_NOT_LISTING_PHOTO = ("AirbnbPlatformAssets", "/pictures/user/", "/pictures/airbnb-platform-assets/")


class RateLimiter:
    def __init__(self, min_interval: float):
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._next = 0.0

    def wait(self):
        with self._lock:
            now = time.monotonic()
            if now < self._next:
                time.sleep(self._next - now)
            self._next = time.monotonic() + self.min_interval


class Blocked(Exception):
    """Airbnb refused or throttled the request; stop fetching pages."""


def fetch(listing: Listing, limiter: RateLimiter, max_photos: int = 40) -> Listing:
    limiter.wait()
    req = urllib.request.Request(
        f"https://www.airbnb.com/rooms/{listing.id}",
        headers={"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            html = resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        if e.code in (403, 429):
            raise Blocked(f"HTTP {e.code} from airbnb.com") from e
        return listing  # 404 = delisted since the dataset snapshot
    parse(html, listing, max_photos)
    return listing


def parse(html: str, listing: Listing, max_photos: int = 40) -> None:
    states = []
    for m in _STATE_SCRIPT.finditer(html):
        try:
            states.append(json.loads(m.group(1)))
        except json.JSONDecodeError:
            pass
    if not states:
        return

    groups = {}
    tour = []
    for state in states:
        for node in _find_key(state, "seeAllAmenitiesGroups"):
            for g in node or []:
                title = g.get("title") or "Other"
                items = groups.setdefault(title, [])
                for a in g.get("amenities") or []:
                    if a.get("title"):
                        items.append({"title": a["title"], "available": bool(a.get("available"))})
        for node in _find_key(state, "accessibilityFeatures"):
            for stop in (node or {}).get("stops") or []:
                text = json.dumps(stop)
                tour.append({
                    "title": _first_str(stop, ("title", "name")) or "",
                    "labels": sorted(set(_all_str(stop, ("title", "subtitle", "caption", "accessibilityLabel", "text")))),
                    "photos": _photos(text),
                })

    # The listing's own photos live in the photo-tour section; other sections
    # carry Airbnb's generic artwork (e.g. the service-animal explainer).
    photos = []
    for state in states:
        for section in _find_sections(state):
            if any(s in section["sectionId"] for s in _PHOTO_SECTIONS):
                for url in _photos(json.dumps(section)):
                    if url not in photos:
                        photos.append(url)
    if not photos:
        for state in states:
            for url in _photos(json.dumps(state)):
                if "/pictures/hosting/" in url and url not in photos:
                    photos.append(url)

    listing.amenity_groups = groups
    listing.accessibility_tour = tour
    # Accessibility tour photos first; they are the most informative.
    tour_photos = [p for stop in tour for p in stop["photos"]]
    listing.photo_urls = (tour_photos + [p for p in photos if p not in tour_photos])[:max_photos]
    listing.page_fetched = True


def _photos(text: str):
    seen = []
    for url in _PHOTO.findall(text):
        if any(bad in url for bad in _NOT_LISTING_PHOTO):
            continue
        if url not in seen:
            seen.append(url)
    return seen


def _find_sections(obj):
    if isinstance(obj, dict):
        if isinstance(obj.get("sectionId"), str):
            yield obj
        for v in obj.values():
            yield from _find_sections(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find_sections(v)


def _find_key(obj, key):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                yield v
            else:
                yield from _find_key(v, key)
    elif isinstance(obj, list):
        for v in obj:
            yield from _find_key(v, key)


def _first_str(obj, keys):
    for k in keys:
        v = obj.get(k) if isinstance(obj, dict) else None
        if isinstance(v, str) and v:
            return v
    return None


def _all_str(obj, keys):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and isinstance(v, str) and v.strip():
                yield v.strip()
            elif isinstance(v, dict) and k in keys and isinstance(v.get("text"), str) and v["text"].strip():
                yield v["text"].strip()
            else:
                yield from _all_str(v, keys)
    elif isinstance(obj, list):
        for v in obj:
            yield from _all_str(v, keys)
