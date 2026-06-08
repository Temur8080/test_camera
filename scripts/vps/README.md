# Kamera Cloud — Git + systemd (Docker yo'q)

## VPS da birinchi marta

```bash
git clone https://github.com/SIZNING/repo.git /opt/kamera-cloud
cd /opt/kamera-cloud
sudo bash scripts/vps/install.sh
bash scripts/vps/test.sh
```

`install.sh`:
- Python venv + server deps
- MediaMTX + go2rtc binary yuklaydi (`bin/`)
- `server/config.yaml` yaratadi
- systemd xizmatlarini yoqadi

## Kod yangilash (deploy)

```bash
cd /opt/kamera-cloud
sudo bash scripts/vps/update.sh
```

Bu `git pull` + pip + `systemctl restart` qiladi.

## Xizmatlar

```bash
systemctl status mediamtx go2rtc kamera-cloud
journalctl -u kamera-cloud -f
```

## Portlar

| Port | Xizmat |
|------|--------|
| 8080 | Web + API |
| 1984 | go2rtc |
| 8554 | MediaMTX (agent RTSP) |

## Sozlama

`server/config.yaml` — web login, agent kalitlari, public IP.

`INSTALL_DIR` o'zgartirish: `INSTALL_DIR=/home/app/kamera sudo bash scripts/vps/install.sh`
