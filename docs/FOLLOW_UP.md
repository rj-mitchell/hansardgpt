# Things to follow up on

Loose ends that need a person (an email, a decision or a check), newest first. Tick them off or delete them
when done.

## TheyWorkForYou Votes: licence for the plain-English vote descriptions

*Added 12 October 2026.*

- **What it is.** The site shows "Voting aye: …" sentences under about 1,600 votes and gives them to briefings.
  mySociety wrote them for TheyWorkForYou Votes. We download them from
  `theyworkforyou.com/pwdata/votes/divisions.parquet` (the same tables are listed on
  <https://votes.theyworkforyou.com/data>).
- **What the sites say.**
  - **TheyWorkForYou Votes** (home, About and Data pages, checked 12 October 2026) states no licence anywhere.
  - **The terms for TheyWorkForYou's paid API** (<https://www.theyworkforyou.com/api/terms>) are the nearest thing:
    - Parliamentary material may be reused under the Open Parliament Licence.
    - mySociety's "own data – lists of MPs, Lords, constituencies and so on" is under Creative Commons
      Attribution-ShareAlike 2.5.
    - They ask for credit such as "Data service provided by TheyWorkForYou", with a link.
  - Those terms are for the API, not the bulk files we use, and do not mention the vote descriptions. So it is not
    explicit.
- **What we do now.** We assume reuse with credit is fine. Each sentence is labelled "(TheyWorkForYou Votes)", and
  the methodology page and ATTRIBUTION.md credit mySociety.
- **To do.** Email mySociety (hello@mysociety.org), for example:

  > I run wheretheystand.uk, a free, non-commercial site about the UK Parliament's records. Next to votes it
  > shows your TheyWorkForYou Votes "voting aye/no means" descriptions, from the divisions.parquet download,
  > credited to TheyWorkForYou Votes with a link. Is that OK, under what licence, and how would you like to be
  > credited?

- **If the answer is share-alike (CC BY-SA).** Their sentences on our pages would be shared under the same terms,
  which fits how we already credit them.
- **If the answer is no.** Ask Claude to turn the descriptions off. The site's own vote labels ("amendment",
  "second reading" and so on) are unaffected.

## Committees: four committees Parliament's service failed on

*Added 12 October 2026.*

- **What happened.** Parliament's committees service returned errors (500/503) for four committees' inquiry lists
  during the first full rebuild, so about 170 inquiry pages show no committee.
- **What happens next.** The weekly update retries them automatically.
- **To do.** A week or so after deploying, run this on the server:

  ```
  journalctl -u hansard-sync --since "7 days ago" | grep "could not be listed"
  ```

  No output means all is well. If the same committees keep appearing, tell Claude.

## Dates of birth: about 110 members with no Wikidata entry

*Added 12 October 2026.*

- **What it is.** Members since 2010 (mostly peers) who have no Wikidata entry, so the site does not know their age.
  They are left out of age groupings.
- **To do.** Optional. A small corrections file could fill them in from reliable published sources (for example
  Who's Who or Parliament's own biographies). It needs a person to check each entry.
