# -*- coding: utf-8 -*-
"""
euraxess_ethical_collector.py

A small, ethical collector for the European Commission's EURAXESS academic
jobs portal. Reads a country slice, writes a CSV.

Standalone version distilled from a production collector I've run since 2023
inside my advisory practice. Public here so others building international
recruitment tooling can start from a version that already respects the source.

USAGE
-----
    python euraxess_ethical_collector.py --country canada --pages 3 --out canada.csv
    python euraxess_ethical_collector.py --country netherlands --pages 5 --out netherlands.csv
    python euraxess_ethical_collector.py --country canada --country netherlands --pages 3 --out cross_continent.csv

WHY THIS SOURCE
---------------
EURAXESS is the European Commission's own researcher-mobility portal, not a
commercial aggregator, and it behaves like one:

  * Plain HTTP requests work. No Cloudflare, no 403, no Selenium.
  * robots.txt permits crawling under an explicit Allow rule.
  * Every advert names the hiring institution and gives a direct apply route,
    a URL or an email at the institution's own domain, not a redirect.
  * The advert body is labelled: Application Deadline, Country, Research
    Field, Education Level, Company/Institute. Nothing is inferred from a
    headline.
  * Data is public, funded by EU taxpayers, meant to be reused.

WHAT MAKES A COLLECTOR "ETHICAL"
--------------------------------
Six things this script does, in order of how much they matter:

  1. Honest User-Agent. The source sees exactly who is fetching and can
     rate-limit or block if needed. No spoofing a browser.

  2. Slow. A random 3-6 second pause between requests. A production run
     hit HTTP 429 at roughly 240 requests when the pause was 1-2.5 seconds.
     Slower is cheaper: a blocked run has to be repeated.

  3. Cached. Once an advert page is fetched, it stays on disk. Re-running
     the script never re-fetches the same URL. The source is not asked twice.

  4. Filtered at collection, not later. If you only serve Iranian PhD
     applicants, a Japanese national-portal row served through EURAXESS
     wastes a listing request, an advert request, and space in whatever
     comes next. This script's --country flag stops the request before it
     happens.

  5. No hidden fields. Everything the script pulls is a labelled field from
     the advert page. No guessing from headlines, no scraping from
     tooltips, no dark patterns.

  6. Public code. If the source ever objects, they can read what runs
     against them and ask for changes. A collector that hides is a
     collector that will get blocked.

WHAT IT WILL NOT DO
-------------------
Full-text search, deduplication across sources, or eligibility parsing.
Those all live downstream, and each is its own decision. This script does
one thing: turns a EURAXESS slice into a CSV without hurting the source.
"""

from __future__ import annotations

import argparse
import csv
import random
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------- constants

BASE = "https://euraxess.ec.europa.eu"
SEARCH = BASE + "/jobs/search"

# Honest User-Agent. The source can identify what is fetching and rate-limit
# or block if it chooses. Spoofing a browser makes debugging harder for the
# source and gets the collector blocked when they notice.
UA = (
    "euraxess-ethical-collector/1.0 "
    "(+https://github.com/DataBizex/ethical-academic-collector; "
    "academic research use)"
)

# Random pause between advert fetches. The first production run of this
# collector hit HTTP 429 at about 240 requests with a 1-2.5 second pause.
# Slower is cheaper: a blocked run means starting over, and the source
# reasonably decides they've seen enough of you.
PAUSE = (3.0, 6.0)

# EURAXESS country codes, taken from the search page's own <select>.
# The exact list is longer; these are the ones this audience uses most.
# Adding a country means opening the search page in a browser and reading
# the option value, not guessing.
COUNTRY_CODES = {
    # European Economic Area
    "austria":     "791", "belgium":     "792", "bulgaria":    "746",
    "croatia":     "776", "cyprus":      "777", "czech":       "755",
    "denmark":     "757", "estonia":     "758", "finland":     "760",
    "france":      "793", "germany":     "794", "greece":      "779",
    "hungary":     "748", "iceland":     "762", "ireland":     "763",
    "italy":       "781", "latvia":      "766", "lithuania":   "767",
    "luxembourg":  "796", "malta":       "782", "netherlands": "798",
    "norway":      "768", "poland":      "749", "portugal":    "784",
    "romania":     "751", "slovakia":    "753", "slovenia":    "787",
    "spain":       "788", "sweden":      "770", "switzerland": "799",
    "uk":          "771",

    # Non-EU on the same portal — useful for cross-continent studies,
    # e.g. tracking flows if Canada joins Erasmus+ as proposed 09/2026.
    "canada":      "682",
}

