#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

PY=python3
command -v $PY >/dev/null 2>&1 || { echo '[ERROR] python3 not found'; exit 1; }

if ! $PY -c 'import webview' >/dev/null 2>&1; then
    echo '[SETUP] installing pywebview (first run only)...'
    $PY -m pip install -r requirements.txt
fi

exec $PY app.py "$@"
