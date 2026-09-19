# Development notes

Four bugs found on the first live run, in the order they surfaced. Kept here because the failure modes are more instructive than the working code, and because every one of them is the kind that returns a plausible answer rather than an error.

---

## 1. The filter key that did nothing

**Symptom.** Asked for Canada. Got 7 Sweden, 2 Netherlands, 1 Switzerland. Zero Canada. No error, no warning, exit code 0.

**Cause.** The URL was built with `f[0]=country:682`. EURAXESS expects `f[0]=job_country:682`. An unrecognised filter key is discarded silently, and the unfiltered feed is returned.

```diff
- listing_url = f"{SEARCH}?f%5B0%5D=country%3A{code}&page={page}"
+ listing_url = f"{SEARCH}?f%5B0%5D=job_country%3A{code}&page={page}"
```

**Why it matters more than it looks.** A collector that returns nothing is fixed within the hour. A collector that returns the wrong country at full speed, with a healthy-looking log, gets trusted. The dataset is wrong and nothing announces it.

**Guard added.** After each country run, the rows are checked against the country that was requested. A mismatch prints a warning:

```
WARNING: asked for canada, got ['sweden', 'switzerland', 'the netherlands']
The country filter did not apply. Check the filter key.
```

---

## 2. Two fields read from labels that do not exist

**Symptom.** `By degree level:` printed nothing at all. Titles were duplicates of the research field.

**Cause.** Both were read with `field_after(text, "Job Title", ...)` and similar. EURAXESS has no `Job Title` label. The advert heading lives in the page `<h1>`, and the career stage lives under `Positions` and `Researcher Profile`.

**Fix.** Title now comes from `<h1>`, falling back to `<title>` with the site suffix stripped. Degree reads `Positions` first, then falls back to the EU's own R1-R4 career-stage vocabulary in `Researcher Profile`: R1 is a doctoral candidate, R2 a post-doctoral researcher. Both are stated fields, not inferences from a headline.

---

## 3. The country dropdown read as a value

**Symptom.** One row in ten had a country of:

```
Austria Belgium Bosnia and Herzegovina Bulgaria Croatia Cypr
```

**Cause.** EURAXESS renders its search filters inside the page body. A `<select>` listing every country sits in the markup near the advert's own Country field, so flattening the page to text put the whole option list where the value should be.

**Fix, in two layers.** The parser now strips `select`, `option`, `form`, `datalist` and `aside` before flattening — that removes the cause. A second check then rejects any country value naming more than one known country, on the assumption that a source which found one way to put a list next to a label will find another.

The rejected value is dropped, not replaced with a guess. An empty cell is honest. `Austria Belgium Bulgaria` is a row that looks filled in and is not.

**Rate note.** One in ten is the dangerous frequency. Nine good rows survive any spot check.

---

## 4. The silent drop

**Symptom.** The summary read `57 adverts across 2 countries` while listing only one country, and the row whose country had been rejected in bug 3 disappeared without comment.

**Cause.** Empty strings were counted as a distinct country, and nothing reported how many rows had been dropped.

**Fix.** Only non-empty countries are counted, and the summary now ends with an explicit line when anything was unreadable:

```
Adverts where the country could not be read: 1/57
```

**Why.** A silent drop is how a collector reports total success while quietly losing rows. The count belongs on screen next to the good news, not in a log nobody opens.

---

## The pattern

None of these four raised an exception. Every one produced output that looked correct.

That is the failure mode worth designing against in a collector: not the crash, but the plausible answer. The defences that caught them are cheap and belong in any collector that runs unattended.

- Check that a filter actually filtered.
- Read only labels the source really prints.
- Strip the page furniture before flattening text.
- Report what you dropped.

---

## First full run

```
57 adverts, 2 countries, 6 listing pages

By country:
   30  The Netherlands
   26  Canada

By degree level:
   35  PhD
   20  Postdoc
    2  Researcher

Adverts with a parseable deadline: 57/57
Adverts where the country could not be read: 1/57
```
