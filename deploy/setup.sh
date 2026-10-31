#!/usr/bin/env bash
# One-time server setup on Ubuntu 24.04 (run as ubuntu, from ~/finn). Idempotent.
set -euo pipefail

if ! command -v caddy >/dev/null; then
  sudo apt-get install -y apt-transport-https curl gnupg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | sudo gpg --dearmor --yes -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  sudo apt-get update -q
  sudo apt-get install -y caddy sqlite3
fi

~/.local/bin/uv sync --frozen

sudo cp deploy/Caddyfile /etc/caddy/Caddyfile
sudo cp deploy/finn*.service deploy/finn*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now finn.service finn-filings.timer finn-eod.timer finn-screener.timer
sudo systemctl reload caddy || sudo systemctl restart caddy
systemctl --no-pager list-timers 'finn-*'
