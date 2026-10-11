# Where They Stand: to-do list and roadmap

Last updated 11 October 2026, the day the site went live.

**Time to build:** S = a few hours · M = a day or two · L = several days or more. Where a more exact estimate helps,
it is given in days of development work. Your own time is usually just merging the change on GitHub and running the
update script. Running costs are for the Anthropic API unless stated.

What is free, cheap and more expensive to run is listed in `docs/COSTS.md`.

**Done** items are marked ✓ and kept here so the list shows what has been built.

---

## Part 1. Your to-do list

### Soon

- [ ] **Open the admin page** at https://wheretheystand.uk/admin and paste your admin token. Bookmark it, and keep the
      token in your password manager. On the server, `grep ^HANSARD_ADMIN_TOKEN= /opt/hansardgpt/deploy/.env` shows it.
- [ ] **Switch to a key login.** Step 5 of `docs/HOSTING.md` makes an SSH key and turns password logins off. About 10
      minutes; do it from your own computer, with the safety net described there.
- [ ] **Set a spending limit in the Anthropic Console** (Settings → Limits). The site has its own caps ($10 a day,
      $150 a month), but a limit at Anthropic is a second safety net. Turn off auto-reload of credit unless you want it.
- [ ] **Tidy up API keys** in the Console. Delete the old key that no longer works. The working key used for testing
      in the Claude Code environment can also be deleted once you no longer need me to run live tests.
- [ ] **Check email works**: send a test message to admin@wheretheystand.uk.
- [ ] **Fill in the Ko-fi page**, using the short description already written, with £3.50 as the default amount.
- [ ] **Leave the first data load to finish.** Keyword search already covers everything since 2010. Meaning-based
      search builds in the background over the next day or so; the Status page shows progress.

### Regularly

- [ ] **Run the health check** after updates and now and then:
      `bash /opt/hansardgpt/deploy/check.sh`.
- [ ] **Copy the backups to your own computer** about once a month. In Terminal or PowerShell on your computer:
      `scp "root@YOUR.SERVER.IP:/opt/hansardgpt/deploy/backups/*.tar.gz" .`
- [ ] **Read the admin page** weekly: spending, reports from readers, feedback marked "not useful".
- [ ] **Install updates** when there is a new version: merge it on GitHub, then on the server
      `bash /opt/hansardgpt/deploy/update.sh`.

### Before telling people about the site

- [ ] **Free uptime monitor** (for example UptimeRobot or Better Stack) checking
      `https://wheretheystand.uk/api/health`, so you get an email if the site goes down.
- [ ] **Hostkey snapshot backups**, if offered, for the whole server.
- [ ] **Claim the name on social media** (Bluesky, X, LinkedIn, Mastodon).
- [ ] **Search the UK trade mark register** for "Where They Stand".
- [ ] **A short legal review** of the AI briefings, the privacy notice and the terms.
- [ ] **Register with Google Search Console and Bing Webmaster Tools** and submit
      `https://wheretheystand.uk/sitemap.xml`, so search engines find the site.
- [ ] **Friendly note to the creator of wheretheystand.nz**: same name, different countries, complementary approaches.
      A mutual link would help both sites.

---

## Part 2. Development roadmap

### A. "Coming next" (promised on the About page)

