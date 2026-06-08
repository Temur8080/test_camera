"""
VPS server: login, kamera ro'yxati, agent registratsiya, go2rtc sync.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote, urlparse

import httpx
import yaml
from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from jose import JWTError, jwt
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config.yaml"
DB_PATH = BASE_DIR / "data.db"
STATIC_DIR = BASE_DIR / "static"

security = HTTPBearer(auto_error=False)

app = FastAPI(title="Kamera Cloud", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_config() -> Dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"config.yaml topilmadi: {CONFIG_PATH}")
    with CONFIG_PATH.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


CFG = load_config()
JWT_SECRET = CFG["server"]["secret_key"]
JWT_ALG = "HS256"
JWT_EXP_HOURS = 24
GO2RTC_API = CFG["go2rtc"]["api"].rstrip("/")
MTX_BASE = CFG["mediamtx"]["rtsp_publish_base"].rstrip("/")


# --- DB ---


def migrate_db(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(cameras)")}
    for col, typ in (
        ("host", "TEXT"),
        ("onvif_xaddr", "TEXT"),
        ("camera_user", "TEXT"),
        ("camera_password", "TEXT"),
        ("streaming", "INTEGER DEFAULT 0"),
    ):
        if col not in cols:
            conn.execute(f"ALTER TABLE cameras ADD COLUMN {col} {typ}")


def init_db() -> None:
    with db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                stream_id TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                host TEXT,
                onvif_xaddr TEXT,
                rtsp_local TEXT,
                camera_user TEXT,
                camera_password TEXT,
                online INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL,
                UNIQUE(agent_id, name)
            );
            CREATE TABLE IF NOT EXISTS agent_heartbeat (
                agent_id TEXT PRIMARY KEY,
                last_seen TEXT NOT NULL
            );
            """
        )
        migrate_db(conn)


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


init_db()


# --- Models ---


class LoginIn(BaseModel):
    username: str
    password: str


class CameraIn(BaseModel):
    name: str
    host: str
    onvif_xaddr: str = ""
    rtsp_url: str = ""  # eski agentlar uchun
    stream_suffix: str = "101"


class CameraCredentialsIn(BaseModel):
    username: str
    password: str
    channel: str = "101"


class AgentRegisterIn(BaseModel):
    agent_id: str
    venue_name: str = ""
    cameras: List[CameraIn] = Field(default_factory=list)


class AgentHeartbeatIn(BaseModel):
    active_streams: List[str] = Field(default_factory=list)


# --- Auth ---


def verify_user(username: str, password: str) -> bool:
    for u in CFG.get("users", []):
        if u["username"] == username and u["password"] == password:
            return True
    return False


def create_token(username: str) -> str:
    exp = datetime.now(timezone.utc) + timedelta(hours=JWT_EXP_HOURS)
    return jwt.encode({"sub": username, "exp": exp}, JWT_SECRET, algorithm=JWT_ALG)


