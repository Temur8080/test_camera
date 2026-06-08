#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/kamera-cloud}"
HOST="${1:-127.0.0.1}"
USER="${TEST_USER:-admin}"
PASS="${TEST_PASS:-admin123}"

ok=0
fail=0

check() {
  local name="$1"
  shift
  if "$@"; then
    echo "[OK]   $name"
    ok=$((ok + 1))
  else
    echo "[FAIL] $name"
    fail=$((fail + 1))
  fi
}

echo "=== Kamera Cloud test (host=$HOST) ==="

check "mediamtx service" systemctl is-active --quiet mediamtx
check "go2rtc service" systemctl is-active --quiet go2rtc
check "kamera-cloud service" systemctl is-active --quiet kamera-cloud
check "Server health" curl -sf --max-time 5 "http://${HOST}:8080/api/health" | grep -q '"ok"'
check "go2rtc" curl -sf --max-time 5 "http://${HOST}:1984/" -o /dev/null

TOKEN=""
if resp=$(curl -sf --max-time 10 -X POST "http://${HOST}:8080/api/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" 2>/dev/null); then
  TOKEN=$(echo "$resp" | grep -o '"token":"[^"]*"' | cut -d'"' -f4)
fi
check "Login API" [[ -n "$TOKEN" ]]

echo ""
echo "Natija: $ok OK, $fail FAIL"
[[ $fail -eq 0 ]]
