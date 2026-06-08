@echo off
cd /d %~dp0
echo ffmpeg o'rnatilmoqda (internet kerak)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_ffmpeg.ps1"
if errorlevel 1 (
  echo.
  echo PowerShell xato. Qo'lda yuklang:
  echo https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
  echo zip oching, bin\ffmpeg.exe ni papkaga nusxalang:
  echo   %~dp0ffmpeg\bin\ffmpeg.exe
  pause
  exit /b 1
)
echo.
echo Endi venue_agent.exe ishga tushiring.
pause