def get_current_user(
    cred: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> str:
    if not cred:
        raise HTTPException(status_code=401, detail="Login kerak")
    try:
        payload = jwt.decode(cred.credentials, JWT_SECRET, algorithms=[JWT_ALG])
        return payload["sub"]
    except JWTError:
        raise HTTPException(status_code=401, detail="Token noto'g'ri")


def verify_agent_key(agent_id: str, key: str) -> bool:
    for a in CFG.get("agents", []):
        if a["agent_id"] == agent_id and a["agent_key"] == key:
            return True
    return False


# --- go2rtc ---


async def go2rtc_add_stream(stream_id: str, rtsp_src: str) -> None:
    """go2rtc ga stream qo'shish (VPS ichidagi MediaMTX RTSP)."""
    url = f"{GO2RTC_API}/api/streams"
    params = {"name": stream_id, "src": rtsp_src}
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.put(url, params=params)
        if r.status_code not in (200, 201):
            # Ba'zi versiyalarda POST
            r = await client.post(url, params=params)
        if r.status_code >= 400:
            raise HTTPException(502, f"go2rtc xato: {r.text}")


async def go2rtc_refresh_stream(stream_id: str) -> None:
    await go2rtc_remove_stream(stream_id)
    await go2rtc_add_stream(stream_id, go2rtc_src_url(stream_id))


async def go2rtc_remove_stream(stream_id: str) -> None:
    url = f"{GO2RTC_API}/api/streams"
    params = {"src": stream_id}
    async with httpx.AsyncClient(timeout=10.0) as client:
        await client.delete(url, params=params)


def mtx_rtsp_url(stream_id: str) -> str:
    return f"{MTX_BASE}/{stream_id}"


def go2rtc_src_url(stream_id: str) -> str:
    return f"{mtx_rtsp_url(stream_id)}#rtsp_transport=tcp"


def stream_id_for(agent_id: str, host: str) -> str:
    safe = host.replace(".", "_").replace(":", "_")
    return f"{agent_id}_{safe}"


def build_rtsp_url(host: str, user: str, password: str, channel: str = "101") -> str:
    u = quote(user, safe="")
    p = quote(password, safe="")
    return f"rtsp://{u}:{p}@{host}:554/Streaming/Channels/{channel}"


def agent_is_online(last_seen: Optional[str], now: datetime) -> bool:
    if not last_seen:
        return False
    try:
        seen = datetime.fromisoformat(last_seen)
        return (now - seen).total_seconds() <= 90
    except ValueError:
        return False


def camera_row_dict(r: sqlite3.Row, agent_online: bool, now: datetime) -> Dict[str, Any]:
    ready = bool(r["camera_user"] and r["camera_password"])
    streaming = bool(r["streaming"]) if "streaming" in r.keys() else False
    online = ready and agent_online and streaming
    return {
        "stream_id": r["stream_id"],
        "name": r["name"],
        "host": r["host"] or "",
        "agent_id": r["agent_id"],
        "ready": ready,
        "streaming": streaming,
        "online": online,
        "needs_auth": not ready,
    }


# --- API ---


@app.post("/api/auth/login")
def login(body: LoginIn):
    if not verify_user(body.username, body.password):
        raise HTTPException(status_code=401, detail="Login yoki parol noto'g'ri")
    return {"token": create_token(body.username), "username": body.username}


@app.get("/api/cameras")
def list_cameras(user: str = Depends(get_current_user)):
    with db() as conn:
        rows = conn.execute(
            """
            SELECT c.*, h.last_seen
            FROM cameras c
            LEFT JOIN agent_heartbeat h ON h.agent_id = c.agent_id
            ORDER BY c.agent_id, c.name
            """
        ).fetchall()
    now = datetime.now(timezone.utc)
    out = []
    for r in rows:
        agent_online = agent_is_online(r["last_seen"], now)
        out.append(camera_row_dict(r, agent_online, now))
    return {"cameras": out}


@app.post("/api/cameras/{stream_id}/credentials")
async def set_camera_credentials(
    stream_id: str,
    body: CameraCredentialsIn,
    user: str = Depends(get_current_user),
):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM cameras WHERE stream_id = ?", (stream_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, detail="Kamera topilmadi")
        host = row["host"]
        if not host:
            raise HTTPException(400, detail="Kamera host ma'lumoti yo'q")
        rtsp = build_rtsp_url(host, body.username, body.password, body.channel)
        ts = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE cameras
            SET camera_user = ?, camera_password = ?, rtsp_local = ?, online = 1, updated_at = ?
            WHERE stream_id = ?
            """,
            (body.username, body.password, rtsp, ts, stream_id),
        )

    await go2rtc_refresh_stream(stream_id)
    return {"ok": True, "stream_id": stream_id, "ready": True}


@app.get("/api/config/public")
def public_config(user: str = Depends(get_current_user)):
    """Frontend uchun go2rtc manzili."""
    host = CFG["server"].get("public_host", "localhost")
    go2rtc_public = CFG["go2rtc"].get("public_url", f"http://{host}:1984")
    return {"go2rtc_url": go2rtc_public.rstrip("/")}


@app.post("/api/agent/register")
async def agent_register(
    body: AgentRegisterIn,
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
):
    if not verify_agent_key(body.agent_id, x_agent_key):
        raise HTTPException(status_code=403, detail="Agent kalit noto'g'ri")

    ts = datetime.now(timezone.utc).isoformat()
    publish_host = CFG["mediamtx"].get("rtsp_publish_host", "127.0.0.1")

    registered_ids: List[str] = []
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_heartbeat (agent_id, last_seen) VALUES (?, ?)",
            (body.agent_id, ts),
        )
        for idx, cam in enumerate(body.cameras, start=1):
            host = cam.host or (cam.rtsp_url.split("@")[-1].split("/")[0] if cam.rtsp_url else "")
            if not host and cam.onvif_xaddr:
                host = urlparse(cam.onvif_xaddr).hostname or ""
            if not host:
                host = f"unknown{idx}"
            stream_id = stream_id_for(body.agent_id, host)
            registered_ids.append(stream_id)

            old = conn.execute(
                "SELECT camera_user, camera_password, rtsp_local FROM cameras WHERE stream_id = ?",
                (stream_id,),
            ).fetchone()

            rtsp_local = cam.rtsp_url or (old["rtsp_local"] if old else None)
            cam_user = old["camera_user"] if old else None
            cam_pass = old["camera_password"] if old else None
            if rtsp_local and not cam_user and "@" in rtsp_local:
                cam_user = cam_pass = None

            conn.execute("DELETE FROM cameras WHERE stream_id = ?", (stream_id,))
            conn.execute(
                """
                INSERT INTO cameras (
                    agent_id, stream_id, name, host, onvif_xaddr,
                    rtsp_local, camera_user, camera_password, online, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    body.agent_id,
                    stream_id,
                    cam.name or f"Kamera {host}",
                    host,
                    cam.onvif_xaddr or "",
                    rtsp_local,
                    cam_user,
                    cam_pass,
                    ts,
                ),
            )

            if cam_user and cam_pass:
                await go2rtc_refresh_stream(stream_id)

        if registered_ids:
            placeholders = ",".join("?" * len(registered_ids))
            conn.execute(
                f"DELETE FROM cameras WHERE agent_id = ? AND stream_id NOT IN ({placeholders})",
                [body.agent_id, *registered_ids],
            )
        else:
            conn.execute("DELETE FROM cameras WHERE agent_id = ?", (body.agent_id,))

    return {
        "ok": True,
        "agent_id": body.agent_id,
        "cameras": len(body.cameras),
        "stream_ids": registered_ids,
        "publish_template": f"rtsp://{publish_host}:8554/{{stream_id}}",
        "note": "Web sahifada har kamera uchun login/parol kiriting",
    }


