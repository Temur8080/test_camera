# Toyxona agent — qisqa qo'llanma

To'liq ma'lumot: [../README.md](../README.md)

## Tez boshlash

```powershell
cd venue_agent
install_ffmpeg.bat
copy config.example.yaml config.yaml
notepad config.yaml
python agent.py
```

## config.yaml

```yaml
server_url: "http://VPS_IP:8080"
agent_id: "toyxona1"
agent_key: "VPS server/config.yaml dagi kalit"
rtsp_publish_host: "VPS_IP"
```

Kamera paroli **web sahifada** kiritiladi.

## .exe

```powershell
build_exe.bat
# dist\ papkani toyxona PC ga ko'chiring
dist\install_ffmpeg.bat
dist\venue_agent.exe
```

## Web

http://VPS_IP:8080 → login → kamera parol → video

## Muammolar

| Xato | Yechim |
|------|--------|
| ffmpeg topilmadi | install_ffmpeg.bat |
| Kamera topilmadi | PC va kamera bir LAN |
| 403 agent | agent_key mos emas |
