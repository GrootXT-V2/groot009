#!/bin/bash
# Double-click this file in Finder to start the Groot desktop robot.
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First-time setup..."
  python3 -m venv .venv
fi
# Install packages again whenever requirements.txt changes
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  echo "Installing packages..."
  .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/installed-requirements.txt
fi
[ -f .env ] || cp .env.example .env
.venv/bin/python -m groot --gui
