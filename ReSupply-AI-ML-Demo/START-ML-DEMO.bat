@echo off
title ReSupply AI - ML Demo Ready
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" -MLDemo
if errorlevel 1 pause
