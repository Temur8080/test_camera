#!/usr/bin/env bash
# Birinchi marta VPS o'rnatish (Git + systemd, Docker yo'q)
set -euo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/kamera-cloud}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

if [[ $EUID -ne 0 ]]; then
  echo "Root bilan: sudo bash scripts/vps/install.sh"
  exit 1
fi

echo "=== Kamera Cloud — Git install ==="
echo "Repo: $REPO_ROOT"
echo "Install: $INSTALL_DIR"

# Repo nusxasi
if [[ "$REPO_ROOT" != "$INSTALL_DIR" ]]; then
  if [[ ! -d "$INSTALL_DIR/.git" && ! -d "$INSTALL_DIR/server" ]]; then
    mkdir -p "$(dirname "$INSTALL_DIR")"
    echo "Nusxalanmoqda: $REPO_ROOT -> $INSTALL_DIR"
    mkdir -p "$INSTALL_DIR"
    cp -a "$REPO_ROOT/." "$INSTALL_DIR/"
  fi
  cd "$INSTALL_DIR"
else
  cd "$INSTALL_DIR"
fi

echo "=== Tizim paketlari ==="
apt-get update -qq
apt-get install -y python3 python3-venv python3-pip curl ca-certificates

echo "=== Python venv ==="
python3 -m venv venv
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r server/requirements.txt

echo "=== config.yaml ==="
if [[ ! -f server/config.yaml ]]; then
  cp server/config.example.yaml server/config.yaml
  PUBLIC_IP="${PUBLIC_IP:-$(curl -4 -s --max-time 5 ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')}"
  if [[ -n "$PUBLIC_IP" ]]; then
    sed -i "s/SIZNING_VPS_IP/$PUBLIC_IP/g" server/config.yaml
    echo "IP yozildi: $PUBLIC_IP"
  fi
  SECRET=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p)
  sed -i "s/O'ZGARTIRING_uzun_random_kalit/$SECRET/" server/config.yaml
  AGENT_KEY=$(openssl rand -hex 16 2>/dev/null || head -c 16 /dev/urandom | xxd -p)
  sed -i "s/AGENT_KALIT_1/$AGENT_KEY/" server/config.yaml
  echo "secret_key va agent_key yangilandi."
else
  echo "server/config.yaml mavjud — saqlab qolindi."
fi

echo "=== MediaMTX + go2rtc binary ==="
mkdir -p bin
ARCH="amd64"
case "$(uname -m)" in
  x86_64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) echo "Qo'llab-quvvatlanmaydigan arxitektura: $(uname -m)"; exit 1 ;;
esac

if [[ ! -x bin/mediamtx ]]; then
  MTX_URL=$(curl -sL "https://api.github.com/repos/bluenviron/mediamtx/releases/latest" \
    | grep -o "https://.*linux_${ARCH}.tar.gz" | head -1)
  curl -fsSL "$MTX_URL" -o /tmp/mediamtx.tar.gz
  tar -xzf /tmp/mediamtx.tar.gz -C /tmp
  MTX_BIN=$(find /tmp -maxdepth 2 -name mediamtx -type f | head -1)
  cp "$MTX_BIN" bin/mediamtx
  chmod +x bin/mediamtx
  rm -rf /tmp/mediamtx.tar.gz /tmp/mediamtx*
  echo "MediaMTX: bin/mediamtx"
fi

if [[ ! -x bin/go2rtc ]]; then
  G2_URL=$(curl -sL "https://api.github.com/repos/AlexxIT/go2rtc/releases/latest" \
    | grep -o "https://.*linux_${ARCH}" | head -1)
  curl -fsSL "$G2_URL" -o bin/go2rtc
  chmod +x bin/go2rtc
  echo "go2rtc: bin/go2rtc"
fi

echo "=== systemd ==="
for svc in mediamtx go2rtc kamera-cloud; do
  cp "scripts/vps/systemd/${svc}.service" "/etc/systemd/system/${svc}.service"
done
systemctl daemon-reload
systemctl enable mediamtx go2rtc kamera-cloud
systemctl restart mediamtx go2rtc kamera-cloud

echo "=== Firewall (ufw) ==="
if command -v ufw &>/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 8080/tcp comment "Kamera Cloud web" || true
  ufw allow 1984/tcp comment "go2rtc" || true
  ufw allow 8554/tcp comment "MediaMTX RTSP" || true
fi

PUBLIC_IP="${PUBLIC_IP:-$(grep public_host server/config.yaml | awk '{print $2}' | tr -d '"')}"
echo ""
echo "=========================================="
echo "TAYYOR: http://${PUBLIC_IP}:8080"
echo "go2rtc: http://${PUBLIC_IP}:1984"
echo "Tekshirish: bash scripts/vps/test.sh"
echo "Yangilash:  bash scripts/vps/update.sh"
echo "=========================================="
