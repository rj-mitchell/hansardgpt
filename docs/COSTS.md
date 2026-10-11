# What costs money on Where They Stand

Last updated 11 October 2026. AI prices are Anthropic's, per call, measured on this site; £1 ≈ $1.27.

## Free (no AI, no charge per use)

These run on the server you already pay for, so extra use costs nothing.

- **Searching and showing sources**, including the "Sources only" button and the sources shown under every briefing.
  Keyword and meaning-based search both run on the server itself.
- **Repeat questions.** A question already answered with the same settings is served from the saved copy for up to a
  week (or until new records arrive), at no cost.
- **Shared briefing links** and printing or copying a briefing.
- **MP and peer pages**, **Find your MP** by postcode, election results and majorities, voting records and rebellions.
- **Re-ranking**, if turned on: a small model that runs on the server, not a paid AI service.
- **The twice-daily data update**, the search index, the backups, the status, admin and information pages.
- **Future features that need no AI**: charts, bill and debate pages without briefings, timelines, glossary, RSS feeds,
  Early Day Motions, the Register of Interests, committee pages and witness lists.

## Cheap (well under 1p each)

- **Reading the question** (choosing the filters shown as chips) before each new briefing: about 0.4p with Opus. The
  test set shows Haiku does this just as well for about 0.01p, so switching would make it effectively free.
- **Running the test set**: reading 60 questions costs about 1p with Haiku and about 25p with Opus. Grading the
  relevance of sources costs a few pence a run, and only for passages not graded before.

## Costs more

- **A new briefing**: about 9p (12 cents) with Opus, the bulk of the running cost. Briefings in "comprehensive" mode
  use more sources and more thinking, so roughly double. Sonnet would roughly halve the cost; the test set compares
  the quality.
- **Comparisons** (two MPs, parties or nations side by side): the cost of one or two briefings.
- **Topic briefings, featured briefings and a weekly "In Parliament this week" page**: a briefing each time one is
  written or refreshed, so a few pounds a month for a modest set.
- **Plain-English summaries of committee evidence** (a future item): about 4p to 15p per session, written once.
- **Running a full briefing comparison in the test set**: about £2 for 10 questions with two models.

## Fixed costs (whatever the use)

- **The server** (Hostkey), monthly.
- **The domain names**, yearly.
- **Email** for admin@wheretheystand.uk, if it is a paid service.

## How spending is controlled

- The site stops writing new briefings for the day at **$10**, and for the month at **$150**. Sources are still shown.
- Every 10 new briefings in a day, a visitor sees a short note on what the site costs, with the Ko-fi link. It is not a
  paywall: they can carry on. If they go through to Ko-fi they are not reminded again that day.
- As a backstop against automated use, one visitor can have at most **40** new briefings a day.
- The admin page shows spending, with warnings at 50% and 80% of the monthly budget.
- A spending limit set in the Anthropic Console is a second safety net (see the to-do list in `ROADMAP.md`).
