@echo off
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller --quiet
python -m PyInstaller --onefile --windowed --name VaultPass --clean ^
  --hidden-import uiautomation --hidden-import comtypes --hidden-import comtypes.client ^
  main.py
echo.
echo Built: dist\VaultPass.exe
