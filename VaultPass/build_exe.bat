@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller --quiet
python -m PyInstaller --onefile --windowed --name VaultPass --clean main.py
echo.
echo Built: dist\VaultPass.exe
