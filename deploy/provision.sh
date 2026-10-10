#!/usr/bin/env bash
# Provision Where They Stand on a fresh Ubuntu 24.04 server (run as root).
#
#   curl -fsSL https://raw.githubusercontent.com/rj-mitchell/hansardgpt/main/deploy/provision.sh | bash
#   (or copy this file to the server and run: sudo bash provision.sh)
#
# What it does:
#   1. installs Docker and git
#   2. clones the repository to /opt/hansardgpt
#   3. asks for your domain and Anthropic API key and writes deploy/.env
#   4. builds and starts the app behind Caddy (automatic HTTPS)
#   5. starts the one-off bootstrap in the background (downloads ~5 GB of Hansard
#      since 2010, ingests, indexes; embeddings continue in later syncs)
#   6. installs the twice-daily sync timer
# The site is public. An admin token (for /api/admin/usage and /api/admin/sync) is
# generated into deploy/.env. For an invite-only site instead, see the README.
set -euo pipefail

REPO="${REPO:-https://github.com/rj-mitchell/hansardgpt.git}"
BRANCH="${BRANCH:-main}"
DIR=/opt/hansardgpt

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (sudo)." >&2
  exit 1
fi

echo "==> Installing Docker and git"
apt-get update -y
apt-get install -y ca-certificates curl git openssl
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  . /etc/os-release
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu ${VERSION_CODENAME} stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -y
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi

echo "==> Fetching Where They Stand into $DIR"
if [[ -d $DIR/.git ]]; then
  git -C "$DIR" pull --ff-only
else
  git clone --branch "$BRANCH" "$REPO" "$DIR"
fi
cd "$DIR/deploy"

if [[ ! -f .env ]]; then
  read -rp "Main domain name pointing at this server (e.g. wheretheystand.uk): " DOMAIN
  read -rp "Other domain names that should redirect to it, space-separated (e.g. wheretheystand.co.uk wheretheystand.org.uk), or blank: " OTHERS
  REDIRECTS="www.$DOMAIN"
  for d in $OTHERS; do REDIRECTS="$REDIRECTS, $d, www.$d"; done
  read -rsp "Anthropic API key (leave blank for sources-only mode): " KEY
  echo
  umask 077
  printf 'DOMAIN=%s\nREDIRECT_DOMAINS="%s"\nHANSARD_ANTHROPIC_API_KEY=%s\nHANSARD_ADMIN_TOKEN=%s\n' \
    "$DOMAIN" "$REDIRECTS" "$KEY" "$(openssl rand -hex 24)" > .env
fi

echo "==> Building and starting"
docker compose up -d --build

echo "==> Starting the initial data load in the background (log: /var/log/hansard-bootstrap.log)"
nohup docker compose run --rm -T app hansard bootstrap --embed-minutes 120 > /var/log/hansard-bootstrap.log 2>&1 &

echo "==> Installing the sync timer"
cp hansard-sync.service hansard-sync.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hansard-sync.timer

cat <<MSG

Where They Stand is starting at https://$(grep ^DOMAIN= .env | cut -d= -f2)/
The first data load takes roughly 30-60 minutes (follow /var/log/hansard-bootstrap.log).
Semantic search improves as embeddings complete over the next syncs.

The site is open to everyone. Usage and spend:
  curl -H "Authorization: Bearer \$(grep ^HANSARD_ADMIN_TOKEN= $DIR/deploy/.env | cut -d= -f2)" \\
    https://$(grep ^DOMAIN= .env | cut -d= -f2)/api/admin/usage
MSG
