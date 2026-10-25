"""Command line: list markets, rate listings, build the HTML report."""

import argparse
import csv
import json
import sys
import threading
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import asdict
from itertools import islice
from pathlib import Path

from . import features, heuristics, listing_page, report, scoring, sources


def cmd_regions(args):
    regions = sources.select_regions(sources.discover_us_regions(), args.regions)
    for r in regions:
        print(f"{r.key:35} {r.date}")
    print(f"\n{len(regions)} US market(s) on Inside Airbnb.")


class Runner:
    def __init__(self, args):
        self.args = args
        self.out_dir = Path(args.out)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.jsonl = self.out_dir / "ratings.jsonl"
        self.done = self._load_done()
        self.lock = threading.Lock()
        self.limiter = listing_page.RateLimiter(args.page_delay)
        self.pages_enabled = args.pages
        self.counts = {"rated": 0, "claude": 0, "errors": 0, "input_tokens": 0, "output_tokens": 0}
        self.client = None
        if not args.no_claude:
            import anthropic
            from . import claude_review
            self.claude_review = claude_review
            self.client = anthropic.Anthropic(max_retries=4)

    def _load_done(self):
        done = set()
        if self.jsonl.exists():
            with self.jsonl.open(encoding="utf-8") as f:
                for line in f:
                    try:
                        done.add(json.loads(line)["listing"]["id"])
                    except (json.JSONDecodeError, KeyError):
                        pass
        return done

    def process(self, listing: sources.Listing):
        rating = heuristics.rate(listing)
        note = None
        if rating["overall"] < 10 and self.pages_enabled:
            try:
                listing_page.fetch(listing, self.limiter, max_photos=max(self.args.max_photos, 12))
                rating = heuristics.rate(listing)
            except listing_page.Blocked as e:
                with self.lock:
                    if self.pages_enabled:
                        self.pages_enabled = False
                        print(f"\n! {e}; continuing without listing pages (CSV data only).", file=sys.stderr)
            except Exception as e:  # network hiccup: keep the CSV-only rating
                note = f"page fetch failed: {e}"

        if self.client and rating["overall"] <= self.args.claude_max_prelim:
            try:
                prelim = rating
                rating = self.claude_review.review(
                    self.client, listing, model=self.args.model,
                    max_photos=self.args.max_photos, effort=self.args.effort,
                )
                rating["heuristic_overall"] = prelim["overall"]
                with self.lock:
                    self.counts["claude"] += 1
                    self.counts["input_tokens"] += rating["usage"]["input_tokens"]
                    self.counts["output_tokens"] += rating["usage"]["output_tokens"]
            except self.claude_review.ReviewFailed as e:
                note = f"Claude review failed, heuristic rating kept: {e}"
                with self.lock:
                    self.counts["errors"] += 1
        if note:
            rating["note"] = note
        self._write(listing, rating)

    def _write(self, listing, rating):
        record = {"listing": _listing_summary(listing), "rating": rating}
        with self.lock:
            with self.jsonl.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
            self.done.add(listing.id)
            self.counts["rated"] += 1
            c = self.counts
            if c["rated"] % 25 and not sys.stderr.isatty():
                return
            print(
                f"\r{c['rated']} rated | {c['claude']} by Claude | {c['errors']} errors | "
                f"{c['input_tokens']:,} in / {c['output_tokens']:,} out tokens   ",
                end="", file=sys.stderr, flush=True,
            )

    def run(self):
        regions = sources.select_regions(sources.discover_us_regions(), self.args.regions)
        if not regions:
            sys.exit("No matching US markets. Run `python -m airbnb_access regions` to list them.")
        cache = Path(self.args.cache)
        print(f"Rating listings from {len(regions)} market(s); results -> {self.jsonl}", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=self.args.workers) as pool:
            pending = set()
            for region in regions:
                print(f"\n{region.key}: downloading {region.date} snapshot...", file=sys.stderr)
                path = sources.download(region, cache)
                calendar = {}
                if not self.args.no_calendar:
                    print(f"{region.key}: reading availability calendar...", file=sys.stderr)
                    calendar = sources.read_calendar(sources.download(region, cache, "calendar.csv.gz"))
                todo = (_with_calendar(l, calendar) for l in sources.read_listings(path, region.key)
                        if l.id not in self.done)
                if self.args.limit:
                    todo = islice(todo, self.args.limit)
                for listing in todo:
                    if len(pending) >= self.args.workers * 4:
                        finished, pending = wait(pending, return_when=FIRST_COMPLETED)
                        _raise_errors(finished)
                    pending.add(pool.submit(self.process, listing))
            finished, _ = wait(pending)
            _raise_errors(finished)
        print(file=sys.stderr)
        write_csv(self.jsonl, self.out_dir / "ratings.csv")
        report.build(self.jsonl, self.out_dir / "report.html", max_rows=self.args.report_rows)
        print(f"Wrote {self.out_dir / 'ratings.csv'} and {self.out_dir / 'report.html'}", file=sys.stderr)


def _raise_errors(futures):
    for f in futures:
        f.result()  # surfaces auth/config errors instead of silently dropping them


def _with_calendar(listing, calendar):
    listing.availability = calendar.get(listing.id)
    return listing


