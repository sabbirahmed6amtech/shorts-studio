#!/usr/bin/env bash
# Start Shorts Studio on Mac or Linux. The first run sets everything up.
set -e
cd "$(dirname "$0")"

if [ ! -x .venv/bin/python ]; then
  echo "First run: setting up Shorts Studio. This takes a few minutes..."
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 .venv
  else
    PY=""
    for c in python3.12 python3.11 python3.13 python3; do
      if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)'; then
        PY="$c"; break
      fi
    done
    if [ -z "$PY" ]; then
      echo
      echo "Python 3.11 or 3.12 is needed (this Mac has $(python3 --version 2>&1 || echo none))."
      echo "Install it with:  brew install python@3.12   (or from python.org), then run ./start.sh again."
      exit 1
    fi
    "$PY" -m venv .venv
  fi
fi

# Install packages on the first run, and again whenever requirements.txt changes.
if ! cmp -s requirements.txt .venv/.installed-requirements; then
  echo "Installing packages..."
  if command -v uv >/dev/null 2>&1; then
    uv pip install --python .venv/bin/python -r requirements.txt
  else
    .venv/bin/python -m pip install --upgrade pip
    .venv/bin/python -m pip install -r requirements.txt
  fi
  cp requirements.txt .venv/.installed-requirements
fi

exec .venv/bin/python app.py
