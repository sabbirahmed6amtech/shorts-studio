// Shared helpers for every page.

export async function api(path, { method = "GET", body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  const isJson = (res.headers.get("content-type") || "").includes("json");
  const data = isJson ? await res.json() : await res.text();
  if (!res.ok) {
    const msg = (data && data.detail) || `${res.status} ${res.statusText}`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return data;
}

let toastTimer;
export function toast(msg, isError = false) {
  let el = document.getElementById("toast");
  if (!el) {
    el = document.createElement("div");
    el.id = "toast";
    el.setAttribute("role", "status");
    document.body.appendChild(el);
  }
  el.textContent = msg;
  el.className = "show" + (isError ? " err" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = ""), isError ? 6000 : 2500);
}

export function fmtTime(sec, withTenths = false) {
  if (sec == null || isNaN(sec)) return "–";
  const neg = sec < 0;
  sec = Math.abs(sec);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = withTenths ? (sec % 60).toFixed(1).padStart(4, "0") : String(Math.floor(sec % 60)).padStart(2, "0");
  return (neg ? "-" : "") + (h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`);
}

export function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

export const STATUS = {
  queued: { label: "Queued", cls: "busy" },
  downloading: { label: "Downloading", cls: "busy" },
  transcribing: { label: "Transcribing", cls: "busy" },
  analyzing: { label: "Gemini is picking clips", cls: "busy" },
  ready: { label: "Ready", cls: "ok" },
  error: { label: "Failed", cls: "err" },
};
export const isBusy = (s) => ["queued", "downloading", "transcribing", "analyzing"].includes(s);

export function scoreColor(score) {
  if (score == null) return "#3b82f6"; // manual
  if (score >= 75) return "#18a058";
  if (score >= 50) return "#d48806";
  return "#8a8f98";
}
