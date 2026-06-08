#!/usr/bin/env bash
# Git pull + xizmatlarni qayta ishga tushirish
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/kamera-cloud}"
cd "$INSTALL_DIR"

echo "=== git pull ==="
if [[ -d .git ]]; then
  git pull --ff-only
else
  echo "Git repo emas — qo'lda nusxalangan. git init && git remote add origin URL"
fi

echo "=== Python deps ==="
venv/bin/pip install -q -r server/requirements.txt

echo "=== Restart ==="
systemctl restart mediamtx go2rtc kamera-cloud
systemctl is-active mediamtx go2rtc kamera-cloud

echo "Yangilandi."
