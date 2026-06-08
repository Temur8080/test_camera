# Kamera Cloud

Masofadan toyxona kameralarini ko‘rish: **VPS (Git + systemd)** + **toyxona agent (.exe)** + **web panel**.

---

## Loyiha tahlili

### Maqsad

Toyxona Wi‑Fi/LAN dagi ONVIF kameralarni topish, VPS orqali internetdan real vaqtda ko‘rish.

### Arxitektura

```
[Toyxona kameralar] --RTSP--> [venue_agent + ffmpeg]
                                    |
                                    v (RTSP publish :8554)
                            [VPS: MediaMTX]
                                    |
                                    v
                            [VPS: go2rtc :1984]
                                    |
                                    v
                            [VPS: FastAPI :8080 + Web]
                                    |
                                    v
                            [Brauzer: login, kamera parol, video]
```

### Komponentlar

| Qism | Papka | Vazifa |
|------|-------|--------|
| **Server** | `server/` | JWT login, kamera ro‘yxati, agent API, go2rtc sync |
| **Agent** | `venue_agent/` | Kamera topish, VPS ga ro‘yxat, ffmpeg push |
| **VPS skriptlar** | `scripts/vps/` | Git deploy, systemd, MediaMTX/go2rtc config |

### Oqim

1. Agent kameralarni topadi → VPS ga **faqat ro‘yxat** (IP, nom)
2. Foydalanuvchi webda **kamera login/parol** kiritadi
3. Agent serverdan parol oladi → ffmpeg bilan VPS ga video yuboradi
4. Brauzer go2rtc orqali video ko‘rsatadi

### Olib tashlangan (keraksiz)

| O‘chirildi | Sabab |
|------------|--------|
| `deploy/ubuntu/` (Docker) | Git + systemd ishlatamiz |
| `camera_scanner.py` | Faqat lokal test; agent bilan dublikat |
| `remote_deploy.py` | SSH parol deploy; git pull yetarli |
| `go2rtc.yaml` (root) | Maxfiy ma’lumot + avtomatik yaratiladi |
| `README_VPS.md` | Bitta README ga birlashtirildi |
| `requirements.txt` (root) | Faqat `server/` va `venue_agent/` da |

---

## Papka tuzilishi

```
test_camera/
├── README.md                 # shu fayl
├── scripts/vps/              # VPS deploy (Git + systemd)
│   ├── install.sh            # birinchi o'rnatish
│   ├── update.sh             # git pull + restart
│   ├── test.sh               # tekshiruv
│   ├── mediamtx.yml
│   ├── go2rtc.yaml
│   └── systemd/
├── server/                   # VPS web + API
│   ├── app.py
│   ├── config.example.yaml
│   ├── requirements.txt
│   └── static/
└── venue_agent/              # toyxona PC
    ├── agent.py
    ├── config.example.yaml
    ├── build_exe.bat
    ├── install_ffmpeg.bat
    └── TOYXONA_AGENT.md
```

---

## 1. VPS o‘rnatish (Git)

```bash
git clone https://github.com/SIZNING/repo.git /opt/kamera-cloud
cd /opt/kamera-cloud
sudo bash scripts/vps/install.sh
bash scripts/vps/test.sh
```

Brauzer: `http://VPS_IP:8080`

Portlar: **8080**, **1984**, **8554**

Batafsil: [scripts/vps/README.md](scripts/vps/README.md)

### Kod yangilash (deploy)

```bash
cd /opt/kamera-cloud
sudo bash scripts/vps/update.sh
```

---

## 2. Toyxona PC (agent)

```powershell
cd venue_agent
install_ffmpeg.bat          # bir marta
copy config.example.yaml config.yaml
# server_url, agent_id, agent_key to'ldiring
python agent.py
```

Yoki `.exe`: `build_exe.bat` → `dist\venue_agent.exe`

Batafsil: [venue_agent/TOYXONA_AGENT.md](venue_agent/TOYXONA_AGENT.md)

---

## 3. Web foydalanish

1. `http://VPS_IP:8080` — sayt login
2. Kamera kartasi — **Parol kerak**
3. O‘ng panelda kamera login/parol kiriting
4. **Online** bo‘lgach video ochiladi

---

## 4. Sozlama

**VPS** — `server/config.yaml`:
- `users` — web login
- `agents` — har toyxona uchun `agent_id` + `agent_key`
- `public_host`, `go2rtc.public_url`, `mediamtx.rtsp_publish_host`

**Toyxona** — `venue_agent/config.yaml`:
- `server_url`, `agent_id`, `agent_key`, `rtsp_publish_host`
- Kamera paroli **kerak emas** (webda kiritiladi)

---

## 5. Xizmatlar (VPS)

```bash
systemctl status mediamtx go2rtc kamera-cloud
journalctl -u kamera-cloud -f
```

---

## 6. Muammolar

| Belgisi | Yechim |
|---------|--------|
| Kamera yo‘q | Agent ishlayaptimi? `agent_key` mosmi? |
| Parol panel yo‘q | Brauzer Ctrl+F5 |
| Video yo‘q | ffmpeg ishlayaptimi? 8554 ochiqmi? |
| DESCRIBE xato | Agent video yuborguncha kuting |

---

## 7. Xavfsizlik

- `config.yaml` ni gitga qo‘ymang
- Kuchli parollar, HTTPS (nginx) production uchun
- `agent_key` maxfiy saqlang
