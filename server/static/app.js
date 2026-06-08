const API = "";
const TOKEN_KEY = "kamera_cloud_token";
const USER_KEY = "kamera_cloud_user";

let go2rtcUrl = "http://localhost:1984";
let pendingCam = null;
let allCameras = [];

function $(id) {
  return document.getElementById(id);
}

function show(id) {
  ["login-view", "dashboard-view", "player-view"].forEach((v) => {
    $(v).classList.toggle("hidden", v !== id);
  });
}

function token() {
  return localStorage.getItem(TOKEN_KEY);
}

async function api(path, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  const res = await fetch(API + path, { ...options, headers });
  if (res.status === 401) {
    logout();
    throw new Error("Sessiya tugadi");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || res.statusText);
  return data;
}

function logout() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  show("login-view");
}

function statusLabel(cam) {
  if (cam.needs_auth) return { cls: "pending", text: "Parol kerak" };
  if (cam.online) return { cls: "online", text: "Online" };
  if (cam.ready && cam.streaming) return { cls: "offline", text: "Ulanmoqda..." };
  if (cam.ready) return { cls: "offline", text: "Video yuborilmoqda..." };
  return { cls: "offline", text: "Ulanmoqda..." };
}

async function waitForStream(streamId, maxSec = 60) {
  for (let i = 0; i < maxSec; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const { cameras } = await api("/api/cameras");
    allCameras = cameras;
    const cam = cameras.find((c) => c.stream_id === streamId);
    if (cam?.online) return cam;
  }
  throw new Error("Video tayyor emas. Agent oynasi ochiqmi va ffmpeg ishlayaptimi?");
}

function selectCameraForAuth(cam) {
  pendingCam = cam;
  $("auth-panel").classList.remove("hidden");
  $("auth-panel-camera").textContent = cam.name + (cam.host ? ` (${cam.host})` : "");
  $("cam-user").value = "admin";
  $("cam-pass").value = "";
  $("auth-error").classList.add("hidden");
  document.querySelectorAll(".card.selected").forEach((el) => el.classList.remove("selected"));
  const card = document.querySelector(`[data-stream-id="${cam.stream_id}"]`);
  if (card) card.classList.add("selected");
  $("auth-panel").scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function updateAuthPanelVisibility() {
  const needs = allCameras.filter((c) => c.needs_auth);
  if (needs.length === 0) {
    $("auth-panel").classList.add("hidden");
    pendingCam = null;
    return;
  }
  $("auth-panel").classList.remove("hidden");
  if (!pendingCam || !pendingCam.needs_auth) {
    selectCameraForAuth(needs[0]);
  }
}

$("login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const err = $("login-error");
  err.classList.add("hidden");
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("username").value.trim(),
        password: $("password").value,
      }),
    });
    localStorage.setItem(TOKEN_KEY, data.token);
    localStorage.setItem(USER_KEY, data.username);
    await loadDashboard();
  } catch (ex) {
    err.textContent = ex.message || "Kirish xatosi";
    err.classList.remove("hidden");
  }
});

$("logout-btn").addEventListener("click", logout);
$("back-btn").addEventListener("click", () => {
  $("player-frame").src = "";
  show("dashboard-view");
  updateAuthPanelVisibility();
});

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!pendingCam) {
    $("auth-error").textContent = "Avval kamerani tanlang";
    $("auth-error").classList.remove("hidden");
    return;
  }
  const err = $("auth-error");
  err.classList.add("hidden");
  try {
    const streamId = pendingCam.stream_id;
    await api(`/api/cameras/${streamId}/credentials`, {
      method: "POST",
      body: JSON.stringify({
        username: $("cam-user").value.trim(),
        password: $("cam-pass").value,
      }),
    });
    $("auth-error").textContent = "Video tayyorlanmoqda, kuting...";
    $("auth-error").classList.remove("hidden");
    await loadDashboard();
    const updated = await waitForStream(streamId);
    $("auth-error").classList.add("hidden");
    openPlayer(updated);
  } catch (ex) {
    err.textContent = ex.message || "Saqlash xatosi";
    err.classList.remove("hidden");
  }
});

async function loadDashboard() {
  const cfg = await api("/api/config/public");
  go2rtcUrl = cfg.go2rtc_url;
  const { cameras } = await api("/api/cameras");
  allCameras = cameras;
  $("user-label").textContent = localStorage.getItem(USER_KEY) || "";
  const grid = $("camera-grid");
  grid.innerHTML = "";
  $("empty-msg").classList.toggle("hidden", cameras.length > 0);

  cameras.forEach((cam) => {
    const st = statusLabel(cam);
    const el = document.createElement("div");
    el.className = "card";
    el.dataset.streamId = cam.stream_id;
    el.innerHTML = `
      <h3>${escapeHtml(cam.name)}</h3>
      <p class="muted">${escapeHtml(cam.host || cam.agent_id)}</p>
      <span class="badge ${st.cls}">${st.text}</span>
      ${cam.needs_auth ? '<button type="button" class="btn-small">Parol kiriting</button>' : ""}
    `;
    el.addEventListener("click", (e) => {
      if (e.target.classList.contains("btn-small")) {
        e.stopPropagation();
      }
      onCameraClick(cam);
    });
    grid.appendChild(el);
  });

  updateAuthPanelVisibility();
  show("dashboard-view");
}

function onCameraClick(cam) {
  if (cam.needs_auth) {
    selectCameraForAuth(cam);
    return;
  }
  if (!cam.online) {
    selectCameraForAuth(cam);
    $("auth-error").textContent = "Parol saqlangan. Agent ulanmoqda — 10–20 s kuting.";
    $("auth-error").classList.remove("hidden");
    return;
  }
  openPlayer(cam);
}

async function openPlayer(cam) {
  if (!cam.online) {
    try {
      cam = await waitForStream(cam.stream_id, 30);
    } catch (ex) {
      alert(ex.message);
      return;
    }
  }
  $("player-title").textContent = cam.name;
  const src = encodeURIComponent(cam.stream_id);
  $("player-frame").src = `${go2rtcUrl}/stream.html?src=${src}&mode=webrtc,mse,hls`;
  show("player-view");
}

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

if (token()) {
  loadDashboard().catch(logout);
} else {
  show("login-view");
}

setInterval(() => {
  if (token() && !$("dashboard-view").classList.contains("hidden")) {
    loadDashboard().catch(() => {});
  }
}, 15000);
