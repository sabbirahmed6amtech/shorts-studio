import { api, toast, esc } from "/common.js";

const form = document.getElementById("form");
const $ = (s) => document.querySelector(s);

// ---------- settings form ----------

function fill(s) {
  for (const el of form.elements) {
    if (!el.name || el.name === "gemini_api_key" || !(el.name in s)) continue;
    if (el.type === "checkbox") el.checked = !!s[el.name];
    else el.value = s[el.name];
  }
  const keyInput = form.elements.gemini_api_key;
  keyInput.value = "";
  keyInput.placeholder = s.gemini_key_set ? `Saved (${s.gemini_key_hint || "hidden"}). Paste a new key to replace it.` : "Paste your key";
  updatePreview();
}

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const body = Object.fromEntries(new FormData(form).entries());
  for (const el of form.elements) if (el.type === "checkbox" && el.name) body[el.name] = el.checked;
  try {
    fill(await api("/api/settings", { method: "PUT", body }));
    const saved = $("#saved");
    saved.classList.add("show");
    setTimeout(() => saved.classList.remove("show"), 2000);
  } catch (err) {
    toast(err.message, true);
  }
});

// ---------- caption preview ----------

const FONT_FILES = { "Anton": "Anton-Regular.ttf", "Poppins ExtraBold": "Poppins-ExtraBold.ttf", "Bebas Neue": "BebasNeue-Regular.ttf" };
for (const [name, file] of Object.entries(FONT_FILES)) {
  const face = new FontFace(`cap-${name}`, `url(/fonts/${file})`);
  face.load().then((f) => document.fonts.add(f)).catch(() => {});
}

function updatePreview() {
  const f = form.elements;
  const box = $("#cap-preview span");
  if (!box) return;
  const upper = f.caption_uppercase.checked;
  const n = Math.max(1, Number(f.caption_words.value) || 3);
  const words = ["this", "is", "how", "it", "looks", "on", "screen"].slice(0, n);
  const hi = Math.min(1, words.length - 1);
  box.innerHTML = words.map((w, i) => {
    const t = esc(upper ? w.toUpperCase() : w);
    return i === hi ? `<span style="color:${f.caption_highlight.value}">${t}</span>` : t;
  }).join(" ");
  Object.assign(box.style, {
    fontFamily: `"cap-${f.caption_font.value}", sans-serif`,
    // The preview box is about 1/9 of the 1920px video height.
    fontSize: `${Math.max(10, (Number(f.caption_size.value) || 110) / 4)}px`,
    color: f.caption_color.value,
  });
  $("#cap-preview").style.opacity = f.captions_enabled.checked ? 1 : 0.35;
}
form.addEventListener("input", updatePreview);

// ---------- YouTube connection ----------

const SETUP_STEPS = `
  <ol class="steps small">
    <li>Open <a href="https://console.cloud.google.com/projectcreate" target="_blank" rel="noopener">Google Cloud</a> and create a project.</li>
    <li>Enable the <a href="https://console.cloud.google.com/apis/library/youtube.googleapis.com" target="_blank" rel="noopener">YouTube Data API v3</a> for it.</li>
    <li>In <a href="https://console.cloud.google.com/auth/overview" target="_blank" rel="noopener">Google Auth Platform</a>, set it up with audience <b>External</b>, and add your Google account under <b>Audience → Test users</b>.</li>
    <li>Under <a href="https://console.cloud.google.com/auth/clients" target="_blank" rel="noopener">Clients</a>, create a client of type <b>Desktop app</b> and download its JSON file.</li>
    <li>Upload that file here, then press <b>Connect YouTube</b>.</li>
  </ol>
  <div class="notice small" style="margin-top:10px">
    <b>Two Google rules to know:</b><br>
    • While the app is in <i>Testing</i>, Google signs you out after 7 days. To stay connected, press <b>Publish app</b> on the Audience page. When you connect, Google will warn that the app isn't verified: choose <i>Advanced → Go to app</i>. It's your own app.<br>
    • Until Google audits your project, YouTube keeps every API upload <b>private</b>, so scheduled Shorts won't go public. Request the audit with the
    <a href="https://support.google.com/youtube/contact/yt_api_form" target="_blank" rel="noopener">YouTube API audit form</a>.
  </div>`;

async function loadYouTube() {
  const body = $("#yt-body");
  let st;
  try {
    st = await api("/api/youtube/status");
  } catch (e) {
    body.textContent = e.message;
    return;
  }
  const msg = $("#yt-msg");
  msg.classList.toggle("hidden", !st.error);
  msg.textContent = st.error || "";

  if (!st.client) {
    body.innerHTML = `
      <p class="small" style="margin-top:0">To upload and schedule Shorts, connect your channel. This is a one-time setup (about 10 minutes):</p>
      ${SETUP_STEPS}
      <div class="row" style="margin-top:12px">
        <input type="file" id="client-file" accept=".json,application/json" class="grow">
        <button class="btn primary" id="client-upload">Upload client file</button>
      </div>`;
  } else if (!st.connected) {
    body.innerHTML = `
      <p class="small" style="margin-top:0">Client file saved. Sign in with the Google account that owns your channel.</p>
      <div class="row">
        <a class="btn primary" href="/auth/youtube/start">Connect YouTube</a>
        <button class="btn danger" id="client-remove">Remove client file</button>
      </div>
      <details style="margin-top:10px"><summary class="small">Setup steps</summary>${SETUP_STEPS}</details>`;
  } else {
    const ch = st.channel;
    body.innerHTML = `
      <div class="channel">
        ${ch?.thumb ? `<img src="${esc(ch.thumb)}" alt="">` : ""}
        <div class="grow"><b>${esc(ch?.title || "Connected")}</b><div class="muted small">Uploads and schedules go to this channel.</div></div>
        <button class="btn" id="yt-disconnect">Disconnect</button>
      </div>
      <details style="margin-top:10px"><summary class="small">Setup notes (sign-in expiry, private uploads)</summary>${SETUP_STEPS}</details>`;
  }
}

$("#yt-card").addEventListener("click", async (e) => {
  const id = e.target.id;
  try {
    if (id === "client-upload") {
      const file = $("#client-file").files[0];
      if (!file) return toast("Choose the JSON file first", true);
      const fd = new FormData();
      fd.append("file", file);
      await api("/api/youtube/client", { method: "POST", form: fd });
      toast("Client file saved");
    } else if (id === "client-remove") {
      if (!confirm("Remove the client file and disconnect YouTube?")) return;
      await api("/api/youtube/client", { method: "DELETE" });
    } else if (id === "yt-disconnect") {
      if (!confirm("Disconnect this channel? Scheduled videos already on YouTube are not affected.")) return;
      await api("/api/youtube/disconnect", { method: "POST" });
    } else return;
    loadYouTube();
  } catch (err) {
    toast(err.message, true);
  }
});

// Coming back from Google's sign-in page.
const params = new URLSearchParams(location.search);
if (params.get("yt") === "connected") toast("YouTube connected");
if (params.get("yt_error")) {
  $("#yt-msg").classList.remove("hidden");
  $("#yt-msg").textContent = params.get("yt_error");
}
if (params.has("yt") || params.has("yt_error")) history.replaceState(null, "", "/settings.html");

api("/api/settings").then(fill).catch((e) => toast(e.message, true));
loadYouTube().then(() => {
  if (params.get("yt_error")) {
    $("#yt-msg").classList.remove("hidden");
    $("#yt-msg").textContent = params.get("yt_error");
  }
});
