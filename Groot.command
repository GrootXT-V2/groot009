#!/bin/bash
# Double-click this file in Finder to start the floating Groot bubble.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First-time setup..."
  python3 -m venv .venv && .venv/bin/pip install -q -r requirements.txt
fi
[ -f .env ] || cp .env.example .env
.venv/bin/python -m groot --gui
