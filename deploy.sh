#!/bin/bash
# Deploy the CSCC dashboard to Railway (no API keys required).
# First time: run "railway login" in your terminal and complete the browser sign-in.
set -e
cd "$(dirname "$0")"

if ! command -v railway &>/dev/null; then
  echo "Install Railway CLI: npm install -g @railway/cli"
  exit 1
fi

# Create/link project if needed (safe to run multiple times)
railway init --name cscc-dashboard 2>/dev/null || true

echo "Deploying to Railway..."
railway up

echo ""
echo "Done. Your dashboard URL will appear above (or run: railway open)."