# Country names as EURAXESS writes them -> what we normalize to.
COUNTRY_FIX = {
    "czechia":        "Czech Republic",
    "netherlands":    "The Netherlands",
    "united kingdom": "United Kingdom",
}

MONTHS = {m[:3].lower(): i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], start=1)}

CACHE = Path(".cache") / "euraxess"


# ---------------------------------------------------------------- console

def say(text: str = "") -> None:
    """print() that cannot crash on a Windows console."""
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


# ---------------------------------------------------------------- fetching

def get(session: requests.Session, url: str) -> str | None:
    """Fetch a URL with cache. Never asks the source twice for the same page."""
    CACHE.mkdir(parents=True, exist_ok=True)
    key = re.sub(r"[^a-zA-Z0-9]+", "_", url)[:110]
    cached = CACHE / (key + ".html")

    if cached.exists():
        return cached.read_text(encoding="utf-8", errors="ignore")

    try:
        r = session.get(url, timeout=30)
    except Exception as e:
        say(f"    request failed: {type(e).__name__}")
        return None

    if r.status_code != 200:
        say(f"    HTTP {r.status_code}")
        return None

    cached.write_text(r.text, encoding="utf-8")
    # Pause is between fetches, not around the write. A cache hit costs
    # nothing to the source, so no pause.
    time.sleep(random.uniform(*PAUSE))
    return r.text


# ---------------------------------------------------------------- parsing

def job_ids_on_page(html: str) -> list[str]:
    """Advert ids on a listing page, in page order and de-duplicated."""
    soup = BeautifulSoup(html, "html.parser")
    seen, out = set(), []
    for a in soup.find_all("a", href=True):
        m = re.fullmatch(r"/jobs/(\d+)", a["href"])
        if m and m.group(1) not in seen:
            seen.add(m.group(1))
            out.append(m.group(1))
    return out


def flat_text(html: str) -> str:
    """Advert body as one flat text run, minus scripts, nav and form widgets.

    The form tags matter as much as the scripts. EURAXESS renders its search
    filters inside the page body, so a <select> of every country sits in the
    markup near the advert's own Country field. Left in, "Country" resolves
    to "Austria Belgium Bosnia and Herzegovina Bulgaria ..." - the option
    list, not the value. One row in ten, which is exactly the rate that
    survives a spot check and poisons the dataset later.
    """
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "svg",
                     "noscript", "iframe", "select", "option", "form",
                     "datalist", "aside"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


def field_after(text: str, label: str, stops: list[str], limit: int = 200) -> str:
    """Value printed after a label, up to whichever stop word comes first.

    EURAXESS renders the advert as a flat run of 'Label Value Label Value'
    with no markup separating them. A value ends where the next known label
    begins.
    """
    i = text.find(label)
    if i < 0:
        return ""
    rest = text[i + len(label):].lstrip(" :-")
    cut = len(rest)
    for stop in stops:
        j = rest.find(stop)
        if 0 <= j < cut:
            cut = j
    return rest[:cut].strip(" :-")[:limit].strip()


def parse_deadline(raw: str) -> str:
    """'5 Oct 2026 - 00:00 (Europe/Warsaw)' -> '2026-10-05'."""
    m = re.search(r"\b(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{4})", raw)
    if m and m.group(2)[:3].lower() in MONTHS:
        return f"{m.group(3)}-{MONTHS[m.group(2)[:3].lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", raw)
    return m.group(0) if m else ""


