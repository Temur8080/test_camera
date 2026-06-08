@echo off
REM Toyxona agent .exe yig'ish
cd /d %~dp0

echo === Kutubxonalar ===
pip install pyinstaller requests pyyaml

echo === .exe yig'ilmoqda ===
python -m PyInstaller --onefile --console --name venue_agent --clean agent.py
if errorlevel 1 (
  echo Xato: pyinstaller muvaffaqiyatsiz
  pause
  exit /b 1
)

echo === config nusxalash ===
if exist config.yaml (
  copy /Y config.yaml dist\config.yaml
) else (
  copy /Y config.example.yaml dist\config.yaml
  echo DIQQAT: dist\config.yaml ni tahrirlang - server_url va agent_key
)
copy /Y config.example.yaml dist\config.example.yaml
copy /Y install_ffmpeg.bat dist\install_ffmpeg.bat
copy /Y install_ffmpeg.ps1 dist\install_ffmpeg.ps1

echo.
echo ========================================
echo TAYYOR: dist\venue_agent.exe
echo         dist\config.yaml
echo ========================================
echo.
echo Ishga tushirish: dist\venue_agent.exe
echo Kerak: ffmpeg PATH da (winget install Gyan.FFmpeg)
echo.
pause
