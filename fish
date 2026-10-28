#!/bin/sh
# Short form on Linux and macOS: ./fish, ./fish life, ./fish show, ./fish cottage ... (see README)
exec "$(dirname "$0")/.venv/bin/python" -m fish "$@"
