# Where They Stand: to-do list and roadmap

Last updated 11 October 2026, the day the site went live.

**Effort:** S = a few hours · M = a day or two · L = several days or more. Running costs are for the
Anthropic API unless stated.

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
| **Your MP**: enter a postcode to see your MP, ask about them, see what they've said on a topic and their votes | M | Uses the ONS postcode directory or postcodes.io. No AI cost to look up |
| **Comparisons**: two MPs, parties or nations side by side on the same question | M | Costs the same as one or two briefings |
| **Charts**: how much a subject was debated over time, by party, House and nation | M | No AI cost. Must show context with every number (the lesson from the NZ site's expenses) |
| **Topic briefings**: regularly refreshed briefings on the issues in the news, on permanent pages | S–M | About $5 to start, then a few dollars a month. Also brings in search-engine traffic |
| **1997–2010** records | M–L | Needs the older boundary sets; disk use roughly doubles |
| **Early Day Motions**: who signed which motions | M | Good cross-party evidence of support |
| **Select committee evidence and reports** | L | Different source and format |
| **Scottish Parliament, Senedd, Northern Ireland Assembly** | L each | Each has its own record and member data |

### B. Discussed earlier, not yet built

| Item | Effort | Notes |
|---|---|---|
| **MP and peer pages**: roles over time, seats, recent contributions, voting record, briefings asked about them | M | No photos (licensing), or Parliament's official portraits only |
| **Recent-activity feed** on each MP page ("spoke in…", "voted against their party on…") | S, after MP pages | |
| **Voting record summaries** per member and topic, with the method shown in full | M | Context next to every number |
| **Test set of 50–100 questions with scoring** | M | About $3–5 per run. The foundation for the next two items |
| **Cheaper models where they are just as good** (for example, a smaller model for reading the question) | S, after the test set | Lowers running costs |
| **Re-ranking step** for sharper choice of sources | M | Judged with the test set |
| **Public search API** for researchers (search only, no AI briefings), documented and rate-limited | M | |
| **Topic alerts by email** (a weekly digest on chosen topics) | M–L | Needs an email-sending service and a sign-up with consent |
| **Cloudflare protection** (proxy on) | S–M | Make the server trust Cloudflare's visitor details, choose the right certificate setting, update the privacy notice |
| **Off-site backups** sent automatically to cheap storage | S | Needs a storage account from you (for example Backblaze B2) |
| **Contact and press page**: a short media pack, logo files, how to cite the site | S | |
| **Link to the source code** from the About page and footer (the repository is public and MIT-licensed) | S | Strong evidence of no hidden agenda |

### C. New ideas

**Finding and following positions**
| Item | Effort | What it gives |
|---|---|---|
| **Timeline view**: one person's or party's statements on a topic in date order, with votes in between | M | Shows how positions developed, without the site judging consistency |
| **Bill pages**: each bill's debates by stage (second reading, committee, report, Lords) with a briefing per stage | M | The data already includes bill names and committee debates |
| **Debate pages**: "what was said in this debate", one briefing per debate | S–M | Useful for "what happened yesterday" questions |
| **"Ask about this"** in the source panel: a follow-up question about one speech or speaker | S | |
| **Sources only** button: show the balanced evidence set without writing a briefing | S | Free to run; useful when the daily limit is reached |
| **Weekly "In Parliament this week"** page, generated automatically | S–M | A few dollars a week; regular fresh content |

**Sharing and reuse**
| Item | Effort | What it gives |
|---|---|---|
| **Download as PDF or Word** button (print already works) | S | For briefing packs and meetings |
| **Embeddable briefing card** for journalists and bloggers | S–M | Spreads the site with a link back |
| **RSS feeds** for topic briefings, the changelog and corrections | S | |
| **Featured briefings** page: a few good briefings chosen by you, indexable by search engines | S | Discovery and search traffic (saved briefings are hidden from search engines by default) |

**Quality and trust**
| Item | Effort | What it gives |
|---|---|---|
| **Balance warning**: a note when the evidence is dominated by one party or group | S | Readers see the limits at a glance |
| **Fill in missing dates of birth** (about 5% of members since 2010) from other sources, with a small corrections file | S | More complete age groupings |
| **Glossary page** of parliamentary terms (division, Westminster Hall, urgent question and so on), linked from the source panel | S | |
| **Accessibility testing with real users** (screen reader and keyboard users) | M | Automated checks only catch some problems |
| **Automatic accessibility check in CI**, so new pages stay accessible | S | |

**Running the site**
| Item | Effort | What it gives |
|---|---|---|
| **Prompt caching** for the briefing instructions | S | Cuts the cost of each briefing |
| **Keep briefings until the next data update** instead of 24 hours | S | Fewer repeat costs on popular questions |
| **Failed-briefing log and alerts** on the admin page (and by email, once an email service exists) | S | You'd have spotted the API key problem straight away |
| **Spending alerts**: a warning on the admin page at 50% and 80% of the monthly cap | S | |
| **Popular questions** (counts only, no visitor details) on the admin page | S | Shows what people want; feeds topic briefings |
| **One-command update** script on the server (pull, rebuild, health check) | S | Simpler than the three commands now |

---

## Suggested order

1. **Quick wins (S):** prompt caching, failed-briefing alerts, spending alerts, sources-only button, source code link,
   balance warning.
2. **Your MP** and **MP pages**: the most-asked-for features, and the base for the activity feed and voting
   summaries.
3. **Test set**, then cheaper models and re-ranking: lower costs and better briefings.
4. **Topic briefings** and **featured briefings**: content to point people and search engines at.
5. **Charts, comparisons, bill pages, timelines.**
6. **More of the record**, starting with Early Day Motions.
