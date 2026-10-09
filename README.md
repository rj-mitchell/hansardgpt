# HansardGPT

**Verifiable answers about the UK Parliament, cited to Hansard.**

HansardGPT is an open-source research engine for journalists, researchers and policy analysts. Ask a
plain-English question ("How have ministers justified delays to HS2?") and get an answer written *only* from
retrieved Hansard records. Every statement carries a `[Source n]` citation that opens the verbatim record,
with:

* the speaker's name, party and constituency **on that date**;
* their ministerial, shadow or committee-chair role at the time;
* the Hansard column number (or written-question reference);
* links to the official Parliament record and to the exact record on TheyWorkForYou.

If the archive has nothing relevant, it says **"No records found."** instead of guessing.

> Status: v1, covering May 2010 (the 2010 general election) to today. Commons, Lords, Westminster Hall, written
> answers and statements (both Houses), Public Bill Committees and every division (vote).

---

## Contents

1. [How it works](#how-it-works)
2. [Trying it (offline sample)](#trying-it-offline-sample)
3. [Running it on a server](#running-it-on-a-server)
4. [Day-to-day operation](#day-to-day-operation)
5. [Ranking: recency and role weighting](#ranking-recency-and-role-weighting)
6. [How answers stay grounded](#how-answers-stay-grounded)
7. [Data sources and licensing](#data-sources-and-licensing)
8. [Development](#development)
9. [Measured performance](#measured-performance)
10. [Known limitations](#known-limitations)

---

## How it works

```
 TheyWorkForYou scrapedxml ──► streaming parser ──► Parquet (zstd, by source & year) ──► DuckDB SQL
 (rsync or HTTPS, daily)        (lxml iterparse)            │
                                                           ▼
 mysociety/parlparse members/ ──► reference tables ──► speaker-on-date enrichment
 (git pull, daily)                (people, seats, offices,      │
 ONS / mySociety boundaries       regions, parties)             ▼
                                                  LanceDB: BM25 passages + vectors (local model)
                                                           │
 question ─► filter plan (Claude, shown as editable chips) ─► deterministic retrieval & ranking
                                                           │
                                       Claude (Opus 5.5) answers ONLY from the sources,
                                       with native search-result citations ─► verification ─► UI
```

* **Ingest.** `lxml.etree.iterparse` streams each file and frees elements as it goes, so memory stays flat
  however large the file is. Ingesting everything since 2010 (24,695 files, 3.7 million records) takes about
  3 minutes with a peak of 664 MB across all worker processes.
* **Storage.** Zstd-compressed Parquet, partitioned by source and year. Each sitting day is replaced atomically
  when Hansard issues a correction. Days older than 90 days are compacted into one file per partition, so
  queries spanning many years run in tens of milliseconds.
* **Identity.** Speakers are resolved **only by parlparse IDs**, never by name. One person ID covers every
  name and title change. For example, David Cameron is "David Cameron", MP for Witney, Prime Minister in 2012,
  and "Lord Cameron of Chipping Norton", Foreign Secretary in the Lords in 2024. Both are the same person.
* **Temporal joins.** Every open-ended or partial date is normalised: a missing or empty end becomes
  `9999-12-31`, and a year on its own like `"1983"` covers the whole year. Duplicate office rows in the source
  data are removed and overlapping spells merged. Each join is aggregated per record, so a minister with two
  posts never duplicates a speech.
* **Search.** LanceDB holds a BM25 full-text index over 4.7 million passages, plus vectors from a local
  open-source embedding model (`snowflake-arctic-embed-xs`, run on CPU). Both are filtered by date, House,
  region, party, person and role.

## Trying it (offline sample)

Needs Python 3.12+, [uv](https://docs.astral.sh/uv/) and Node 20+.

```bash
uv sync --extra embed
(cd web && npm ci && npm run build)
uv run hansard bootstrap --sample     # ~5 seconds, no downloads, uses real Hansard excerpts
uv run hansard serve                  # open http://127.0.0.1:8000
```

The sample uses a small set of real Hansard excerpts, sign-in is turned off, and it uses a simple offline
embedder. Set `ANTHROPIC_API_KEY` to get written answers; without a key you see ranked, cited sources only.

## Running it on a server

Recommended: 4–8 vCPU, 16 GB RAM and 60 GB of disk.

| Data | Size |
|---|---|
| Raw XML since 2010 | 4.9 GB |
| Parquet store | 1.2 GB |
| Keyword index | 4.1 GB |
| Vectors | about 8 GB |

On a fresh Ubuntu 24.04 server pointed at by a domain name:

```bash
sudo bash deploy/provision.sh
```

The script:
* installs Docker;
* starts the app behind Caddy, which provides automatic HTTPS;
* runs the first data load in the background (30–60 minutes);
* installs a timer that runs the sync at 07:15 and 19:15 UK time.

Then create your account:

```bash
cd /opt/hansardgpt/deploy && docker compose exec app hansard user add you@example.org --admin
```

**Semantic-search build time.** The initial embedding of about 4.7 million passages is resumable and runs
newest first. It takes roughly a day on 4 cores, and less on 8. Keyword search works from the start, and
recent years become semantically searchable within the first hours. Each sync continues the embedding for up
to 4 hours.

## Day-to-day operation

| Command | What it does |
|---|---|
| `hansard sync` | Full incremental update (this is what the timer runs): member data, new and corrected Hansard, index, embeddings, compaction, sync log |
| `hansard status` | Files ingested, indexed and embedded; parlparse commit; recent runs |
| `hansard search "…" --from 2018-01-01 --region "North East"` | Ranked sources from the terminal (no model call) |
| `hansard user add/list/disable` | Invite-only accounts (argon2 password hashes) |
| `hansard embed --max-minutes 60` | Continue building semantic vectors |
| `hansard reference` | Rebuild member and role tables from parlparse |

**Cost control** (in `config/settings.toml`, `[usage]`):

* a per-user daily question cap;
* a monthly spend cap for the whole service;
* each answer's token usage and cost logged to SQLite.

Admins can view usage at `/api/admin/usage`.

**Backups.** Everything can be rebuilt from public sources except `data/state.sqlite`, which holds users,
usage and the sync log. Back that file up.

## Ranking: recency and role weighting

Ranking is soft. Nothing is excluded unless you set a filter.

```
score = relevance × recency × authority

relevance = ½ · BM25/max(BM25)  +  ½ · calibrated cosine similarity
recency   = 0.35 + 0.65 · 0.5^(age / half-life)           (slider: off … half-life 2 years)
authority = 1 + (W − 1) · m                               (slider W: 1.0× … 2.0×)
```

The authority multiplier `m` depends on the speaker's role on the date of the record:

| Speaker's role on the date | m |
|---|---|
| Government minister or select committee chair whose portfolio matches the question | 1.0 |
| Shadow minister, matching portfolio | 0.6 |
| Minister or chair, other portfolio | 0.5 |
| Shadow minister, other portfolio | 0.3 |
| Backbencher | 0 |

* **Recency floor.** Because of the 0.35 floor, a much stronger 2011 match still beats a weak 2025 one.
* **Portfolios.** Departments are mapped to stable portfolios that survive renames. For example DECC → BEIS
  → DESNZ all map to `energy_climate`, so an energy question boosts the energy minister of every era. Every
  post-2010 role title in parlparse maps to a portfolio or is deliberately marked as having none, and a test
  enforces this.
* **Transparency.** The source drawer shows each source's score breakdown.

## How answers stay grounded

1. **Editable filters.** The question becomes an editable filter plan: dates, Houses, regions, parties,
   speakers, roles and boosted portfolios. "Northern MPs" means the North East, North West, and Yorkshire and
   The Humber; you can change this in settings. You see and can edit every filter.
2. **Deterministic retrieval.** The same plan and sliders always give the same sources.
3. **Sources only.** Claude (Opus 5.5) receives only those sources, as search-result blocks with citations
   enabled, under rules that forbid outside knowledge. When the sources don't answer the question, it must say
   "No records found."
4. **Verification.** Every citation is re-checked against our copy of the source text. Any uncited
   substantive sentence is flagged in the UI as unsupported, never passed off as sourced.
5. **No guessing on empty results.** If retrieval finds nothing, the model is not called at all.

## Data sources and licensing

* **Proceedings:** [TheyWorkForYou / ParlParse](https://parser.theyworkforyou.com/hansard.html) XML (mySociety),
  under the Open Parliament Licence v3.0.
* **Members, offices and committees:** [mysociety/parlparse](https://github.com/mysociety/parlparse)
  `members/`, comprising `people.json`, `ministers-2010.json` and `posts/westminster-parliament-posts.json`.
* **Constituency → region:** ONS (Dec 2021 constituency names and codes) and mySociety's
  [2025-constituencies](https://github.com/mysociety/2025-constituencies) data, under the Open Government
  Licence v3.0. The vendored lookup in `data_static/geo/` is rebuilt by `scripts/build_geo_lookups.py`.

The app shows these attributions on every page; see [ATTRIBUTION.md](ATTRIBUTION.md). Code is MIT-licensed.
Hugging Face is used only for a one-off download of the embedding model's weights, which are pinned by
SHA-256. No data comes from there.

## Development

```bash
uv sync --extra embed
uv run pytest                 # Python tests (offline; Claude is mocked)
uv run ruff check src tests scripts
cd web && npm ci && npm test && npm run typecheck
```

* **Python tests.** The fixtures are trimmed copies of real data (`scripts/make_fixtures.py`). They cover:
  * identity across name and title changes (Cameron);
  * role history and duplicate source rows (Benn);
  * concurrent posts (Greening);
  * open-ended and year-only dates;
  * boundary invariance across the 2024 review;
  * every file type in the parser;
  * incremental ingest, including corrections to already-compacted days;
  * memory that stays flat with file size;
  * composite scoring;
  * filters;
  * citation verification;
  * the "no records found" path, refusals, auth and caps, and the daily sync with a member reshuffle.
* **Live role-mapping check.** `PARLPARSE_MEMBERS=/path/to/members uv run pytest tests/test_portfolios.py`
  checks the role mapping against the current live data.

## Measured performance

On a 4-vCPU cloud VM, using the full archive since 2010:

| Step | Result |
|---|---|
| Download (HTTPS) | 24,695 files, 4.9 GB, 14 minutes |
| Ingest | 3.73 M records, 5,344 divisions, 2.35 M votes; 3 minutes; peak 664 MB across all processes |
| Keyword index | 4.72 M passages in 9 minutes; peak 2.7 GB during the full-text build |
| Multi-year SQL (Parquet + DuckDB) | 20–50 ms |
| Search (filters + BM25 + vectors + ranking + full records + speaker profiles) | 0.25–0.5 s warm |
| Embedding (`arctic-embed-xs`, CPU, batch 8) | 35–110 passages/s depending on length; peak ~1 GB |

## Known limitations

* **Official links.** Hansard's modern XML has no per-speech official URL. For debates, the official link
  opens the sitting day; the column number and the TheyWorkForYou link pinpoint the speech. Written questions
  and statements link to the exact official record.
* **Regions.** Region filters apply to MPs; peers have no constituencies.
* **Party data.** Party on a date comes from parlparse memberships, so the tool reflects any gaps in that
  source.
* **Recency of member data.** Committee and role data reflect what mySociety has published, refreshed daily.
* **Earlier years.** Extending before 2010 needs the 1997 and 2005 boundary sets and the pre-2010
  `ministers.json`. The code paths are in place, but this is not yet enabled or tested.
