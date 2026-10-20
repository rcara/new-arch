#!/bin/sh
cd "$(dirname "$0")"
if [ -x .venv/bin/python ]; then
  exec .venv/bin/python launcher.py
else
  exec python3 launcher.py
fi
