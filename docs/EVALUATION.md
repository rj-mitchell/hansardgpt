# The test set and what it showed

First run 11 October 2026. The questions are in `eval/questions.toml`, the full results in `eval/runs/`, and the
relevance grades in `eval/judgments.jsonl`.

## What it is

62 questions covering everything the site understands: plain topics, parties, places, dates, the Lords, ministers and
the opposition, named people, gender, age, first-term MPs, marginal and safe seats, votes, combinations, loaded or
misspelt wording, an attempt to override the instructions, and follow-up questions. For each one, the test set
records the filters a careful reader would choose.

Three things are scored:

1. **Reading the question**: are the filters (the chips shown above each briefing) right? Every filter counts, and
   adding one the question did not ask for is a mistake.
2. **Choosing the sources**: how relevant are the 24 sources chosen, and how many parties and speaker groups do they
   cover? A small model grades each source 0 (off topic), 1 (related) or 2 (directly on the question); each source
   is only ever graded once, so later comparisons are nearly free.
3. **The briefings**: the automatic checks (citations found word for word in their sources, sentences without
   support, loaded words), and a blind side-by-side judgement of two models' briefings on the same sources.

Run it with `hansard eval plans`, `hansard eval sources` and `hansard eval briefings` (see `hansard eval --help`).
On the server, run them from `/opt/hansardgpt` inside the app container.

## 1. Reading the question

| Who reads the question | All filters right | Cost per question | Typical time |
|---|---|---|---|
| Opus 5.5 | 62 of 62 | 0.43p | 2.6 s |
| Sonnet 5.5 | 61 of 62 | 0.24p | 2.3 s |
| **Haiku 5.5** | **60 of 62** | **0.013p** | **1.5 s** |
| Built-in rules (free) | 47 of 62 | free | instant |

Haiku's two misses were defensible: it ended "during the pandemic" in mid-2022 rather than at the end of 2022, and
limited "the Safety of Rwanda Bill" to the months the bill was before Parliament. **Haiku now reads the questions**,
including for "Sources only", which used the far weaker built-in rules before. One line in `config/settings.toml`
(`query_parse_model`) switches back.

The test set also found a real bug, now fixed: when the model answered with the name of a group of regions
("northern") rather than the regions themselves, the filter was silently dropped, so "northern MPs" searched everyone.

## 2. Choosing the sources: re-ranking

Re-ranking means a small model on the server re-reads the best candidates alongside the question and re-scores them
(no charge per question). Tested here on keyword search, since only 1% of the record had meaning-based search on the
test machine (the live server will have all of it).

| Ranking | Sources directly on the question | Related or direct | Parties | Speaker groups | Time to choose |
|---|---|---|---|---|---|
| Current | 64% | 96% | 4.0 | 4.8 | 1.1 s |
| Re-rank best 60 | 67% | 97% | 4.1 | 4.8 | 3.8 s |
| Re-rank best 100 | 68% | 97% | 4.1 | 4.8 | 5.8 s |
| Re-rank best 150 | 69% | 97% | 4.1 | 4.8 | 8.1 s |

(Re-ranker: ms-marco-MiniLM-L-6-v2. A second model, jina-reranker-v1-tiny-en, did about the same. Times are on a
4-core machine.)

The first version of re-ranking narrowed the balance: on average one fewer speaker group per question. That is
fixed: re-ranking may now change the order of the evidence but never which groups are included.

**Decision: re-ranking is built but off for now.** It gives a modest gain for several seconds' wait on every search.
It should be tried again on the live server once meaning-based search is complete, because that may change both the
starting point and the speed. Turning it on is one line (`reranker` in `[ranking]`).

**How far to trust the grades:** Sonnet re-graded a random 120 of Haiku's grades. They agreed on relevant or not 91%
of the time, and never differed by more than one step. Haiku is a little more generous with "related". Every ranking
is graded by the same grader, so the comparisons are fair even where the absolute numbers are a little high.

## 3. Briefings: Opus or Sonnet

(Results to follow.)

## Cost of this round of testing

(To follow.)
