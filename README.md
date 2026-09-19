# ethical-academic-collector

A small, ethical Python collector for the European Commission's [EURAXESS](https://euraxess.ec.europa.eu) academic jobs portal.

Distilled from a production collector I have run inside my advisory practice since 2023, published here for anyone building international recruitment tooling who wants to start from a version that already respects the source.

## What it does

Reads a EURAXESS country slice (PhD, postdoc and research positions), writes a CSV with labelled fields.

That is all. Deduplication across sources, eligibility parsing, and full-text search all live downstream and are their own decisions.

## Why "ethical"

Six principles, in order of how much they matter:

1. **Honest User-Agent.** The source sees exactly what is fetching and can rate-limit or block it. No browser spoofing.
2. **Slow.** Random 3-6 second pause between requests. A production run hit HTTP 429 at ~240 requests when the pause was 1-2.5 seconds. Slower is cheaper.
3. **Cached.** Once an advert is fetched, it stays on disk. Re-running the script never re-fetches the same URL.
4. **Filtered at collection, not later.** A `--country` flag stops requests you would only throw away later.
5. **No hidden fields.** Everything pulled is a labelled field from the advert page. No headline guessing.
6. **Public code.** If the source objects, they can read what runs against them.

## Quick start

```powershell
pip install requests beautifulsoup4

# One country
python euraxess_ethical_collector.py --country canada --pages 3 --out canada.csv

# Cross-continent (relevant right now given the Canada-EU Erasmus+ talks)
python euraxess_ethical_collector.py --country canada --country netherlands --pages 3 --out cross_continent.csv
```

Expected wall-clock time: about 20-40 minutes for 30-60 adverts across two countries, mostly spent politely waiting between fetches.

## Supported countries

31 European countries plus Canada. Full list is in `COUNTRY_CODES` inside the script — adding more means opening the EURAXESS search page in a browser and reading the code from the country `<select>`, not guessing.

## Output

CSV with these columns:

| Column | What it is |
|---|---|
| `id` | EURAXESS advert id |
| `url` | Direct link to the advert page |
| `title` | Job title |
| `institution` | Hiring organisation |
| `country` | Normalized country name |
| `city` | City |
| `degree` | PhD, Postdoc, Researcher, or blank |
| `research_field` | EURAXESS-vocabulary research field |
| `deadline` | Application deadline in YYYY-MM-DD, or blank |
| `funded` | "Yes" / "No" / blank |
| `contract` | Temporary, Permanent, etc. |

## What it will not tell you

Whether the position is open to applicants from your country. EURAXESS often prints a salary, but a salary is not a statement about who may receive the funding. The only reliable answer to "can this specific person apply here" is on the institution's own page, in the eligibility text, which is a downstream decision.

## Requirements

- Python 3.10+
- `requests`
- `beautifulsoup4`

Nothing else. No Selenium, no headless browser, no API key. EURAXESS is one of the few sources where that is true, and the reason this collector exists.

## Not affiliated with

The European Commission. EURAXESS is an EU public service; this is a private tool that reads it.

## License

MIT.
