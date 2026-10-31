#!/usr/bin/env bash
# Ship the backend to the Lightsail server and restart it. The app itself is served by Vercel (frontend/),
# so the server only runs the API and the scheduled refresh. Data on the server is never overwritten.
set -euo pipefail

HOST="${FINN_HOST:-ubuntu@15.206.124.235}"
KEY="${FINN_KEY:-$HOME/.ssh/finn-lightsail.pem}"
cd "$(dirname "$0")/.."

rsync -az --delete -e "ssh -i $KEY" \
  --include 'backend/***' --include 'deploy/***' --include 'tests/***' \
  --include 'pyproject.toml' --include 'uv.lock' --include '.python-version' --include 'requirements.txt' \
  --exclude '__pycache__' --exclude '*' \
  ./ "$HOST:~/finn/"
ssh -i "$KEY" "$HOST" 'cd ~/finn && ~/.local/bin/uv sync --frozen -q && sudo systemctl restart finn && sleep 2 && systemctl is-active finn'
