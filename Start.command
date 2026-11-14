#!/bin/zsh
set -e
cd -- "${0:A:h}"
exec "${SHARP_PYTHON:-.sharp/venv/bin/python}" -u world/serve.py