def advert_title(html: str) -> str:
    """The advert's own heading.

    Taken from <h1> when present, else from <title> with the site suffix
    stripped. Not from the flat text, where the heading sits next to
    navigation and cannot be told apart from it.
    """
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    if h1:
        t = re.sub(r"\s+", " ", h1.get_text(" ", strip=True))
        if len(t) > 3:
            return t[:300]
    if soup.title and soup.title.string:
        t = soup.title.string
        for suffix in ["| EURAXESS", "- EURAXESS", "EURAXESS"]:
            t = t.replace(suffix, "")
        return re.sub(r"\s+", " ", t).strip()[:300]
    return ""


def parse_advert(html: str, job_id: str) -> dict | None:
    """Turn one advert page into a labelled dict, or None if too thin."""
    text = flat_text(html)
    if len(text) < 800:
        return None

    LABELS = ["Organisation/Company", "Department", "Research Field",
              "Researcher Profile", "Positions", "Country",
              "Application Deadline", "Type of Contract", "Job Status",
              "Hours Per Week", "Offer Starting Date", "Is the job funded",
              "Reference Number", "Offer Description", "Where to apply",
              "Requirements", "Additional Information", "Education Level",
              "City", "State/Province", "Postal Code", "Company/Institute",
              "Number of offers available", "WorkLocation"]

    def val(label, limit=200):
        return field_after(text, label, [x for x in LABELS if x != label], limit)

    institution = val("Organisation/Company", 200) or val("Company/Institute", 200)

    # Country, with a sanity check.
    #
    # Stripping the form tags in flat_text() removes the usual cause of a
    # swallowed option list, but a source can always find a new way to put
    # a list of countries next to a label. A value naming several known
    # countries at once is a widget, not an answer, so it is dropped rather
    # than stored. An empty cell is honest; "Austria Belgium Bulgaria" is a
    # row that looks filled in and is not.
    country_raw = val("Country", 60)
    if sum(1 for name in COUNTRY_CODES if name in country_raw.lower()) > 1:
        country_raw = ""
    country = COUNTRY_FIX.get(country_raw.lower(), country_raw)

    # Degree comes from two labelled fields, in order of how specific they are.
    #
    # "Positions" is the exact one when present: it literally says "PhD
    # Positions" or "Postdoctoral Positions". When it is absent, EURAXESS
    # still prints "Researcher Profile", which uses the EU's own R1-R4
    # career-stage vocabulary: R1 is a doctoral candidate, R2 is a
    # post-doctoral researcher. That is a statement about the post, not a
    # guess from the headline, so it is safe to read.
    positions = val("Positions", 80).lower()
    profile = val("Researcher Profile", 150).lower()
    haystack = positions + " " + profile

    if "phd" in haystack or "doctoral candidate" in haystack or "(r1)" in haystack:
        degree = "PhD"
    elif "postdoc" in haystack or "recognised researcher" in haystack or "(r2)" in haystack:
        degree = "Postdoc"
    elif "researcher" in haystack:
        degree = "Researcher"
    else:
        degree = ""

    return {
        "id":            job_id,
        "url":           f"{BASE}/jobs/{job_id}",
        "title":         advert_title(html),
        "institution":   institution,
        "country":       country,
        "city":          val("City", 100),
        "degree":        degree,
        "research_field": val("Research Field", 300),
        "deadline":      parse_deadline(val("Application Deadline", 100)),
        "funded":        val("Is the job funded", 60),
        "contract":      val("Type of Contract", 60),
    }


# ---------------------------------------------------------------- main