@app.get("/api/agent/streams")
def agent_streams(
    agent_id: str,
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
):
    """Agent ffmpeg uchun — parol kiritilgan kameralar."""
    if not verify_agent_key(agent_id, x_agent_key):
        raise HTTPException(status_code=403, detail="Agent kalit noto'g'ri")

    publish_host = CFG["mediamtx"].get("rtsp_publish_host", "127.0.0.1")
    publish_port = int(CFG["mediamtx"].get("rtsp_publish_port", 8554))

    with db() as conn:
        rows = conn.execute(
            """
            SELECT stream_id, rtsp_local, host, camera_user, camera_password
            FROM cameras
            WHERE agent_id = ? AND camera_user IS NOT NULL AND camera_password IS NOT NULL
            """,
            (agent_id,),
        ).fetchall()

    streams = []
    for r in rows:
        rtsp = r["rtsp_local"]
        if not rtsp and r["host"]:
            rtsp = build_rtsp_url(r["host"], r["camera_user"], r["camera_password"])
        if not rtsp:
            continue
        streams.append(
            {
                "stream_id": r["stream_id"],
                "rtsp_url": rtsp,
                "publish_url": f"rtsp://{publish_host}:{publish_port}/{r['stream_id']}",
            }
        )

    return {
        "streams": streams,
        "publish_host": publish_host,
        "publish_port": publish_port,
    }


@app.post("/api/agent/heartbeat")
async def agent_heartbeat(
    agent_id: str,
    body: Optional[AgentHeartbeatIn] = None,
    x_agent_key: str = Header(..., alias="X-Agent-Key"),
):
    if not verify_agent_key(agent_id, x_agent_key):
        raise HTTPException(status_code=403, detail="Agent kalit noto'g'ri")
    ts = datetime.now(timezone.utc).isoformat()
    active = set((body or AgentHeartbeatIn()).active_streams)
    with db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_heartbeat (agent_id, last_seen) VALUES (?, ?)",
            (agent_id, ts),
        )
        conn.execute(
            "UPDATE cameras SET streaming = 0 WHERE agent_id = ?",
            (agent_id,),
        )
        for sid in active:
            conn.execute(
                "UPDATE cameras SET streaming = 1, online = 1 WHERE stream_id = ? AND agent_id = ?",
                (sid, agent_id),
            )

    return {"ok": True, "active": len(active)}


@app.get("/api/health")
def health():
    return {"ok": True, "service": "kamera-cloud", "version": "1.0.0"}


@app.get("/")
def index():
    return FileResponse(STATIC_DIR / "index.html")


if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    import uvicorn

    host = CFG["server"].get("host", "0.0.0.0")
    port = int(CFG["server"].get("port", 8080))
    uvicorn.run("app:app", host=host, port=port, reload=False)
