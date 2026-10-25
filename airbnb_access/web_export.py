"""Build the search site (index.html + data/) without keeping anything on disk.

Each market is streamed from Inside Airbnb, rated, and written as one gzip
JSON file, base64-encoded as text (`data/<state>-<market>.gz.txt`) so any
static host serves it. `best.gz.txt` holds the most accessible listings
across all markets, and `index.json` lists the markets.

Photos are not copied: rows carry Airbnb's own photo addresses (the cover for
every listing, a gallery for reviewed ones) and the page loads them from
Airbnb's servers.

Claude reviews are expensive, so they are kept in a reviews file
(`reviews/reviews.json` in the repo) and reused on every build. With
ANTHROPIC_API_KEY set and --claude-limit N, up to N more listings are
reviewed and added to that file.
"""

import base64
import gzip
import heapq
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import features, heuristics, listing_page, report, scoring, sources
from .cli import _listing_summary

PAGE_TEMPLATE = Path(__file__).resolve().parent.parent / "web" / "accessible-stays.html"
PHOTO_PREFIX = "https://a0.muscache.com/im/pictures/"
GALLERY_MAX = 24

CONF_RANK = {"high": 0, "medium": 1, "low": 2}
HEURISTIC_SUMMARY = "Keyword and amenity check only; photos were not reviewed."


def _photo_key(url):
    """Airbnb photo address without the shared prefix or size query (the page adds them back)."""
    if not url:
        return None
    url = url.split("?")[0].replace("https://a0.muscache.com/pictures/", PHOTO_PREFIX)
    return url[len(PHOTO_PREFIX):] if url.startswith(PHOTO_PREFIX) else url


def _row_for(listing, rating, gallery=None):
    row = report._row(_listing_summary(listing), rating)
    row.pop("photo", None)
    row["img"] = _photo_key(listing.picture_url)
    if gallery:
        row["gallery"] = [k for k in (_photo_key(u) for u in gallery) if k]
    if row.get("summary") == HEURISTIC_SUMMARY:
        row.pop("summary")
    # The page fills these defaults back in; dropping them halves the files.
    return {k: v for k, v in row.items() if v not in ("", None, [], False)}


def _sort_key(row):
    return (row["overall"], CONF_RANK.get(row.get("confidence"), 3), -(row.get("stars") or 0))


def _promise(listing, prelim):
    """Sort key for spending the review budget: lowest heuristic score first, then
    listings with more declared accessibility features, open nights, and reviews."""
    declared = sum(1 for a in heuristics.available_amenities(listing)
                   if any(k in a.lower() for k in heuristics.ACCESSIBILITY_AMENITY_KEYS))
    open_nights = 0
    if listing.availability:
        open_nights = sum(bin(b).count("1") for b in base64.b64decode(listing.availability["bits"]))
    return (prelim["overall"], -declared, -min(open_nights, 30), -(listing.reviews or 0))


def rescore(rating):
    """Recompute a saved review's overall score with the current rule; the category
    scores are Claude's and never change."""
    r = dict(rating)
    r["overall"] = scoring.overall({k: v["score"] for k, v in r["categories"].items()},
                                   r.get("blocking_barrier", False), r.get("hard_barriers", []))
    r["verdict"] = scoring.verdict(r["overall"])
    return r


def load_reviews(path):
    if path and Path(path).exists():
        return json.loads(Path(path).read_text(encoding="utf-8"))
    return {}


