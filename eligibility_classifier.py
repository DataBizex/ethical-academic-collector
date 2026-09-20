# -*- coding: utf-8 -*-
"""
eligibility_classifier.py

Reads the adverts already collected by euraxess_ethical_collector.py and
classifies each one's eligibility language into one of four buckets, using
rules, not a confidence score.

Companion to euraxess_ethical_collector.py in this repository. Runs against
its cached advert pages, so no new network requests are made.

USAGE
-----
    python eligibility_classifier.py --input cross_continent.csv --out cross_continent_classified.csv

WHY RULES, NOT A SCORE
-----------------------
A funding note or a nationality clause is either present in the text or it
is not. Turning that into a probability ("72% likely eligible") invents
precision that does not exist and invites a reader to treat a guess as an
answer. This script says which of four things it found, or says it found
none of them.

THE FOUR CATEGORIES
--------------------
  international_covered      Stated as covering international applicants
  home_and_international     Stated as open to both domestic and international
  no_restriction_stated      Page read in full, no nationality rule stated
                              -> ASK BEFORE APPLYING
  unknown                    Page could not be read (not in cache)

Silence is not permission. A page that says nothing about nationality is
not the same as a page that says everyone may apply, and collapsing the
two is how a false "eligible" gets attached to a real person's decision.
That is why "no_restriction_stated" exists as its own category rather than
being folded into "international_covered".

WHAT THIS DOES NOT DO
----------------------
It does not tell you whether YOU specifically are eligible. It tells you
what the page states about nationality, in four buckets. The gap between
those two things is exactly where a human still has to read the actual
page before applying.
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

CACHE = Path(".cache") / "euraxess"


def say(text: str = "") -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode("ascii", "replace").decode("ascii"))


def flat_text(html: str) -> str:
    """Same extraction as the collector: strip scripts, nav, and form
    widgets before flattening, so a filter dropdown is never read as
    eligibility text."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "svg",
                     "noscript", "iframe", "select", "option", "form",
                     "datalist", "aside"]):
        tag.decompose()
    return re.sub(r"\s+", " ", soup.get_text(" ", strip=True))


# Phrases that state international applicants are covered. Matched against
# lowercased text. Deliberately narrow: a near-miss is left in
# no_restriction_stated rather than guessed into this category.
INTERNATIONAL_PHRASES = [
    "open to international applicants",
    "international candidates are welcome",
    "applicants of any nationality",
    "candidates of any nationality",
    "regardless of nationality",
    "non-eu candidates",
    "non eu candidates",
    "open to all nationalities",
]

# Phrases that state both domestic and international applicants are covered.
MIXED_PHRASES = [
    "national and international applicants",
    "domestic and international",
    "eu and non-eu",
    "eu and non eu",
    "local and international candidates",
]


def classify_text(text: str) -> str:
    low = text.lower()

    if any(p in low for p in MIXED_PHRASES):
        return "home_and_international"

    if any(p in low for p in INTERNATIONAL_PHRASES):
        return "international_covered"

    return "no_restriction_stated"


def cached_html(url: str) -> str | None:
    """Read a cached advert page. Never fetches: if it isn't cached, the
    row is classified as unknown rather than triggering a new request."""
    key = re.sub(r"[^a-zA-Z0-9]+", "_", url)[:110]
    path = CACHE / (key + ".html")
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8", errors="ignore")


def classify_row(url: str) -> str:
    html = cached_html(url)
    if html is None:
        return "unknown"
    text = flat_text(html)
    if len(text) < 800:
        return "unknown"
    return classify_text(text)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Classify eligibility language for already-collected adverts."
    )
    ap.add_argument("--input", required=True, help="CSV produced by the collector.")
    ap.add_argument("--out", required=True, help="Output CSV with the added column.")
    args = ap.parse_args()

    in_path = Path(args.input)
    if not in_path.exists():
        say(f"input not found: {in_path}")
        return 1
    if not CACHE.exists():
        say(f"no cache directory at {CACHE}/ — run the collector first")
        return 1

    with in_path.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    say(f"eligibility_classifier")
    say(f"  input: {in_path}  ({len(rows)} rows)")
    say(f"  cache: {CACHE}/")
    say()

    for i, row in enumerate(rows, start=1):
        url = row.get("url", "")
        category = classify_row(url)
        row["eligibility_category"] = category
        say(f"  {i}/{len(rows)}  id {row.get('id', '?')}  ->  {category}")

    out_path = Path(args.out)
    fields = list(rows[0].keys()) if rows else []
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter
    counts = Counter(r["eligibility_category"] for r in rows)

    say()
    say("=" * 60)
    say(f"CLASSIFICATION COMPLETE: {len(rows)} adverts")
    say("=" * 60)
    for label, key in [
        ("stated open to international", "international_covered"),
        ("stated open to domestic and international", "home_and_international"),
        ("silent on nationality -- ASK BEFORE APPLYING", "no_restriction_stated"),
        ("not checked (not in cache)", "unknown"),
    ]:
        say(f"  {counts.get(key, 0):4d}  {label}")

    say(f"\nWrote {len(rows)} rows to {out_path}")
    say("\nCode: https://github.com/DataBizex/ethical-academic-collector")
    return 0


if __name__ == "__main__":
    sys.exit(main())
