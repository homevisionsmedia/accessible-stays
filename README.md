# Airbnb accessibility rater

Rates US Airbnb listings for how usable they are by a wheelchair user or a guest with limited mobility, on a 1-10 scale:

| Score | Verdict |
|---|---|
| 1-2 | Highly recommended |
| 3-4 | Recommended |
| 5-6 | Use caution: confirm details with the host |
| 7 | Unverified: confirm accessibility with the host before booking |
| 8-9 | Not recommended |
| 10 | Not accessible, do not recommend |

Each listing gets a score from 1 to 10 in each of six categories. The overall score is a weighted average of those six:

| Category | Weight | What it covers |
|---|---|---|
| Arrival & entrance | 30% | Steps, ramps, elevator, path, entrance door width (32 in / 81 cm or more) |
| Bathroom | 25% | Step-free access, roll-in shower vs. tub, grab bars, shower chair, door width |
| Moving around inside | 20% | Single level vs. internal stairs, lofts, ladders, hallway and door widths |
| Bedroom | 15% | Step-free access, door width, bed type and height, space beside the bed |
| Parking & approach | 5% | Accessible or on-site parking, hills, gravel |
| Host-declared accessibility | 5% | Airbnb's "Accessibility features" amenities, the accessibility photo tour, and explicit statements |

Two overrides apply on top of the average:
- Any specific barrier, such as a bathtub as the only shower, puts the overall score at 7 or worse.
- A blocking barrier puts it at 10. Blocking means a wheelchair user couldn't get inside, or couldn't reach any bedroom or bathroom. A host saying the place is not wheelchair accessible also counts.

A category with no information scores 7, because saying nothing about accessibility is not evidence of it.

## How it works