def save_reviews(path, reviews):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(reviews, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def export(out: Path, wanted, claude_limit=0, claude_max_prelim=6, model="claude-opus-5-5",
           pages=False, best_rows=4000, reviews_path=None):
    data = out / "data"
    data.mkdir(parents=True, exist_ok=True)
    reviews = load_reviews(reviews_path)
    client = None
    if claude_limit:
        if not reviews_path:
            raise SystemExit("--claude-limit needs --reviews, so paid reviews are saved and reused.")
        import anthropic
        client = anthropic.Anthropic(max_retries=4)
    markets = []
    candidates = []  # heap of (negated promise key, id, listing, prelim, file): the best claude_limit

    for region in sources.select_regions(sources.discover_us_regions(), wanted):
        print(f"{region.key}: streaming calendar...", file=sys.stderr, flush=True)
        calendar = sources.calendar_from_rows(sources.stream_rows(region, "calendar.csv.gz"))
        print(f"{region.key}: streaming listings...", file=sys.stderr, flush=True)
        file = f"{region.state}-{region.name}.gz.txt"
        rows = []
        for l in sources.listings_from_rows(sources.stream_rows(region), region.key):
            l.availability = calendar.get(l.id)
            saved = reviews.get(l.id)
            if saved:
                rows.append(_row_for(l, rescore(saved["rating"]), saved.get("gallery")))
                continue
            prelim = heuristics.rate(l)
            rows.append(_row_for(l, prelim))
            if client and prelim["overall"] <= claude_max_prelim and l.availability:
                item = (tuple(-k for k in _promise(l, prelim)), l.id, l, prelim, file)
                if len(candidates) < claude_limit:
                    heapq.heappush(candidates, item)
                elif item[:2] > candidates[0][:2]:
                    heapq.heapreplace(candidates, item)
        del calendar
        rows.sort(key=_sort_key)
        _write_packed(data / file, rows)
        markets.append({"key": region.key, "label": sources.market_label(region.key),
                        "file": f"data/{file}", "date": region.date})
        print(f"{region.key}: {len(rows):,} listings -> {file}", file=sys.stderr, flush=True)

    if client and candidates:
        _review_all(client, sorted(candidates, reverse=True), data, model, pages, reviews, reviews_path)

    markets = _summarize(data, markets, best_rows)
    write_page(out, markets)
    total = sum(m["count"] for m in markets)
    reviewed = sum(m["reviewed"] for m in markets)
    print(f"Done: {len(markets)} markets, {total:,} listings, {reviewed} reviewed by Claude.", file=sys.stderr)
    return markets


def _review_all(client, picked, data: Path, model, pages, reviews, reviews_path):
    """Photo-review the picked listings, save each review, then patch the market files."""
    from . import claude_review
    import threading
    limiter = listing_page.RateLimiter(3.0)
    lock = threading.Lock()
    state = {"done": 0, "failed": 0, "in": 0, "out": 0, "pages": pages}
    print(f"Reviewing {len(picked)} listings with {model}"
          f"{' (fetching listing pages, one every 3 s)' if pages else ''}...", file=sys.stderr, flush=True)

    def review(item):
        _, _, listing, prelim, file = item
        if state["pages"]:
            try:
                listing_page.fetch(listing, limiter)
            except listing_page.Blocked as e:
                with lock:
                    if state["pages"]:
                        state["pages"] = False
                        print(f"\n! {e}; reviewing the cover photo only from here on.", file=sys.stderr, flush=True)
            except Exception:
                pass
        gallery = None
        try:
            r = claude_review.review(client, listing, model=model)
            r["heuristic_overall"] = prelim["overall"]
            # Photo numbers in Claude's notes follow the order it saw them, so the gallery starts there.
            seen = r.pop("photos_reviewed", [])
            gallery = (seen + [u for u in listing.photo_urls if u not in seen])[:GALLERY_MAX]
            usage = r.pop("usage")
            with lock:
                state["in"] += usage["input_tokens"]
                state["out"] += usage["output_tokens"]
                reviews[listing.id] = {"rating": r, "gallery": gallery}
        except claude_review.ReviewFailed as e:
            r = dict(prelim, note=f"Claude review failed: {e}")
            with lock:
                state["failed"] += 1
        with lock:
            state["done"] += 1
            if state["done"] % 10 == 0 or state["done"] == len(picked):
                save_reviews(reviews_path, reviews)  # checkpoint: paid work is never lost
                cost = state["in"] * 4 / 1e6 + state["out"] * 20 / 1e6
                print(f"  {state['done']}/{len(picked)} reviewed, {state['failed']} failed, "
                      f"~${cost:.2f} so far (Opus 5.5 list price)", file=sys.stderr, flush=True)
        return file, _row_for(listing, r, gallery)

    # Review one listing first so a setup problem stops the run before it spends anything more.
    first = review(picked[0])
    if first[1].get("method") != "claude":
        raise SystemExit(f"Stopping: the first review failed ({first[1].get('note')}). Nothing else was sent to Claude.")
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = [first] + list(pool.map(review, picked[1:]))
    save_reviews(reviews_path, reviews)

    by_file = {}
    for file, row in results:
        by_file.setdefault(file, {})[row["id"]] = row
    for file, updates in by_file.items():
        rows = [updates.get(r["id"], r) for r in _read_packed(data / file)]
        rows.sort(key=_sort_key)
        _write_packed(data / file, rows)


def _summarize(data: Path, markets, best_rows):
    """Counts per market and the US-wide best list, read back from the written files."""
    best = []
    for m in markets:
        rows = _read_packed(data / Path(m["file"]).name)
        counts = {"recommended": 0, "caution": 0, "unverified": 0, "not": 0}
        for r in rows:
            o = r["overall"]
            counts["recommended" if o <= 4 else "caution" if o <= 6 else "unverified" if o == 7 else "not"] += 1
            item = (tuple(-k for k in _sort_key(r)), r["id"], r)
            if len(best) < best_rows:
                heapq.heappush(best, item)
            elif item[:2] > best[0][:2]:
                heapq.heapreplace(best, item)
        m.update(count=len(rows), reviewed=sum(1 for r in rows if r.get("method") == "claude"), **counts)
    _write_packed(data / "best.gz.txt", sorted((r for _, _, r in best), key=_sort_key))
    (data / "index.json").write_text(json.dumps(markets, separators=(",", ":")), encoding="utf-8")
    return markets


def _read_packed(path: Path):
    return json.loads(gzip.decompress(base64.b64decode(path.read_bytes())))


def _write_packed(path: Path, rows):
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    path.write_bytes(base64.b64encode(gzip.compress(payload, compresslevel=9)))


STANDALONE_HEAD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex, nofollow, noimageindex">
<style>:root{padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>
</head><body>
"""


def write_page(out: Path, markets=None):
    """Fill the page template with the market list and filter options, as index.html."""
    if markets is None:
        markets = json.loads((out / "data" / "index.json").read_text(encoding="utf-8"))
    config = {
        "labels": {k: v["label"] for k, v in scoring.CATEGORIES.items()},
        "features": features.meta(),
        "markets": markets,
    }
    html = PAGE_TEMPLATE.read_text(encoding="utf-8")
    start, end = html.index("/*CONFIG*/"), html.index("/*END*/") + len("/*END*/")
    html = html[:start] + json.dumps(config, separators=(",", ":")).replace("</", "<\\/") + html[end:]
    page = out / "index.html"
    page.write_text(STANDALONE_HEAD + html + "\n</body></html>\n", encoding="utf-8")
    return page
