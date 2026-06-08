"""
Toyxona agent: kameralarni topadi, ro'yxatni VPS ga yuboradi.
Login/parol web sahifada kiritiladi — agent serverdan oladi va ffmpeg ishga tushiradi.
"""
from __future__ import annotations

import argparse
import ipaddress
import shutil
import socket
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urlparse

import requests
import yaml

WS_DISCOVERY_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{message_id}</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>
"""

def app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


BASE_DIR = app_dir()
CONFIG_PATH = BASE_DIR / "config.yaml"
FFMPEG_BIN = "ffmpeg"
FFMPEG_PROCS: Dict[str, subprocess.Popen] = {}


def find_ffmpeg() -> Optional[str]:
    candidates = [
        BASE_DIR / "ffmpeg" / "bin" / "ffmpeg.exe",
        BASE_DIR / "ffmpeg.exe",
    ]
    for path in candidates:
        if path.is_file():
            return str(path)
    found = shutil.which("ffmpeg")
    return found


def require_ffmpeg() -> str:
    global FFMPEG_BIN
    ff = find_ffmpeg()
    if not ff:
        print("ffmpeg topilmadi!")
        print(f"  1) {BASE_DIR}\\install_ffmpeg.bat ishga tushiring")
        print(f"  2) yoki ffmpeg.exe ni shu papkaga qo'ying: {BASE_DIR}")
        sys.exit(1)
    FFMPEG_BIN = ff
    return ff


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        print(f"config.yaml yo'q: {CONFIG_PATH}")
        print("config.example.yaml dan nusxa oling.")
        sys.exit(1)
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def headers(cfg: dict) -> dict:
    return {"X-Agent-Key": cfg["agent_key"], "Content-Type": "application/json"}


def probe_onvif(timeout: float) -> List[str]:
    message = WS_DISCOVERY_TEMPLATE.format(message_id=uuid.uuid4())
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    sock.settimeout(timeout)
    discovered: Set[str] = set()
    try:
        sock.sendto(message.encode("utf-8"), ("239.255.255.250", 3702))
        while True:
            packet, _ = sock.recvfrom(65535)
            discovered.update(parse_xaddrs(packet))
    except socket.timeout:
        pass
    finally:
        sock.close()
    return sorted(discovered)


def parse_xaddrs(packet: bytes) -> Set[str]:
    result: Set[str] = set()
    try:
        root = ET.fromstring(packet.decode("utf-8", errors="ignore"))
    except ET.ParseError:
        return result
    for elem in root.iter():
        if elem.tag.endswith("XAddrs") and elem.text:
            for url in elem.text.split():
                result.add(url.strip())
    return result


def get_local_ip() -> Optional[str]:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def default_subnet() -> str:
    local_ip = get_local_ip()
    if not local_ip:
        return "192.168.1.0/24"
    return str(ipaddress.ip_network(f"{local_ip}/24", strict=False))


def is_port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def probe_onvif_http(host: str, timeout: float = 1.5) -> Optional[str]:
    for url in (
        f"http://{host}/onvif/device_service",
        f"http://{host}:80/onvif/device_service",
    ):
        try:
            r = requests.get(url, timeout=timeout)
            if r.status_code in (200, 400, 401):
                return url
        except requests.RequestException:
            continue
    return None


def scan_single_host(host: str, timeout: float) -> Optional[str]:
    if not is_port_open(host, 554, timeout=timeout):
        return None
    return probe_onvif_http(host, timeout=max(1.0, timeout)) or f"http://{host}/onvif/device_service"


def fallback_scan_subnet(subnet: str, workers: int = 64, timeout: float = 0.5) -> List[str]:
    hosts = [str(ip) for ip in ipaddress.ip_network(subnet, strict=False).hosts()]
    results: Set[str] = set()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(scan_single_host, h, timeout): h for h in hosts}
        for fut in as_completed(futs):
            x = fut.result()
            if x:
                results.add(x)
    return sorted(results)


def discover_cameras(cfg: dict) -> List[str]:
    timeout = float(cfg.get("scan_timeout", 3.0))
    print("Kameralarni qidiryapman...")
    xaddrs = probe_onvif(timeout=timeout)
    if not xaddrs:
        subnet = cfg.get("subnet") or default_subnet()
        print(f"Multicast bo'sh. Subnet scan: {subnet}")
        xaddrs = fallback_scan_subnet(subnet, timeout=0.5)
    return xaddrs


def register_server(cfg: dict, xaddrs: List[str]) -> dict:
    cameras = []
    for idx, xaddr in enumerate(xaddrs, start=1):
        host = urlparse(xaddr).hostname or f"cam{idx}"
        cameras.append(
            {
                "name": f"Kamera {host}",
                "host": host,
                "onvif_xaddr": xaddr,
            }
        )
    payload = {
        "agent_id": cfg["agent_id"],
        "venue_name": cfg.get("venue_name", cfg["agent_id"]),
        "cameras": cameras,
    }
    url = cfg["server_url"].rstrip("/") + "/api/agent/register"
    r = requests.post(url, json=payload, headers=headers(cfg), timeout=30)
    r.raise_for_status()
    return r.json()


def fetch_streams(cfg: dict) -> List[dict]:
    url = (
        cfg["server_url"].rstrip("/")
        + f"/api/agent/streams?agent_id={cfg['agent_id']}"
    )
    r = requests.get(url, headers={"X-Agent-Key": cfg["agent_key"]}, timeout=15)
    r.raise_for_status()
    return r.json().get("streams", [])


def ffmpeg_output_args(cfg: dict) -> List[str]:
    """Hikvision timestamp ogohlantirishlari — copy yoki transcode."""
    if cfg.get("ffmpeg_transcode"):
        return [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-tune",
            "zerolatency",
            "-g",
            "25",
            "-pix_fmt",
            "yuv420p",
            "-an",
        ]
    return ["-c:v", "copy", "-an"]


def start_ffmpeg(cfg: dict, stream_id: str, src: str, dst: str) -> None:
    cmd = [
        FFMPEG_BIN,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error" if cfg.get("ffmpeg_quiet") else "warning",
        "-rtsp_transport",
        "tcp",
        "-fflags",
        "+genpts+igndts",
        "-use_wallclock_as_timestamps",
        "1",
        "-i",
        src,
        *ffmpeg_output_args(cfg),
        "-f",
        "rtsp",
        "-rtsp_transport",
        "tcp",
        dst,
    ]
    mode = "transcode" if cfg.get("ffmpeg_transcode") else "copy"
    print(f"Push ({mode}): {stream_id} -> {dst}")
    if not cfg.get("ffmpeg_quiet"):
        print("  (timestamp ogohlantirishlari odatda xato emas — video ishlasa OK)")
    FFMPEG_PROCS[stream_id] = subprocess.Popen(cmd)


def stop_stream(stream_id: str) -> None:
    proc = FFMPEG_PROCS.pop(stream_id, None)
    if not proc:
        return
    try:
        proc.terminate()
        proc.wait(timeout=3)
    except Exception:
        proc.kill()


def stop_all_ffmpeg() -> None:
    for sid in list(FFMPEG_PROCS):
        stop_stream(sid)


def sync_streams(cfg: dict) -> None:
    try:
        streams = fetch_streams(cfg)
    except requests.RequestException as exc:
        print(f"Stream ro'yxati xato: {exc}")
        return

    active = set(FFMPEG_PROCS)
    wanted = {s["stream_id"]: s for s in streams}

    for sid in active - wanted.keys():
        print(f"To'xtatildi: {sid}")
        stop_stream(sid)

    for sid, info in wanted.items():
        dst = info.get("publish_url") or ""
        src = info.get("rtsp_url") or ""
        if not src or not dst:
            continue
        proc = FFMPEG_PROCS.get(sid)
        if proc and proc.poll() is None:
            continue
        if proc:
            stop_stream(sid)
        start_ffmpeg(cfg, sid, src, dst)


def active_stream_ids() -> List[str]:
    alive = []
    for sid, proc in list(FFMPEG_PROCS.items()):
        if proc.poll() is None:
            alive.append(sid)
        else:
            print(f"ffmpeg to'xtadi: {sid}, qayta ishga tushiriladi")
            FFMPEG_PROCS.pop(sid, None)
    return alive


def post_heartbeat(cfg: dict) -> None:
    url = cfg["server_url"].rstrip("/") + f"/api/agent/heartbeat?agent_id={cfg['agent_id']}"
    payload = {"active_streams": active_stream_ids()}
    requests.post(
        url,
        json=payload,
        headers=headers(cfg),
        timeout=10,
    )


def agent_loop(cfg: dict) -> None:
    interval = int(cfg.get("sync_interval", 10))
    while True:
        try:
            post_heartbeat(cfg)
        except requests.RequestException as exc:
            print(f"Heartbeat xato: {exc}")
        sync_streams(cfg)
        time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description="Toyxona kamera agent")
    parser.add_argument("--scan-only", action="store_true", help="Faqat qidirish")
    args = parser.parse_args()
    cfg = load_config()
    print(f"ffmpeg: {require_ffmpeg()}")

    xaddrs = discover_cameras(cfg)
    if not xaddrs:
        print("Kamera topilmadi.")
        sys.exit(1)
    print(f"Topildi: {len(xaddrs)} ta kamera")
    for i, x in enumerate(xaddrs, 1):
        print(f"  [{i}] {x}")

    if args.scan_only:
        return

    reg = register_server(cfg, xaddrs)
    print("Server javobi:", reg)
    print("\nWeb sahifada har kamera uchun login/parol kiriting:")
    print(cfg["server_url"])
    print("\nAgent ishlayapti. To'xtatish: Ctrl+C")
    try:
        agent_loop(cfg)
    except KeyboardInterrupt:
        print("\nTo'xtatilmoqda...")
        stop_all_ffmpeg()


if __name__ == "__main__":
    main()
