#!/usr/bin/env bash
# Install the latest version of Where They Stand (whatever has been merged into `main` on GitHub).
# Run on the server, as root:
#   bash /opt/hansardgpt/deploy/update.sh
# It fetches the new code, rebuilds and restarts the site (a few seconds of downtime), refreshes the timers,
# clears out old build files, and finishes with the health check.
set -euo pipefail
DIR="${DIR:-/opt/hansardgpt}"

echo "==> Fetching the latest version"
caddy_before=$(sha1sum "$DIR/deploy/Caddyfile" | cut -d' ' -f1)
git -C "$DIR" pull --ff-only

cd "$DIR/deploy"
echo "==> Refreshing the update and backup timers"
cp hansard-sync.service hansard-sync.timer hansard-backup.service hansard-backup.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hansard-sync.timer hansard-backup.timer >/dev/null

echo "==> Making sure the server has swap space (spare memory on disk for large updates)"
bash "$DIR/deploy/swap.sh" || echo "WARNING: could not add swap; carrying on."

echo "==> Rebuilding and restarting the site"
docker compose up -d --build
if [[ "$(sha1sum Caddyfile | cut -d' ' -f1)" != "$caddy_before" ]]; then
  echo "==> The web server's settings changed: restarting it"
  docker compose up -d --force-recreate --no-deps caddy  # a file mounted into the container is re-read only on a fresh start
fi

echo "==> Clearing out old build files"
docker image prune -f >/dev/null

echo "==> Checking everything is working"
sleep 10
bash "$DIR/deploy/check.sh"