| Item | Effort | Notes |
|---|---|---|
| ✓ **Your MP**: enter a postcode to see your MP, ask about them, see what they've said on a topic and their votes | M | Done 11 October: uses Parliament's own postcode look-up. No AI cost |
| **Comparisons**: two MPs, parties or nations side by side on the same question | M | Costs the same as one or two briefings |
| **Charts**: how much a subject was debated over time, by party, House and nation | M | No AI cost. Must show context with every number (the lesson from the NZ site's expenses) |
| ✓ **Topic briefings**: regularly refreshed briefings on the issues in the news, on permanent pages | S–M | Done 11 October: 16 topics in `config/topics.toml`. Rewritten only when due and the evidence has changed: about £2 to start, then roughly £2–6 a month |
| **1997–2010** records | M–L | Needs the older boundary sets; disk use roughly doubles |
| **Early Day Motions**: who signed which motions | M | Good cross-party evidence of support |
| **Select committee evidence and reports** | L | Different source and format |
| **Scottish Parliament, Senedd, Northern Ireland Assembly** | L each | Each has its own record and member data |

### B. Discussed earlier, not yet built

| Item | Effort | Notes |
|---|---|---|
| ✓ **MP and peer pages**: roles over time, seats, recent contributions, voting record, briefings asked about them | M | Done 11 October, with seats and majorities. Still to add: briefings asked about them |
| **Recent-activity feed** on each MP page ("spoke in…", "voted against their party on…") | S, after MP pages | |
| **Voting record summaries** per member and topic, with the method shown in full | M | Per member done (votes and rebellions on MP pages); per topic still to do |
| **Test set of 50–100 questions with scoring** | M | About $3–5 per run. The foundation for the next two items |
| **Cheaper models where they are just as good** (for example, a smaller model for reading the question) | S, after the test set | Lowers running costs |
| **Re-ranking step** for sharper choice of sources | M | Judged with the test set |
| **Public search API** for researchers (search only, no AI briefings), documented and rate-limited | M | |
| **Topic alerts by email** (a weekly digest on chosen topics) | M–L | Needs an email-sending service and a sign-up with consent |
| **Cloudflare protection** (proxy on) | S–M | Make the server trust Cloudflare's visitor details, choose the right certificate setting, update the privacy notice |
| **Off-site backups** sent automatically to cheap storage | S | Needs a storage account from you (for example Backblaze B2) |
| **Contact and press page**: a short media pack, logo files, how to cite the site | S | |
| ✓ **Link to the source code** from the About page and footer (the repository is public and MIT-licensed) | S | Done |

### B2. Added on 11 October

| Item | Effort | Notes |
|---|---|---|
| ✓ **Election results and majorities**: each MP's majority when they spoke and now; marginal and safe seats; first-term MPs | M | Done |
| ✓ **Beta label** on every page, and an **Other resources** page crediting other sites and what each does best | S | Done |

### C. New ideas

**Finding and following positions**
| Item | Effort | What it gives |
|---|---|---|
| **Timeline view**: one person's or party's statements on a topic in date order, with votes in between | M | Shows how positions developed, without the site judging consistency |
| **Bill pages**: each bill's debates by stage (second reading, committee, report, Lords) with a briefing per stage | M | The data already includes bill names and committee debates |
| ✓ **Debate pages**: "what was said in this debate", one briefing per debate | S–M | Done: every debate since 2010 readable in full on the site, with each speaker as they were on the day, its votes and an "Ask about this debate" box. Linked from sources, timelines, member and bill pages. A ready-made briefing per debate is still to do |
| ✓ **"Ask about this"** in the source panel: a follow-up question about one speech or speaker | S | Done |
| ✓ **Sources only** button: show the balanced evidence set without writing a briefing | S | Done |
| ✓ **Weekly "In Parliament this week"** page, generated automatically | S–M | Done, free (no AI): each sitting day's debates, statements and questions, every vote with its kind, written statements, and an archive of past weeks. An AI-written summary could be added for a few dollars a week |

**Sharing and reuse**
| Item | Effort | What it gives |
|---|---|---|
| ✓ **Download as PDF or Word** button (print already works) | S | Done: Word files are built in the browser, with numbered citations and the full source list |
| ✓ **Embeddable briefing card** for journalists and bloggers | S–M | Done: "Copy embed code" gives the briefing's preview card linked back to it (an image and link, so the site's protection against being framed stays in place) |
| ✓ **RSS feeds** for topic briefings, the changelog and corrections | S | Done, plus a feed for each member and for bills |
| ✓ **Featured briefings**: a few good briefings chosen by you, indexable by search engines | S | Done: "Feature" on the admin page; listed on /topics |

