# Things to follow up on

Loose ends that need a person (an email, a decision or a check). Tick them off or delete them when done.

## Next time you are at a computer, in order

*Done 12 October: installing the 1997 version, the off-site backup, the admin page, loading the new data and the
licence checks.*

- [ ] **1. Install the latest version** (company roles). Merge
  <https://github.com/rj-mitchell/hansardgpt/compare/main...claude/hansard-parliament-engine-review-7veaif>, then on
  the server: `bash /opt/hansardgpt/deploy/update.sh`
- [ ] **2. Make a Companies House API key** (free). At
  <https://developer.company-information.service.gov.uk/>, sign in with your Companies House account, then:
  - "Your applications" → "Create an application". Name: Where They Stand. Description: "Shows MPs' and peers'
    company roles on wheretheystand.uk". Environment: **Live**. Save.
  - In the application, "Create new key" → key type **REST**. Leave "restricted IPs" and "JavaScript domains"
    empty. Save, and copy the key it shows.
- [ ] **3. Put the key on the server.** Run this; it asks for the key without showing it, saves it in the server's
  settings file and restarts the site:

  ```
  cd /opt/hansardgpt/deploy && read -rsp "Companies House API key: " K && echo && sed -i -e '/^HANSARD_COMPANIES_HOUSE_KEY=/d' -e '$a\' .env && printf 'HANSARD_COMPANIES_HOUSE_KEY=%s\n' "$K" >> .env && unset K && docker compose up -d
  ```

  Don't paste the key anywhere else, Claude included.
- [ ] **4. Try it on 20 members:** `cd /opt/hansardgpt/deploy && docker compose exec app hansard directorships --count 20`
  - It should end with `"checked": 20`. If it says the key was refused, run
    `docker compose exec app hansard directorships --check`: it says why (for example a key made for a Test
    application rather than Live) without showing the key. Paste its output to Claude if unsure.
  - Then `docker compose exec app hansard directorships --show "a"` lists what it found for those 20. Paste that
    output to Claude if you'd like the matches checked; it contains no key.
- [ ] **5. Look up everyone now**, rather than a few hundred members per update over a week or two (free; about
  2–3 hours, in the background):
  `cd /opt/hansardgpt/deploy && docker compose exec -d app hansard directorships --count 4000`
- [ ] **6. Click-check the links to other sites** (see below), and the new "Company roles" links on an MP's page.

The server must be able to reach these sites:
- `search.electoralcommission.org.uk`
- `raw.githubusercontent.com`
- `members-api.parliament.uk`
- `api.backblazeb2.com`, plus Backblaze's upload addresses (`*.backblazeb2.com`)
- `www.theyworkforyou.com` and `data.theyworkforyou.com` (already used for the record)
- `votes.theyworkforyou.com` (whip reports)
- `api.company-information.service.gov.uk` (company roles)
- `en.wikipedia.org` (dates of birth Wikidata lacks)

If your server places no limits on outgoing connections (the usual case), there is nothing to do.

## Click-check a few links to other sites

*Added 12 October 2026.*

- **What it is.** The site now links to other free sites wherever they do something it does not. Most of those
  sites block automated checks, so Claude could not open the deep links.
- **To do.** After deploying, click each of these once. If any lands on an error or the wrong page, tell Claude;
  it will switch that link to the site's front page.
  - On a briefing: "Hansard search" (it should open Hansard's results for the same words and dates).
  - On a bill page: "Parliament's bills site" (it should show a search for that bill).
  - On an MP's page: "Parliament's profile", "TheyWorkForYou" and "email alerts".
  - On a peer's page: "official register" under Registered interests (the Register of Lords' Interests).
  - On an MSP's and an MLA's page: "official register" under Registered interests.

## Electoral Commission: licence (done)

*Added 12 October 2026; settled the same day.*

- The Commission's licence (at api.electoralcommission.org.uk/terms) is the Open Government Licence v3.0 with some
  extra conditions. The site now shows the attribution it asks for ("Contains Electoral Commission Information ©
  Electoral Commission and/or database right") on the donations page, on each MP's donations and in the
  methodology and ATTRIBUTION.
- That page is written for the Commission's elections API. Its list of exclusions includes automated extraction
  ("screen scraping"). The site doesn't scrape: once a week it uses the register's own "Export to CSV" download,
  one request at a time. If you ever want that confirmed, email the Commission (the contact on the same page)
  and say: "We download the register of donations once a week with the search site's CSV export and show
  donations to MPs, credited and linked to each record. Is that within your terms?" Nothing needs doing
  otherwise.

## Companies House: confirm the terms for company roles

*Added 12 October 2026.*

- **What it is.** The site looks up MPs' and peers' company roles through the Companies House public data API (your
  free key). Claude's environment could not reach the Companies House developer site to read its terms.
- **What we assume.** The register is public and the API is offered for reuse. The site shows only company names,
  roles and dates (no addresses, nationality or dates of birth), credits Companies House and links each entry to
  its record, and stays well under the rate limit (600 requests in five minutes).
- **To do.** When you make the key, read the terms you are asked to accept. If they say anything about
  attribution wording, limits on showing officers' details, or not combining the data with other sources, tell
  Claude. Otherwise delete this item.

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