1. **Listings.** It downloads the latest US datasets from [Inside Airbnb](https://insideairbnb.com/get-the-data/), which publishes free listing data for 34 US markets: NYC, LA, SF, Chicago, Austin, DC, Hawaii, Nashville and others. See `python -m airbnb_access regions`.
2. **Photos and host amenities.** For each listing it fetches the public page at `airbnb.com/rooms/<id>` to get the full photo set, the complete amenity list and the accessibility photo tour. These requests:
   - go one at a time, 3 seconds apart, under an honest User-Agent;
   - only use a path that Airbnb's robots.txt allows;
   - don't try to get around blocking. If Airbnb blocks or throttles, the run carries on with CSV data only.
3. **Quick keyword check.** It scans the description and amenities for terms like "walk-up", "spiral staircase", "roll-in shower", "step-free guest entrance" and "single level home". Listings this check scores 10, such as ones where the host says "not wheelchair accessible", skip the next step.
4. **Claude review.** Claude (`claude-opus-5-5` by default) looks at up to 12 photos plus the description and amenities. It fills in the six categories with findings, cites what it saw in specific photos, lists hard barriers and writes questions to ask the host.
5. **Output.** Results go to `results/ratings.jsonl` (full detail), `results/ratings.csv` (one row per listing) and `results/report.html`, a search page laid out like Airbnb's (below).

## Searching the results

Open `results/report.html` in a browser. It works offline; only the map and photos need an internet connection.

- **Where.** Type a city, neighborhood or ZIP code and pick a suggestion. With the map open, you can also tick "Search as I move the map".
- **When.**
  - *Dates*: pick check-in and check-out. A listing shows only if every night is open and the stay fits the host's minimum and maximum nights.
  - *Flexible*: pick a stay length (weekend, week, month, 3 or 5 nights, 2 weeks) and any months. Each listing then shows the first open stretch that fits. A weekend means Friday to Sunday.
- **Who.** Adults, children, infants and pets. Infants don't count toward the guest limit, and adding pets keeps only places that allow them.
- **Filters.**
  - Accessibility rating, photo-reviewed only, and hiding listings with a known barrier
  - Type of place and property type
  - Nightly price range
  - Bedrooms, beds and bathrooms
  - Airbnb's accessibility features (step-free entrance, step-free shower, grab bars and so on)
  - Amenities, booking options (self check-in, allows pets) and standout stays (Superhost, top rated)
- **Quick chips and sort.** The chips under the search bar toggle the most common accessibility features. Sort by most accessible, price or rating.
- **Results.** Cards show the accessibility score, the nightly price and an estimated total for the stay. Click a card for the full breakdown. Its "View on Airbnb" link opens the listing with your dates and guests filled in.
- **Shareable searches.** The address bar keeps the current search, so you can bookmark it or send the link.

Availability comes from Inside Airbnb's calendar snapshot, which covers 12 months from the scrape date. It goes stale as bookings come in, so always confirm on Airbnb. Prices are the nightly rate before fees, so totals are estimates. Instant Book isn't offered as a filter because the current data leaves it blank.

## Setup

```bash
python3 -m venv .venv
```

```bash
.venv/bin/pip install -r requirements.txt
```

### API key (only for Claude's photo review)

The keyword check and the hosted search page need no key. Claude's photo review does:

1. Create a key in the Claude Console (console.anthropic.com → API keys) and add billing credit.
2. Add it to your shell profile yourself, so it never appears in chat or in a file you might share:

```bash
echo 'export ANTHROPIC_API_KEY=your-key-here' >> ~/.zshrc
```

3. Open a new terminal, or tell Claude it's set. The SDK reads it from the environment automatically.

Never put the key in the web page, its data files or the GitHub repo. Anyone who can see it could spend your credit. `tools/save_api_key.sh` saves it without showing it on screen.

## The website (GitHub Pages)

The search site is published on GitHub Pages and rebuilds itself every Monday on GitHub's servers (`.github/workflows/build.yml`). Each build:
- streams all US markets straight from Inside Airbnb, with nothing stored;
- rates every listing;
- reuses the saved Claude reviews in `reviews/reviews.json`;
- publishes `index.html` plus about 40 MB of compressed data.

You can also start a build any time from the repo's **Actions** tab.

**Photos.** Photos load straight from Airbnb's servers and are never copied. Every listing shows its cover photo. Listings Claude reviewed show a gallery whose numbers match the photo notes in their breakdown.

**Adding more Claude reviews.** Reviews run on this Mac, because the API key stays here. Each costs roughly $0.05 on Opus 5.5. This reviews up to 500 more of the most promising listings, saving each review into `reviews/reviews.json` as it goes:

```bash
zsh tools/run_review.sh /tmp/site 500
```

Then commit and push `reviews/reviews.json`, and the site rebuilds with them. Your API key is never committed or sent to GitHub.

To build the site locally without reviews:

```bash
.venv/bin/python -m airbnb_access web-export --out /tmp/site --reviews reviews/reviews.json
```

## Usage

Try one market with a small sample first:

```bash
.venv/bin/python -m airbnb_access run --regions asheville --limit 25
```

Run a whole state, or everything:

```bash
.venv/bin/python -m airbnb_access run --regions ca
```

```bash
.venv/bin/python -m airbnb_access run --regions all
```

Runs resume where they left off: listings already in `results/ratings.jsonl` are skipped.

Useful flags:

| Flag | Effect |
|---|---|
| `--no-claude` | Keyword check only, no API cost. Lower accuracy, and confidence is always "low" |
| `--no-pages` | Don't fetch airbnb.com pages. Uses the cover photo only and misses the accessibility amenities |
| `--no-calendar` | Skip the availability calendar download. Date search in the report is turned off |
| `--report-rows 20000` | Most listings to include in report.html (best rated first). For large runs, give each market its own `--out` folder |
| `--model claude-haiku-5-5` | Far cheaper photo review (see cost below) |
| `--claude-max-prelim 8` | Only send listings with a keyword score of 8 or better to Claude |
| `--max-photos 12` | Photos per listing sent to Claude |
| `--page-delay 3` | Seconds between airbnb.com requests |
| `--workers 4` | Parallel Claude requests |

Rebuild the report from existing results:

```bash
.venv/bin/python -m airbnb_access report results/ratings.jsonl -o results/report.html
```

## Scale, time and cost

These are rough estimates; measure on a `--limit 50` run first.

- **Coverage.** Inside Airbnb covers 34 US markets, not every US listing. Rural areas and most smaller cities are missing. Airbnb doesn't publish a full national dataset.
- **Time.** At one page every 3 seconds, fetching pages for a few hundred thousand listings takes more than a week. A single market of a few thousand listings takes a few hours.
- **Claude cost.** A listing with 12 photos is about 8k input tokens plus 1-2k output.
  - Opus 5.5: about $0.05-0.07 per listing, or roughly $5,000-20,000 for every covered US listing.
  - Haiku 5.5: about $0.002 per listing.
  - Start with `--no-claude` to find candidates, then send the promising ones to Claude.

## Limits

- **Airbnb's Terms of Service.** They restrict automated access to the site. The page fetching here is polite and low-volume, but check the terms before running it at scale. `--no-pages` keeps everything to Inside Airbnb's published data.
- **Photos are marketing.** Hosts rarely photograph the entrance or the bathroom from a wheelchair user's point of view. Most listings end up "Unverified" (7) because nothing in them addresses accessibility. Treat the rating as a shortlist, and confirm with the host using the questions in each breakdown.
- **Page structure.** The page parser reads Airbnb's embedded page data. It needs updating if Airbnb changes that structure. A failed parse quietly falls back to CSV data, and `page_fetched` in the output shows which listings had full data.