**Quality and trust**
| Item | Effort | What it gives |
|---|---|---|
| ✓ **Balance warning**: a note when the evidence is dominated by one party or group | S | Done |
| **Fill in missing dates of birth** (about 5% of members since 2010) from other sources, with a small corrections file | S | More complete age groupings |
| ✓ **Glossary page** of parliamentary terms (division, Westminster Hall, urgent question and so on), linked from the source panel | S | Done: /glossary, linked from every vote label and the footer |
| **Accessibility testing with real users** (screen reader and keyboard users) | M | Automated checks only catch some problems |
| **Automatic accessibility check in CI**, so new pages stay accessible | S | |

**Running the site**
| Item | Effort | What it gives |
|---|---|---|
| ✓ **Prompt caching** for the briefing instructions | S | Done: reading a question costs about 78% less on a repeat |
| ✓ **Keep briefings longer**: a week instead of 24 hours | S | Done |
| ✓ **Failed-briefing log and alerts** on the admin page (and by email, once an email service exists) | S | Admin page done; email still to do |
| ✓ **Spending alerts**: a warning on the admin page at 50% and 80% of the monthly cap | S | Done |
| ✓ **Popular questions** (counts only, no visitor details) on the admin page | S | Done |
| ✓ **One-command update** script on the server (pull, rebuild, health check) | S | Done: `deploy/update.sh` |

### D. Gaps raised in the Gemini review, and procedural explanations

What the review suggested, what the site already does, what is missing, and how long each piece would take.

**Explaining votes properly (procedural explanations)**

Already done: the source panel explains what a division is, and rebellions are counted against each party's majority
on the day, so a free vote shows up as a party splitting. Not yet done: telling the reader *what kind of vote* it was.
A vote against a "reasoned amendment" or a programme motion says little about someone's view of the policy, and the
briefing should not imply that it does.

| Item | Time | Notes |
|---|---|---|
| ✓ **Name the type of each vote** from its title: second or third reading, reasoned amendment, programme motion, Lords amendments ("ping-pong"), opposition day motion, ten minute rule bill, closure, statutory instrument, money resolution | 1 day | Done: read from the motion before each division and the outcome after it; about 91% of divisions since 2010 get a kind. Shown on bill pages, member pages, timelines and in the source panel, and given to the briefing |
| ✓ **Plain-English note for each type** in the source panel, for example "a reasoned amendment sets out reasons to decline a bill's second reading; voting against it usually means supporting the bill going forward" | Half a day | Done: shown with each vote and listed in the glossary |
| ✓ **Briefing rule**: report what a procedural vote was about, never present it as a view on the policy itself; describe free votes as free votes | 2 hours | Done for procedural votes. Free votes cannot yet be told apart in the record (see whipping information) |
| **Whipping information** (whether a vote was whipped, and how) where TheyWorkForYou Votes records it | 1–2 days | Their coverage is partial; shown only where recorded, with the source named |
| **Wrecking amendments** and similar labels | Not recommended | Calling an amendment "wrecking" is a political judgement. The site would only report it when a speaker in the debate says so, with the citation |

**Money, interests and influence (data interoperability)**

Already done: every speaker is identified by their parliamentary ID (never by name), with their party, offices,
committees and seat on the date. Nothing yet on interests, donations or groups. All of this needs care: putting a
donation next to a speech can suggest a link that is not there. Each item would show the declared facts and dates
side by side, and say plainly that being next to each other does not show that one caused the other. A short legal
review before launch is advised.

