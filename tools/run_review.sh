#!/bin/zsh
# Loads the saved API key, confirms it works, then rebuilds the site data with
# Claude's photo review of the most promising listings. Usage:
#   zsh tools/run_review.sh OUT_DIR [LIMIT]
set -e
source ~/.zshrc 2>/dev/null || true
cd "${0:A:h}/.."
.venv/bin/python -m airbnb_access check-key
.venv/bin/python -m airbnb_access web-export --regions all --out "$1" --claude-limit "${2:-500}" --pages --reviews reviews/reviews.json
