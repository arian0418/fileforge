#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
g++ -std=c++17 -O2 fileforge.cpp -o fileforge
exec python3 fileforge_desktop.py
