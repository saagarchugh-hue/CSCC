#!/bin/bash
# Deploy the CSCC dashboard to Railway (no API keys required).
# First time: run "railway login" in your terminal, then "railway init --name cscc-dashboard" once.
set -e
cd "$(dirname "$0")"

if ! command -v railway &>/dev/null; then
  echo "Install Railway CLI: npm install -g @railway/cli"
  exit 1
fi

if ! railway status &>/dev/null; then
  echo "No Railway project linked. Run once:"
  echo "  railway login"
  echo "  railway init --name cscc-dashboard"
  echo "Then run ./deploy.sh again."
  exit 1
fi

echo "Deploying to Railway..."
railway up

echo ""
echo "Done. Your dashboard URL will appear above (or run: railway open)."
