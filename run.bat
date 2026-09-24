@echo off
cd /d "%~dp0"
g++ -std=c++17 -O2 -municode fileforge.cpp -o fileforge.exe
if errorlevel 1 (
  echo Install a C++17 compiler such as MSYS2 MinGW-w64 and put g++ on PATH.
  pause
  exit /b 1
)
python fileforge_desktop.py
if errorlevel 1 pause