def _listing_summary(l: sources.Listing):
    d = asdict(l)
    for k in ("amenities", "amenity_groups"):
        d.pop(k)
    d["description"] = l.description[:500]  # full text stays in the cached CSV
    d["features"] = features.tags(heuristics.available_amenities(l))
    d["accessibility_amenities"] = [
        a for a in heuristics.available_amenities(l)
        if any(k in a.lower() for k in heuristics.ACCESSIBILITY_AMENITY_KEYS)
    ]
    return d


def write_csv(jsonl: Path, out: Path):
    cats = list(scoring.CATEGORIES)
    with jsonl.open(encoding="utf-8") as f, out.open("w", newline="", encoding="utf-8") as o:
        w = csv.writer(o)
        w.writerow(["id", "url", "region", "name", "property_type", "overall", "verdict", "method", "confidence"]
                   + [f"{c}_score" for c in cats] + ["hard_barriers", "summary"])
        for line in f:
            r = json.loads(line)
            l, g = r["listing"], r["rating"]
            w.writerow([l["id"], l["url"], l["region"], l["name"], l["property_type"], g["overall"], g["verdict"],
                        g["method"], g["confidence"]] + [g["categories"][c]["score"] for c in cats]
                       + ["; ".join(g["hard_barriers"]), g.get("summary", "")])


def cmd_report(args):
    jsonl = Path(args.jsonl)
    write_csv(jsonl, jsonl.with_suffix(".csv"))
    report.build(jsonl, Path(args.output), max_rows=args.rows)
    print(f"Wrote {args.output} and {jsonl.with_suffix('.csv')}")


def cmd_check_key(args):
    import os
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ANTHROPIC_API_KEY is not set in this shell.")
    try:
        model = anthropic.Anthropic().models.retrieve(args.model)
    except anthropic.AuthenticationError:
        sys.exit("The API key was rejected. Create a new one at platform.claude.com/settings/keys.")
    except anthropic.PermissionDeniedError:
        sys.exit("The key works but can't use this model. Check the key's workspace and billing.")
    except anthropic.APIConnectionError as e:
        sys.exit(f"Couldn't reach the Anthropic API: {e}")
    print(f"Key works. {model.display_name} is available.")


def main(argv=None):
    p = argparse.ArgumentParser(prog="airbnb_access", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("regions", help="list the US markets available")
    r.add_argument("regions", nargs="*", default=["all"])
    r.set_defaults(func=cmd_regions)

    run = sub.add_parser("run", help="rate listings")
    run.add_argument("--regions", nargs="+", default=["all"],
                     help="'all', state codes (ny ca), or markets (austin ny/new-york-city)")
    run.add_argument("--limit", type=int, default=0, help="max new listings per market (0 = all)")
    run.add_argument("--out", default="results")
    run.add_argument("--cache", default="data")
    run.add_argument("--pages", action="store_true",
                     help="also fetch airbnb.com listing pages (against Airbnb's terms; off by default)")
    run.add_argument("--page-delay", type=float, default=3.0, help="seconds between listing-page requests")
    run.add_argument("--no-calendar", action="store_true",
                     help="skip the availability calendar (date search in the report will not work)")
    run.add_argument("--no-claude", action="store_true", help="keyword/amenity heuristic only, no photo review")
    run.add_argument("--model", default="claude-opus-5-5")
    run.add_argument("--effort", default="medium", choices=["low", "medium", "high", "xhigh", "max"])
    run.add_argument("--max-photos", type=int, default=12, help="photos sent to Claude per listing")
    run.add_argument("--claude-max-prelim", type=int, default=9,
                     help="only send listings whose heuristic score is at or below this to Claude")
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--report-rows", type=int, default=20000)
    run.set_defaults(func=lambda a: Runner(a).run())

    rep = sub.add_parser("report", help="rebuild report.html and ratings.csv from ratings.jsonl")
    rep.add_argument("jsonl", nargs="?", default="results/ratings.jsonl")
    rep.add_argument("-o", "--output", default="results/report.html")
    rep.add_argument("--rows", type=int, default=20000)
    rep.set_defaults(func=cmd_report)

    web = sub.add_parser("web-export", help="build the hosted site's data files (streams, keeps no cache)")
    web.add_argument("--regions", nargs="+", default=["all"])
    web.add_argument("--out", required=True, help="folder for the data files (delete after publishing)")
    web.add_argument("--claude-limit", type=int, default=0,
                     help="photo-review up to this many listings with Claude (needs ANTHROPIC_API_KEY)")
    web.add_argument("--claude-max-prelim", type=int, default=6)
    web.add_argument("--model", default="claude-opus-5-5")
    web.add_argument("--pages", action="store_true", help="also fetch airbnb.com pages for listings sent to Claude (against Airbnb's terms; off by default)")
    web.add_argument("--reviews", help="JSON file of saved Claude reviews to reuse and add to")
    web.set_defaults(func=lambda a: __import__("airbnb_access.web_export", fromlist=["export"]).export(
        Path(a.out), a.regions, a.claude_limit, a.claude_max_prelim, a.model, a.pages, reviews_path=a.reviews))

    ck = sub.add_parser("check-key", help="confirm ANTHROPIC_API_KEY works (free request, no tokens used)")
    ck.add_argument("--model", default="claude-opus-5-5")
    ck.set_defaults(func=cmd_check_key)

    args = p.parse_args(argv)
    args.func(args)
