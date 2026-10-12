# Things to follow up on

Loose ends that need a person (an email, a decision or a check). Tick them off or delete them when done.

## Next time you are at a computer, in order

- [ ] **1. Install the latest version.** Merge
  <https://github.com/rj-mitchell/hansardgpt/compare/main...claude/hansard-parliament-engine-review-7veaif>, then on
  the server: `bash /opt/hansardgpt/deploy/update.sh`
- [ ] **2. Turn on the off-site backup** (Backblaze B2: bucket and key already made). On the server, run the command
  under "Setting up the off-site copy" in [HOSTING.md](HOSTING.md#backups). It asks for the bucket name, keyID and
  applicationKey, and hides the key as you paste it. Then check:
  `cd /opt/hansardgpt/deploy && docker compose run --rm -T app hansard offsite` should say `"ok": true`, and
  `docker compose run --rm -T app hansard backup --to /backups` should end "Off-site copy: stored in …".
- [ ] **3. Set up the admin page.**
  - Your admin token was created when the server was set up. To see it, on the server:
    `grep ^HANSARD_ADMIN_TOKEN= /opt/hansardgpt/deploy/.env | cut -d= -f2`
  - Save it in your password manager. Don't send it to anyone, Claude included.
  - Open <https://wheretheystand.uk/admin> and paste the token. The page shows:
    - spending, and warnings (including failed backups);
    - reports from readers, feedback and visits;
    - recent briefings, with "Feature" buttons, and topic briefings;
    - the update history.
  - The page forgets the token when you close the browser tab, so paste it each time, ideally from the password
    manager.
  - If the command prints nothing (the token is missing), create one and restart the site:
    `cd /opt/hansardgpt/deploy && sed -i '/^HANSARD_ADMIN_TOKEN=/d' .env && echo "HANSARD_ADMIN_TOKEN=$(openssl rand -hex 24)" >> .env && docker compose up -d`
    Then run the first command again to see it.
- [ ] **4. Load the new data now** rather than waiting for the weekly update. All of this is free. On the server, in
  `/opt/hansardgpt/deploy`:
  - `docker compose exec app hansard donations` (about a minute)
  - `docker compose exec app hansard groups` (seconds)
  - `docker compose exec -d app hansard interests --lords` (about 15 minutes, in the background)
  - Optional, slower:
    - `docker compose exec -d app hansard committees` (about two hours)
    - `docker compose exec -d app hansard devolved --files 2000` (about an hour)
    - `docker compose exec -d app hansard edms --months 200 --signatures 25000` (4–5 hours)
- [ ] **5. Click-check the links to other sites** (see below).
- [ ] **6. The two licence checks below** (Electoral Commission and TheyWorkForYou Votes).

The server must be able to reach these sites:
- `search.electoralcommission.org.uk`
- `raw.githubusercontent.com`
- `members-api.parliament.uk`
- `api.backblazeb2.com`, plus Backblaze's upload addresses (`*.backblazeb2.com`)
- `www.theyworkforyou.com`

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

## Electoral Commission: confirm the licence for the register of donations

*Added 12 October 2026.*

- **What it is.** The site downloads the Commission's register of donations (search.electoralcommission.org.uk)
  and shows donations to MPs. The search site states no licence, and the Commission's main website (where its
  copyright notice is) could not be reached from Claude's environment.
- **What we assume.** Its content is under the Open Government Licence v3.0, as is usual for UK public bodies; the
  site credits the Commission and links every donation to its record.
- **To do.** Open <https://www.electoralcommission.org.uk> and find its copyright or reuse notice (usually linked
  in the page footer). If it says the Open Government Licence, delete this item. If it says anything else, tell
  Claude.

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
