@echo off
chcp 65001 >nul
title Cau noi Thanh Thanh
cd /d "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
  echo May nay chua cai Python. Hay cai tu python.org, nho tick "Add python.exe to PATH", roi bam lai file nay.
  start "" https://www.python.org/downloads/
  pause
  exit /b 1
)
python cau_noi.py
if errorlevel 1 pause