| Item | Time | Notes |
|---|---|---|
| **Register of Members' Financial Interests** on MP pages: declared jobs, gifts, donations, shareholdings, with dates | 2–3 days | Parliament publishes it as open data (Open Parliament Licence), linked by member ID. No AI cost |
| **Declared interests next to speeches**: flag where the speaker had a relevant declared interest on the day | 2 days, after the above | Deciding "relevant" needs care; start with exact category matches and show the register entry, not a judgement |
| **Electoral Commission donations** to MPs and their local parties | 2–3 days | Donations to individual MPs match by name and constituency, so each match needs a confidence check; ambiguous ones are left out |
| **All-Party Parliamentary Groups**: which groups a member belongs to and who funds the secretariat | 1–2 days | The register is published per edition; needs a small scraper |
| **Companies House**: directorships of members | 3–5 days | Matching by name is unreliable (many people share names). Only use where the member has declared the company in the register, then link to it. Needs a free API key |
| **Timeline of who said what, alongside declared interests and donations** | 2–3 days, after the above | The "co-occurrence" view. Highest risk of implying wrongdoing; would be opt-in on the MP page, never in briefings |

**Select committees (evidence and scrutiny)**

Already done: committee chairs and members are known on each date and boosted for matching subjects. Not covered:
what committees heard and recommended.

| Item | Time | Notes |
|---|---|---|
| **Committee pages**: inquiries, reports and the government's responses, with links | 2–3 days | Parliament's Committees API, open data. No AI cost |
| **Witness index**: who gave evidence to which inquiry, searchable by organisation | 2 days | From the same API. Shows which organisations are heard most |
| **Oral evidence transcripts in search and briefings** | 5–8 days | The large item in section A. Different format; witnesses are not members, so they need their own labels |
| **Plain-English summaries of evidence sessions** | 2 days, after the above | About $0.05–0.20 per session, written once and stored |
| **Recommendation tracking**: each report recommendation, whether the government accepted it, and what happened next | 2–3 weeks | Recommendations and responses are long documents; matching them needs AI and checking by a person. Best done for a few committees first, or in partnership with a research group |

**Devolved parliaments**

Already done: nations are a grouping for Westminster MPs. Not covered: the Scottish Parliament, the Senedd and the
Northern Ireland Assembly. TheyWorkForYou already publishes all three records in a similar format to the Westminster
data, which makes this much easier than starting from scratch.

| Item | Time | Notes |
|---|---|---|
| **Devolution notes**: when a question is about a devolved subject (health, education, most transport, and so on), say so in the briefing, and which nations' policy Westminster decides | 1 day | Curated table of reserved and devolved matters for each nation, kept up to date by hand. Useful now, before any devolved data is added |
| **Scottish Parliament** debates, questions and members | 4–6 days | Members, parties and offices from the same mySociety sources |
| **Senedd** | 4–6 days | Bilingual record; search would cover English and Welsh |
| **Northern Ireland Assembly** | 3–5 days | Includes the periods when the Assembly was not sitting |
| **One common format** for all four, so filters and groupings work the same way | Included above | The site's format is already general; mostly new labels (MSP, MS, MLA) and offices |
| **Cross-border comparison**: "how did Westminster, Holyrood and the Senedd debate the same issue?" | 2–3 days, after at least one devolved parliament | Builds on the comparisons feature |

---

## Suggested order

1. ✓ **Quick wins (S):** prompt caching, failed-briefing alerts, spending alerts, sources-only button, source code link,
   balance warning.
2. ✓ **Your MP** and **MP pages**: the most-asked-for features, and the base for the activity feed and voting
   summaries. Also done: election results and majorities, the beta label and the Other resources page.
3. ✓ **Test set**, then cheaper models and re-ranking: done, except the Opus/Sonnet briefing comparison and a
   citation tweak, which wait for API credit (see `docs/EVALUATION.md`).
4. ✓ **Topic briefings** and **featured briefings**: content to point people and search engines at.
5. **Charts, comparisons, bill pages, timelines.**
6. **More of the record**, starting with Early Day Motions.
7. **From section D**, quickest and most useful first: vote types and the procedural-vote rule (about 2 days),
   devolution notes (1 day), then the Register of Members' Financial Interests (2–3 days), committee pages and the
   witness index (4–5 days), then a devolved parliament (about a week each).
