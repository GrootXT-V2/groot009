#!/bin/bash
# Double-click this file in Finder to start the Groot desktop robot.
cd "$(dirname "$0")"

# Prefer a well-supported Python version (3.12 or 3.13)
PY=""
for candidate in python3.12 python3.13 /opt/homebrew/bin/python3.12 /opt/homebrew/bin/python3.13 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done

# Rebuild the environment if it was made with a Python that's too new
if [ -x .venv/bin/python ] && [ "$PY" != "python3" ] && \
   .venv/bin/python -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)'; then
  echo "Switching Groot to $PY..."
  rm -rf .venv
fi

if [ ! -d .venv ]; then
  echo "First-time setup with $PY..."
  "$PY" -m venv .venv
fi
# Install packages again whenever requirements.txt changes
if ! cmp -s requirements.txt .venv/installed-requirements.txt; then
  echo "Installing packages (this can take a few minutes)..."
  .venv/bin/pip install -q -r requirements.txt && cp requirements.txt .venv/installed-requirements.txt
fi
[ -f .env ] || cp .env.example .env
.venv/bin/python -u -m groot --gui
