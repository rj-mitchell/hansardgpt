# Putting Where They Stand online (Hostkey, London)

This guide takes you from nothing to a live site at **wheretheystand.uk**, step by step. It is written for a
Hostkey virtual server in London, but works the same on any provider's Ubuntu 24.04 server. Allow about an hour,
most of it waiting for the Hansard data to load.

You will need:
- the three domains registered: wheretheystand.uk, wheretheystand.co.uk and wheretheystand.org.uk;
- your Anthropic API key;
- the code merged into the `main` branch on GitHub, and the repository public. (If you want to keep it private,
  ask for the private-repository steps instead of step 5.)

---

## 1. Make an SSH key (once, on your own computer)

An SSH key lets you log in to the server securely without a password.

**Windows:** open *Terminal* (or PowerShell) and run:

```
ssh-keygen -t ed25519
```

Press Return at each question (a passphrase is optional but recommended). Then show the public half of the key:

```
type $env:USERPROFILE\.ssh\id_ed25519.pub
```

**Mac:** the same `ssh-keygen` command in *Terminal*, then `cat ~/.ssh/id_ed25519.pub`.

Copy the whole line it prints (it starts `ssh-ed25519`). This public half is safe to share; never share the file
without `.pub`.

## 2. Order the server

On Hostkey, choose the **v3-medium** virtual server (8 vCPU, 16 GB RAM, 160 GB NVMe), with:
- **Location:** London (United Kingdom);
- **Operating system:** Ubuntu 24.04 LTS, the plain image: no control panel, no Portainer or ISPmanager;
- **SSH key:** paste the line from step 1.

When it is ready, Hostkey shows the server's **IP address** (four numbers, such as 203.0.113.25). Note it down.

## 3. Point the domains at the server

At the company where you registered the domains, open each domain's **DNS settings** and add these records,
using your server's IP address. Remove any existing "parking" A records first.

| Domain | Type | Name / host | Value |
|---|---|---|---|
| wheretheystand.uk | A | `@` | your server's IP |
| wheretheystand.uk | A | `www` | your server's IP |
| wheretheystand.co.uk | A | `@` | your server's IP |
| wheretheystand.co.uk | A | `www` | your server's IP |
| wheretheystand.org.uk | A | `@` | your server's IP |
| wheretheystand.org.uk | A | `www` | your server's IP |

Changes usually take effect within an hour. To check, run `nslookup wheretheystand.uk` on your computer: it
should print your server's IP address. Wait until it does before step 5, so that the HTTPS certificates can be
issued.

## 4. Log in to the server

On your computer:

```
ssh root@YOUR.SERVER.IP
```

Type `yes` the first time it asks whether to trust the server. You are now typing commands on the server.

## 5. Run the setup script

Still on the server, run:

```
curl -fsSL https://raw.githubusercontent.com/rj-mitchell/hansardgpt/main/deploy/provision.sh -o provision.sh
sudo bash provision.sh
```

It asks three questions:
1. **Main domain name:** `wheretheystand.uk`
2. **Other domain names to redirect:** `wheretheystand.co.uk wheretheystand.org.uk` (the `www` versions are added
   automatically).
3. **Anthropic API key:** paste it. Nothing appears as you paste; that is deliberate. Press Return.

The script then:
- installs Docker, turns on automatic security updates, and sets up a firewall that allows only SSH and the web;
- builds and starts the site, with HTTPS certificates obtained automatically;
- starts loading Hansard since 2010 in the background (30–60 minutes);
- sets up the twice-daily update.

At the end it prints a command for checking usage and spend. Keep it somewhere safe; it contains your admin
token.

## 6. Watch the first data load

```
tail -f /var/log/hansard-bootstrap.log
```

Press Ctrl+C to stop watching (the load carries on). When it finishes, open **https://wheretheystand.uk**.
Searching works as soon as the load completes. Meaning-based matching is then built in the background during
each twice-daily update, newest records first; on 8 cores the whole archive takes roughly a day. The
[status page](https://wheretheystand.uk/status) shows its progress.

---

## Day to day

The easiest way to keep an eye on the site is the admin page, **https://wheretheystand.uk/admin**. Paste your
admin token (below) to see spending, reports from readers, feedback, visits, recent briefings and update
history. You can close reports there (adding a public note for the [corrections page](https://wheretheystand.uk/corrections)
if something was put right) and withdraw a briefing. A withdrawal reason is shown publicly.

| To… | Run on the server |
|---|---|
| See usage, spend, visits and feedback | the admin page, or the `curl` command printed at the end of setup |
| See the update history | `curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" https://wheretheystand.uk/api/admin/sync` |
| Install a new version of the site | `cd /opt/hansardgpt && git pull && cd deploy && docker compose up -d --build` |
| Restart the site | `cd /opt/hansardgpt/deploy && docker compose restart` |
| Change the API key | edit `/opt/hansardgpt/deploy/.env`, then `docker compose up -d` in the same folder |
| Show the "Support this site" link | add `HANSARD_DONATE_URL=https://ko-fi.com/yourname` to `/opt/hansardgpt/deploy/.env`, then `docker compose up -d` in the same folder |
| List recent briefings | `curl -H "Authorization: Bearer YOUR_ADMIN_TOKEN" https://wheretheystand.uk/api/admin/briefings` |
| Withdraw a briefing (after a complaint, say) | `curl -X POST -H "Authorization: Bearer YOUR_ADMIN_TOKEN" -H "Content-Type: application/json" -d '{"reason": "complaint about attribution"}' https://wheretheystand.uk/api/admin/briefings/THE_ID/withdraw` |

Your admin token is in `/opt/hansardgpt/deploy/.env` (`HANSARD_ADMIN_TOKEN=`).

## Backups

Everything can be rebuilt from public sources except one file: the saved briefings, usage records, feedback and
visit counts. Turn on Hostkey's snapshot backups if offered, or ask for the nightly off-site copy to
be set up.

## Spending limits

The defaults are 15 new briefings per visitor a day, and $10 a day and $150 a month for the whole site. To change
them, edit the `[usage]` section of `config/settings.toml`, then install it as a new version (see the table).
