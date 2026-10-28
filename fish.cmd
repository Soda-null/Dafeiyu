@echo off
rem Short form on Windows: fish, fish life, fish show, fish cottage ... (see README)
set PYTHONUTF8=1
"%~dp0.venv\Scripts\python.exe" -m fish %*