def collect_country(session: requests.Session, country: str, pages: int) -> list[dict]:
    """Fetch listing pages, then advert pages, return normalized rows."""
    code = COUNTRY_CODES.get(country.lower())
    if not code:
        say(f"unknown country '{country}'. Known: {', '.join(sorted(COUNTRY_CODES))}")
        return []

    say(f"\n=== {country.upper()} (EURAXESS country code {code}) ===")

    # Step 1: collect all advert ids across N listing pages
    all_ids: list[str] = []
    for page in range(pages):
        # The filter key is job_country, not country. Using the wrong key
        # is silently ignored by EURAXESS: you get unfiltered results and
        # no error, which is the worst kind of bug in a collector.
        listing_url = f"{SEARCH}?f%5B0%5D=job_country%3A{code}&page={page}"
        say(f"  listing page {page + 1}/{pages}")
        html = get(session, listing_url)
        if not html:
            break
        ids = job_ids_on_page(html)
        say(f"    {len(ids)} adverts")
        for i in ids:
            if i not in all_ids:
                all_ids.append(i)

    say(f"  total unique adverts to fetch: {len(all_ids)}")

    # Step 2: fetch each advert and parse it
    rows: list[dict] = []
    for i, job_id in enumerate(all_ids, start=1):
        say(f"  advert {i}/{len(all_ids)} (id {job_id})")
        html = get(session, f"{BASE}/jobs/{job_id}")
        if not html:
            continue
        row = parse_advert(html, job_id)
        if row:
            rows.append(row)

    say(f"  parsed: {len(rows)} rows")

    # Check that the filter actually did something.
    #
    # EURAXESS ignores an unknown filter key silently and returns the
    # unfiltered feed. Without this check a run looks perfectly healthy
    # while collecting the wrong countries - which is how a dataset ends
    # up quietly wrong rather than loudly broken.
    wanted = country.lower()
    got = {(r.get("country") or "").lower() for r in rows}
    if rows and not any(wanted in g or g in wanted for g in got if g):
        say(f"  WARNING: asked for {country}, got {sorted(g for g in got if g)}")
        say("  The country filter did not apply. Check the filter key.")

    return rows


def write_csv(rows: list[dict], out: Path) -> None:
    if not rows:
        say("nothing to write")
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    fields = ["id", "url", "title", "institution", "country", "city",
              "degree", "research_field", "deadline", "funded", "contract"]

    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def summarize(rows: list[dict]) -> None:
    """Print a small breakdown, because shape matters as much as count."""
    from collections import Counter

    named = [r for r in rows if r.get("country")]
    n_countries = len({r["country"] for r in named})

    say("\n" + "=" * 60)
    say(f"COLLECTION COMPLETE: {len(rows)} adverts across {n_countries} "
        f"{'country' if n_countries == 1 else 'countries'}")
    say("=" * 60)

    for label, key in [("country", "country"), ("degree level", "degree")]:
        c = Counter((r.get(key) or "-") for r in rows if r.get(key))
        say(f"\nBy {label}:")
        for k, v in c.most_common(10):
            say(f"  {v:4d}  {k}")

    with_deadline = sum(1 for r in rows if r.get("deadline"))
    say(f"\nAdverts with a parseable deadline: {with_deadline}/{len(rows)}")

    # Say out loud what was not readable.
    #
    # A silent drop is how a collector reports 100% success while quietly
    # losing rows. The count belongs on screen next to the good news.
    missing = len(rows) - len(named)
    if missing:
        say(f"Adverts where the country could not be read: {missing}/{len(rows)}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Ethical collector for EURAXESS academic positions."
    )
    ap.add_argument("--country", action="append", required=True,
                    help="Country slug (e.g. canada, netherlands, germany). "
                         "Can be repeated for multi-country runs.")
    ap.add_argument("--pages", type=int, default=2,
                    help="Listing pages per country (default: 2, about 20 adverts).")
    ap.add_argument("--out", default="euraxess_positions.csv",
                    help="Output CSV path (default: euraxess_positions.csv).")
    args = ap.parse_args()

    say("euraxess_ethical_collector")
    say(f"  User-Agent: {UA}")
    say(f"  pause between fetches: {PAUSE[0]}-{PAUSE[1]}s")
    say(f"  cache directory: {CACHE}/")
    say(f"  countries: {', '.join(args.country)}")
    say(f"  listing pages per country: {args.pages}")
    say(f"  output: {args.out}")

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en"})

    all_rows: list[dict] = []
    for country in args.country:
        rows = collect_country(session, country, args.pages)
        all_rows.extend(rows)

    write_csv(all_rows, Path(args.out))
    summarize(all_rows)

    say(f"\nWrote {len(all_rows)} rows to {args.out}")
    say("\nCode: https://github.com/DataBizex/ethical-academic-collector")
    return 0


if __name__ == "__main__":
    sys.exit(main())
