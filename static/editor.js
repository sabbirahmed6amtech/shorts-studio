import WaveSurfer from "/vendor/wavesurfer.esm.js";
import RegionsPlugin from "/vendor/regions.esm.js";
import TimelinePlugin from "/vendor/timeline.esm.js";
import { api, toast, fmtTime, esc, STATUS, isBusy, scoreColor } from "/common.js";

const $ = (s) => document.querySelector(s);
const jobId = Number(new URLSearchParams(location.search).get("job"));
const video = $("#video");

let job = null;
let clips = [];
let words = [];
let selectedId = null;
let ws = null;
let regions = null;
let adding = false; // true while we add regions from code, so they aren't mistaken for user drags
let fitPx = 1;
let yt = { connected: false };
let settings = {};
let pollTimer = null;
let outSig = "";
const regionByClip = new Map();

// ---------- helpers ----------

const clipById = (id) => clips.find((c) => c.id === id);
const clipIdOf = (region) => Number(String(region.id).replace("clip-", "")) || null;

function rgba(hex, a) {
  const n = parseInt(hex.slice(1), 16);
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${a})`;
}

function parseTime(text) {
  const parts = String(text).trim().split(":").map(Number);
  if (!parts.length || parts.some(isNaN)) return null;
  return parts.reduce((acc, p) => acc * 60 + p, 0);
}

function stageMsg(text) {
  $("#stage-msg").classList.toggle("hidden", !text);
  $("#stage-msg").textContent = text || "";
}

async function patchClip(id, fields) {
  try {
    const updated = await api(`/api/clips/${id}`, { method: "PATCH", body: fields });
    Object.assign(clipById(id), updated);
    renderList();
    if (id === selectedId) renderOutput(clipById(id)); // edits can make a render out of date
    return updated;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

// ---------- startup ----------

async function init() {
  if (!jobId) return (location.href = "/");
  try {
    job = await api(`/api/jobs/${jobId}`);
  } catch (e) {
    stageMsg(e.message);
    return;
  }
  document.title = `${job.title || "Video"} · Shorts Studio`;
  $("#job-title").textContent = job.title || job.url || `Video ${job.id}`;
  $("#job-title").title = $("#job-title").textContent;

  if (job.status !== "ready") return waitForReady();

  const [clipList, peaks, transcript, ytStatus] = await Promise.all([
    api(`/api/jobs/${jobId}/clips`),
    api(`/api/jobs/${jobId}/peaks`),
    api(`/api/jobs/${jobId}/transcript`).catch(() => ({ words: [] })),
    api("/api/youtube/status").catch(() => ({ connected: false })),
    api("/api/settings").catch(() => ({})),
  ]).then((r) => { settings = r[4]; return r; });
  yt = ytStatus;
  loadLayout();
  clips = clipList;
  words = transcript.words || [];
  showAiMessage();

  video.src = `/api/jobs/${jobId}/video`;
  video.addEventListener("error", () =>
    stageMsg("Your browser can't play this video's format. Clips can still be edited on the timeline."));
  video.addEventListener("loadedmetadata", layoutCrop);
  new ResizeObserver(layoutCrop).observe($("#stage"));

  setupWave(peaks);
  renderList();
  ensurePolling();
}

async function waitForReady() {
  const st = STATUS[job.status] || { label: job.status };
  if (job.status === "error") {
    stageMsg(`Processing failed: ${job.message || "unknown error"}. Go back to Videos to retry.`);
    return;
  }
  const pct = job.progress ? ` ${Math.round(job.progress * 100)}%` : "";
  stageMsg(`Still processing: ${st.label}${pct}…`);
  setTimeout(async () => {
    job = await api(`/api/jobs/${jobId}`).catch(() => job);
    if (job.status === "ready") location.reload();
    else waitForReady();
  }, 2000);
}

function showAiMessage() {
  const el = $("#ai-msg");
  el.classList.toggle("hidden", !job.ai_error);
  el.textContent = job.ai_error || "";
}

// ---------- waveform + regions ----------

function setupWave(peaks) {
  const css = getComputedStyle(document.documentElement);
  regions = RegionsPlugin.create();
  const duration = job.duration || peaks.peaks.length / peaks.per_second;
  fitPx = Math.max(0.5, ($("#wave").clientWidth || 800) / duration);

  ws = WaveSurfer.create({
    container: "#wave",
    media: video,
    peaks: [peaks.peaks],
    duration,
    height: 90,
    normalize: true,
    waveColor: css.getPropertyValue("--muted").trim() || "#9aa1ad",
    progressColor: css.getPropertyValue("--accent").trim() || "#e5484d",
    cursorColor: css.getPropertyValue("--accent").trim() || "#e5484d",
    cursorWidth: 2,
    barWidth: 2,
    barGap: 1,
    minPxPerSec: fitPx,
    autoScroll: true,
    autoCenter: true,
    plugins: [regions, TimelinePlugin.create({ height: 18 })],
  });

  ws.once("ready", () => {
    addAllRegions();
    regions.enableDragSelection({ color: rgba("#3b82f6", 0.25), minLength: 1 });
  });
  ws.on("timeupdate", (t) => {
    $("#time").textContent = `${fmtTime(t, true)} / ${fmtTime(duration)}`;
  });
  ws.on("play", () => ($("#play").textContent = "❚❚ Pause"));
  ws.on("pause", () => ($("#play").textContent = "▶ Play"));

  regions.on("region-created", (r) => {
    if (!adding) createFromDrag(r);
  });
  regions.on("region-updated", async (r) => {
    const id = clipIdOf(r);
    if (!id) return;
    const updated = await patchClip(id, { start: r.start, end: r.end });
    if (!updated) {
      const c = clipById(id); // put it back where the server has it
      r.setOptions({ start: c.start, end: c.end });
      return;
    }
    renderList();
    if (id === selectedId) renderDetail();
  });
  regions.on("region-clicked", (r, e) => {
    e.stopPropagation();
    const id = clipIdOf(r);
    if (id) select(id, { seek: true, scrollList: true });
  });
}

function regionLabel(c, index) {
  return c.score == null ? `#${index + 1}` : `#${index + 1} · ${c.score}`;
}

function regionColor(c) {
  return rgba(scoreColor(c.score), c.id === selectedId ? 0.42 : 0.18);
}

function addRegion(c, index) {
  adding = true;
  try {
    const r = regions.addRegion({
      id: `clip-${c.id}`,
      start: c.start,
      end: c.end,
      color: regionColor(c),
      content: regionLabel(c, index),
      drag: true,
      resize: true,
      minLength: 1,
    });
    regionByClip.set(c.id, r);
  } finally {
    adding = false;
  }
}

function addAllRegions() {
  adding = true;
  regions.clearRegions();
  adding = false;
  regionByClip.clear();
  sortedClips().forEach((c, i) => addRegion(c, i));
}

async function createFromDrag(r) {
  const start = r.start;
  const end = r.end;
  r.remove();
  await createClip(start, end);
}

async function createClip(start, end) {
  try {
    const c = await api(`/api/jobs/${jobId}/clips`, { method: "POST", body: { start, end } });
    clips.push(c);
    refreshRegions();
    renderList();
    select(c.id, { scrollList: true });
  } catch (e) {
    toast(e.message, true);
  }
}

/** Re-number labels and colours after the clip list changes. */
function refreshRegions() {
  sortedClips().forEach((c, i) => {
    const r = regionByClip.get(c.id);
    if (r) r.setOptions({ color: regionColor(c), content: regionLabel(c, i) });
    else addRegion(c, i);
  });
}

// ---------- clip list + selection ----------

const sortedClips = () => [...clips].sort((a, b) => a.start - b.start);

function renderList() {
  const list = sortedClips();
  $("#clip-count").textContent = list.length
    ? `${list.length} clip${list.length === 1 ? "" : "s"}`
    : "No clips yet";
  $("#clips").innerHTML = list.length
    ? list.map((c, i) => `
      <button class="clip-item ${c.id === selectedId ? "active" : ""}" data-id="${c.id}">
        <div class="top">
          <span>#${i + 1} · ${fmtTime(c.start)}–${fmtTime(c.end)} · ${Math.round(c.end - c.start)}s</span>
          ${c.score != null
            ? `<span class="score" style="background:${scoreColor(c.score)}">${c.score}</span>`
            : `<span class="muted">manual</span>`}
        </div>
        <div class="name">${esc(c.title) || '<span class="muted">Untitled</span>'}</div>
        ${flagsHtml(c)}
      </button>`).join("")
    : `<div class="empty small">Drag across the waveform to create a clip${job.ai_error ? "" : ", or press Run AI again"}.</div>`;
}

function pct(p) {
  return `${Math.round((p || 0) * 100)}%`;
}

function when(iso) {
  return new Date(iso).toLocaleString([], { dateStyle: "medium", timeStyle: "short" });
}

function flagsHtml(c) {
  const f = [];
  if (c.render_status === "queued") f.push(`<span class="flag busy">Waiting to render</span>`);
  else if (c.render_status === "rendering") f.push(`<span class="flag busy">Rendering ${pct(c.render_progress)}</span>`);
  else if (c.render_status === "error") f.push(`<span class="flag err">Render failed</span>`);
  else if (c.render_status === "done") f.push(c.render_current ? `<span class="flag ok">Rendered</span>` : `<span class="flag warn">Edited since render</span>`);
  if (c.yt_status === "queued") f.push(`<span class="flag busy">Waiting to upload</span>`);
  else if (c.yt_status === "uploading") f.push(`<span class="flag busy">Uploading ${pct(c.yt_progress)}</span>`);
  else if (c.yt_status === "scheduled") f.push(`<span class="flag ok">⏰ ${when(c.yt_publish_at)}</span>`);
  else if (c.yt_status === "published") f.push(`<span class="flag ok">On YouTube</span>`);
  else if (c.yt_status === "error") f.push(`<span class="flag err">Upload failed</span>`);
  return f.length ? `<div class="flags">${f.join("")}</div>` : "";
}

$("#clips").addEventListener("click", (e) => {
  const b = e.target.closest(".clip-item");
  if (b) select(Number(b.dataset.id), { seek: true });
});

function select(id, { seek = false, scrollList = false } = {}) {
  selectedId = id;
  const c = clipById(id);
  refreshRegions();
  renderList();
  renderDetail();
  layoutCrop();
  if (c && seek) ws.setTime(c.start);
  if (scrollList) document.querySelector(`.clip-item[data-id="${id}"]`)?.scrollIntoView({ block: "nearest" });
}

function spokenText(c) {
  return words.filter((w) => w.s >= c.start - 0.05 && w.e <= c.end + 0.05).map((w) => w.w).join(" ");
}

function renderDetail() {
  const el = $("#detail");
  const c = clipById(selectedId);
  if (!c) {
    el.classList.add("hidden");
    return;
  }
  el.classList.remove("hidden");
  const said = spokenText(c);
  el.innerHTML = `
    <div class="row">
      <h3 class="grow">Clip · ${(c.end - c.start).toFixed(1)}s</h3>
      <span class="saved" id="saved">Saved</span>
    </div>
    <div class="times">
      <label>Start<input type="text" id="f-start" value="${fmtTime(c.start, true)}"></label>
      <label>End<input type="text" id="f-end" value="${fmtTime(c.end, true)}"></label>
      <button class="btn sm" id="play-clip" title="Play just this clip">▶ Play clip</button>
    </div>
    <div class="row">
      <button class="btn sm" id="start-here" title="Set start to the playhead">Start = playhead</button>
      <button class="btn sm" id="end-here" title="Set end to the playhead">End = playhead</button>
    </div>
    <label>Title <span class="hint" id="title-count"></span>
      <input type="text" id="f-title" maxlength="100" value="${esc(c.title)}" placeholder="Short, catchy title">
    </label>
    <label>Description
      <textarea id="f-desc" rows="3" placeholder="What this Short is about">${esc(c.description)}</textarea>
    </label>
    <label>Hashtags <span class="hint">separated by spaces</span>
      <input type="text" id="f-tags" value="${esc((c.hashtags || []).join(" "))}">
    </label>
    ${c.hook || c.reason ? `<div class="why">${c.hook ? `<div><b>Hook:</b> ${esc(c.hook)}</div>` : ""}${c.reason ? `<div><b>Why:</b> ${esc(c.reason)}</div>` : ""}</div>` : ""}
    ${said ? `<div><div class="muted small">What's said</div><div class="said">${esc(said)}</div></div>` : ""}
    <div id="clip-out"></div>
    <div class="row"><span class="grow"></span><button class="btn sm danger" id="del-clip">Delete clip</button></div>
  `;
  renderOutput(c, true);

  const flash = () => {
    const s = $("#saved");
    if (!s) return;
    s.classList.add("show");
    setTimeout(() => s.classList.remove("show"), 1200);
  };
  const updateCount = () => ($("#title-count").textContent = `${$("#f-title").value.length}/100`);
  updateCount();
  $("#f-title").addEventListener("input", updateCount);

  const saveText = async (fields) => {
    if (await patchClip(c.id, fields)) {
      flash();
      renderList();
    }
  };
  $("#f-title").addEventListener("change", (e) => saveText({ title: e.target.value }));
  $("#f-desc").addEventListener("change", (e) => saveText({ description: e.target.value }));
  $("#f-tags").addEventListener("change", (e) =>
    saveText({ hashtags: e.target.value.split(/[\s,]+/).filter(Boolean) }));

  const saveTimes = async (start, end) => {
    if (start == null || end == null) return toast("Use a time like 1:23.4", true);
    const updated = await patchClip(c.id, { start, end });
    if (updated) {
      regionByClip.get(c.id)?.setOptions({ start: updated.start, end: updated.end });
      refreshRegions();
      renderList();
      flash();
    }
    renderDetail();
  };
  $("#f-start").addEventListener("change", (e) => saveTimes(parseTime(e.target.value), c.end));
  $("#f-end").addEventListener("change", (e) => saveTimes(c.start, parseTime(e.target.value)));
  $("#start-here").addEventListener("click", () => saveTimes(ws.getCurrentTime(), c.end));
  $("#end-here").addEventListener("click", () => saveTimes(c.start, ws.getCurrentTime()));
  $("#play-clip").addEventListener("click", () => regionByClip.get(c.id)?.play(true));

  $("#del-clip").addEventListener("click", async () => {
    if (!confirm("Delete this clip?")) return;
    try {
      await api(`/api/clips/${c.id}`, { method: "DELETE" });
      regionByClip.get(c.id)?.remove();
      regionByClip.delete(c.id);
      clips = clips.filter((x) => x.id !== c.id);
      selectedId = null;
      refreshRegions();
      renderList();
      renderDetail();
      layoutCrop();
    } catch (e) {
      toast(e.message, true);
    }
  });
}

// ---------- render + YouTube panel ----------

function toLocalInput(iso) {
  const d = new Date(iso);
  const p = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
}

function renderSection(c) {
  const busy = c.render_status === "queued" || c.render_status === "rendering";
  let body;
  if (busy) {
    body = `
      <div class="row"><span class="grow small">${c.render_status === "queued" ? "Waiting to render…" : `Rendering ${pct(c.render_progress)}`}</span>
        ${c.render_status === "queued" ? `<button class="btn sm" data-act="cancel">Cancel</button>` : ""}</div>
      <div class="bar"><i style="width:${pct(c.render_progress)}"></i></div>`;
  } else {
    const file = c.render_file ? `/api/clips/${c.id}/file?v=${encodeURIComponent(c.render_file)}` : null;
    body = `
      ${c.render_status === "error" ? `<div class="notice err small">${esc(c.render_error)}</div>` : ""}
      ${c.render_status === "done" && !c.render_current ? `<div class="notice warn small">You changed this clip or the caption style after rendering. Render again to include the changes.</div>` : ""}
      ${file && c.render_status === "done" ? `<video class="preview" src="${file}" controls preload="metadata" playsinline></video>` : ""}
      <div class="row">
        <button class="btn sm ${c.render_current ? "" : "primary"}" data-act="render">${c.render_file ? "Render again" : "Render"}</button>
        ${file && c.render_status === "done" ? `<a class="btn sm" href="/api/clips/${c.id}/file?download=1">Download</a>` : ""}
      </div>`;
  }
  return `<div class="out-block"><h3>Vertical video</h3>${body}</div>`;
}

function youtubeSection(c) {
  let body;
  const link = c.yt_video_id
    ? `<a href="https://youtube.com/shorts/${c.yt_video_id}" target="_blank" rel="noopener">Watch</a> ·
       <a href="https://studio.youtube.com/video/${c.yt_video_id}/edit" target="_blank" rel="noopener">Open in YouTube Studio</a>` : "";
  if (c.yt_status === "queued" || c.yt_status === "uploading") {
    const label = c.yt_status === "queued" ? "Waiting to upload…"
      : c.render_status === "rendering" ? "Rendering before upload…" : `Uploading ${pct(c.yt_progress)}`;
    body = `
      <div class="row"><span class="grow small">${label}${c.yt_publish_at ? ` · goes public ${when(c.yt_publish_at)}` : ""}</span>
        ${c.yt_status === "queued" ? `<button class="btn sm" data-act="cancel">Cancel</button>` : ""}</div>
      <div class="bar"><i style="width:${pct(c.yt_progress)}"></i></div>`;
  } else if (c.yt_status === "scheduled") {
    const live = new Date(c.yt_publish_at) <= new Date();
    body = `<div class="small">${live ? "Went public" : "Uploaded. YouTube makes it public on"} <b>${when(c.yt_publish_at)}</b>.</div>
      <div class="small">${link}</div>
      <div class="muted small">To change the time or details now, use YouTube Studio. Edits here don't update YouTube.</div>`;
  } else if (c.yt_status === "published") {
    body = `<div class="small">Uploaded as <b>${esc(c.yt_privacy || "public")}</b>.</div><div class="small">${link}</div>
      <div class="muted small">Edits here don't update YouTube.</div>`;
  } else if (!yt.connected) {
    body = `<div class="small muted">Connect your channel in <a href="/settings.html">Settings</a> to upload and schedule.</div>`;
  } else {
    body = `
      ${c.yt_status === "error" ? `<div class="notice err small">${esc(c.yt_error)}</div>` : ""}
      <label>Publish on <span class="hint">your time zone</span>
        <input type="datetime-local" id="yt-when">
      </label>
      <div class="row">
        <button class="btn sm primary" data-act="schedule">Schedule</button>
        <span class="muted small">or</span>
        <select id="yt-privacy" style="width:auto">
          ${["public", "unlisted", "private"].map((v) =>
            `<option value="${v}" ${v === (settings.yt_now_privacy || "public") ? "selected" : ""}>${v[0].toUpperCase() + v.slice(1)}</option>`).join("")}
        </select>
        <button class="btn sm" data-act="upload-now">Upload now</button>
      </div>
      <div class="muted small">The clip is rendered first if needed. YouTube holds scheduled videos as private and publishes them at the chosen time, so this computer doesn't need to be on then.</div>`;
  }
  return `<div class="out-block"><h3>YouTube${yt.channel ? ` <span class="muted small">· ${esc(yt.channel.title)}</span>` : ""}</h3>
    ${yt.error ? `<div class="notice warn small">${esc(yt.error)}</div>` : ""}${body}</div>`;
}

function renderOutput(c, force = false) {
  const el = $("#clip-out");
  if (!el || !c) return;
  const sig = JSON.stringify([c.id, c.render_status, pct(c.render_progress), c.render_current, c.render_file,
    c.render_error, c.yt_status, pct(c.yt_progress), c.yt_error, c.yt_video_id, c.yt_publish_at, yt.connected]);
  if (!force && sig === outSig) return; // don't wipe a time the user is typing
  outSig = sig;
  el.innerHTML = renderSection(c) + youtubeSection(c);
  const input = $("#yt-when");
  if (input) {
    api(`/api/youtube/next-slots?n=1&clip=${c.id}`)
      .then(([slot]) => { if (input.isConnected && !input.value) input.value = toLocalInput(slot); })
      .catch(() => {});
  }
}

const anyBusy = () => clips.some((c) =>
  ["queued", "rendering"].includes(c.render_status) || ["queued", "uploading"].includes(c.yt_status));

function ensurePolling() {
  if (pollTimer || !anyBusy()) return;
  pollTimer = setInterval(async () => {
    try {
      const fresh = await api(`/api/jobs/${jobId}/clips`);
      for (const f of fresh) {
        const c = clipById(f.id);
        if (c) Object.assign(c, f);
      }
      renderList();
      renderOutput(clipById(selectedId));
    } catch {}
    if (!anyBusy()) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }, 2000);
}

async function clipAction(c, act) {
  let updated;
  if (act === "render") {
    updated = await api(`/api/clips/${c.id}/render`, { method: "POST" });
  } else if (act === "cancel") {
    updated = await api(`/api/clips/${c.id}/cancel`, { method: "POST" });
  } else if (act === "schedule") {
    const v = $("#yt-when").value;
    if (!v) return toast("Pick a date and time", true);
    updated = await api(`/api/clips/${c.id}/youtube`, { method: "POST", body: { publish_at: new Date(v).toISOString() } });
  } else if (act === "upload-now") {
    const privacy = $("#yt-privacy").value;
    if (privacy === "public" && !confirm("Upload and publish this Short publicly right now?")) return;
    updated = await api(`/api/clips/${c.id}/youtube`, { method: "POST", body: { privacy } });
  }
  if (updated) Object.assign(c, updated);
  renderList();
  renderOutput(c, true);
  ensurePolling();
}

$("#detail").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-act]");
  const c = clipById(selectedId);
  if (!b || !c) return;
  b.disabled = true;
  try {
    await clipAction(c, b.dataset.act);
  } catch (err) {
    toast(err.message, true);
  } finally {
    b.disabled = false;
  }
});

async function reloadClips() {
  const fresh = await api(`/api/jobs/${jobId}/clips`);
  for (const f of fresh) {
    const c = clipById(f.id);
    if (c) Object.assign(c, f);
  }
  renderList();
  renderOutput(clipById(selectedId), true);
  ensurePolling();
}

$("#render-all").addEventListener("click", async () => {
  try {
    const r = await api(`/api/jobs/${jobId}/render-all`, { method: "POST" });
    toast(r.queued ? `Rendering ${r.queued} clip${r.queued === 1 ? "" : "s"}` : "Every clip is already rendered");
    await reloadClips();
  } catch (e) {
    toast(e.message, true);
  }
});

$("#schedule-all").addEventListener("click", async () => {
  if (!yt.connected) return toast("Connect YouTube in Settings first.", true);
  const todo = clips.filter((c) => !c.yt_status || c.yt_status === "error");
  if (!todo.length) return toast("Every clip is already on YouTube or uploading.");
  try {
    const slots = await api(`/api/youtube/next-slots?n=${todo.length}`);
    if (!confirm(`Upload ${todo.length} clip${todo.length === 1 ? "" : "s"}, best score first, one per slot from ` +
      `${when(slots[0])} to ${when(slots[slots.length - 1])}? Each is rendered first if needed.`)) return;
    const r = await api(`/api/jobs/${jobId}/schedule-all`, { method: "POST" });
    toast(`Scheduled ${r.queued} clip${r.queued === 1 ? "" : "s"}`);
    await reloadClips();
  } catch (e) {
    toast(e.message, true);
  }
});

// ---------- framing: one 9:16 crop, or streamer on top + content below ----------

const OUT_W = 1080, OUT_H = 1920;
let cropGeom = null;   // where the video picture sits inside the stage (px)
let liveCropX = null;  // crop centre while dragging, so the preview follows the mouse
let layout = { mode: "single", split: 0.4, cam: null, content: null };

function loadLayout() {
  const data = job.layout_json ? JSON.parse(job.layout_json) : null;
  layout = { mode: job.layout || "single", split: data?.split ?? 0.4, cam: data?.cam || null, content: data?.content || null };
  syncLayoutControls();
}

/** Shape (width / height, in source pixels) each part must have so the Short isn't stretched. */
function partAspect(which) {
  const topH = Math.round((OUT_H * layout.split) / 2) * 2;
  return OUT_W / (which === "cam" ? topH : OUT_H - topH);
}

/** Shrink a 0..1 rect around its centre to the given pixel aspect and keep it in the frame. */
function fitRect(r, aspect) {
  const W = video.videoWidth || 1920, H = video.videoHeight || 1080;
  let w = r.w * W, h = r.h * H;
  const cx = (r.x + r.w / 2) * W, cy = (r.y + r.h / 2) * H;
  if (w / h > aspect) w = h * aspect; else h = w / aspect;
  w = Math.min(w, W, H * aspect);
  h = w / aspect;
  const x = Math.min(Math.max(cx - w / 2, 0), W - w);
  const y = Math.min(Math.max(cy - h / 2, 0), H - h);
  return { x: x / W, y: y / H, w: w / W, h: h / H };
}

function defaultLayout() {
  layout.split = layout.split || 0.4;
  // Facecam: top-left, about a third of the width. Content: the middle, full height.
  layout.cam = fitRect({ x: 0.01, y: 0.02, w: 0.32, h: 0.5 }, partAspect("cam"));
  layout.content = fitRect({ x: 0.2, y: 0, w: 0.6, h: 1 }, partAspect("content"));
}

function syncLayoutControls() {
  document.querySelectorAll("#layout-mode button").forEach((b) => b.classList.toggle("active", b.dataset.mode === layout.mode));
  $("#split-wrap").classList.toggle("hidden", layout.mode !== "split");
  $("#split").value = Math.round(layout.split * 100);
  $("#split-val").textContent = `${Math.round(layout.split * 100)}%`;
}

let saveTimer;
function saveLayout() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(async () => {
    try {
      const body = { mode: layout.mode, split: layout.split };
      if (layout.mode === "split") Object.assign(body, { cam: layout.cam, content: layout.content });
      job = await api(`/api/jobs/${jobId}/layout`, { method: "PUT", body });
      await reloadClips(); // renders made with the old framing are now out of date
    } catch (e) {
      toast(e.message, true);
    }
  }, 400);
}

function layoutCrop() {
  const crop = $("#crop");
  const stage = $("#stage");
  if (!video.videoWidth) {
    crop.classList.add("hidden");
    cropGeom = null;
    return;
  }
  const sw = stage.clientWidth, sh = stage.clientHeight;
  const scale = Math.min(sw / video.videoWidth, sh / video.videoHeight);
  const w = video.videoWidth * scale, h = video.videoHeight * scale;
  cropGeom = { w, h, boxW: Math.min(w, (h * 9) / 16) };
  Object.assign(crop.style, { left: `${(sw - w) / 2}px`, top: `${(sh - h) / 2}px`, width: `${w}px`, height: `${h}px` });

  const split = layout.mode === "split";
  if (split && (!layout.cam || !layout.content)) defaultLayout();
  const c = clipById(selectedId);
  crop.classList.toggle("hidden", !split && !c);
  for (const el of ["#crop-box", "#shade-l", "#shade-r"]) $(el).classList.toggle("hidden", split);
  for (const el of ["#box-cam", "#box-content"]) $(el).classList.toggle("hidden", !split);
  if (split) {
    placeRect($("#box-cam"), layout.cam);
    placeRect($("#box-content"), layout.content);
  } else if (c) {
    placeBox(c.crop_x ?? 0.5);
    $("#crop-box .tag").textContent = cropGeom.boxW >= w - 1 ? "Already vertical" : "9:16 · drag";
  }
}

function placeRect(el, r) {
  const { w, h } = cropGeom;
  Object.assign(el.style, { left: `${r.x * w}px`, top: `${r.y * h}px`, width: `${r.w * w}px`, height: `${r.h * h}px` });
}

/** Position the single crop for a centre (0..1 of the width). Returns the centre after clamping. */
function placeBox(cx) {
  const { w, boxW } = cropGeom;
  const left = Math.min(Math.max(cx * w - boxW / 2, 0), w - boxW);
  $("#crop-box").style.left = `${left}px`;
  $("#crop-box").style.width = `${boxW}px`;
  $("#shade-l").style.cssText = `left:0;width:${left}px`;
  $("#shade-r").style.cssText = `left:${left + boxW}px;right:0`;
  return w > boxW ? (left + boxW / 2) / w : 0.5;
}

// Single crop: drag sideways.
{
  const box = $("#crop-box");
  let drag = null;
  box.addEventListener("pointerdown", (e) => {
    if (!cropGeom || cropGeom.boxW >= cropGeom.w - 1) return;
    e.preventDefault();
    box.setPointerCapture(e.pointerId);
    box.classList.add("dragging");
    drag = { x: e.clientX, left: box.offsetLeft, cx: null };
  });
  box.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const { w, boxW } = cropGeom;
    drag.cx = liveCropX = placeBox((drag.left + (e.clientX - drag.x) + boxW / 2) / w);
  });
  const end = async () => {
    if (!drag) return;
    box.classList.remove("dragging");
    const cx = drag.cx;
    drag = null;
    if (cx != null && selectedId) await patchClip(selectedId, { crop_x: Math.round(cx * 1000) / 1000 });
    liveCropX = null;
  };
  box.addEventListener("pointerup", end);
  box.addEventListener("pointercancel", end);
}

// Streamer / content boxes: drag to move, drag the corner to resize (shape stays locked).
for (const which of ["cam", "content"]) {
  const el = $(`#box-${which}`);
  let drag = null;
  el.addEventListener("pointerdown", (e) => {
    if (!cropGeom) return;
    e.preventDefault();
    e.stopPropagation();
    el.setPointerCapture(e.pointerId);
    el.classList.add("dragging");
    drag = { x: e.clientX, y: e.clientY, r: { ...layout[which] }, resize: !!e.target.closest(".handle") };
  });
  el.addEventListener("pointermove", (e) => {
    if (!drag) return;
    const dx = (e.clientX - drag.x) / cropGeom.w, dy = (e.clientY - drag.y) / cropGeom.h;
    const r = drag.r;
    if (drag.resize) {
      // Width follows the mouse; height follows from the locked shape. Anchored at the top-left.
      const W = video.videoWidth, H = video.videoHeight, aspect = partAspect(which);
      let wN = Math.max(0.05, r.w + dx);
      wN = Math.min(wN, 1 - r.x, ((1 - r.y) * H * aspect) / W);
      layout[which] = { x: r.x, y: r.y, w: wN, h: (wN * W) / aspect / H };
    } else {
      layout[which] = { ...r, x: Math.min(Math.max(r.x + dx, 0), 1 - r.w), y: Math.min(Math.max(r.y + dy, 0), 1 - r.h) };
    }
    placeRect(el, layout[which]);
  });
  const end = () => {
    if (!drag) return;
    drag = null;
    el.classList.remove("dragging");
    saveLayout();
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);
}

$("#layout-mode").addEventListener("click", (e) => {
  const b = e.target.closest("button[data-mode]");
  if (!b || b.dataset.mode === layout.mode) return;
  layout.mode = b.dataset.mode;
  syncLayoutControls();
  layoutCrop();
  saveLayout();
});

$("#split").addEventListener("input", (e) => {
  layout.split = Number(e.target.value) / 100;
  $("#split-val").textContent = `${e.target.value}%`;
  // Each part's shape depends on the split, so refit both boxes around their centres.
  layout.cam = fitRect(layout.cam, partAspect("cam"));
  layout.content = fitRect(layout.content, partAspect("content"));
  layoutCrop();
});
$("#split").addEventListener("change", saveLayout);

// ---------- live 9:16 preview ----------

const preview = $("#preview");
const pctx = preview.getContext("2d");

function drawPart(r, aspect, dy, dh) {
  const W = video.videoWidth, H = video.videoHeight;
  const f = fitRect(r, aspect);
  pctx.drawImage(video, f.x * W, f.y * H, f.w * W, f.h * H, 0, dy, preview.width, dh);
}

function drawPreview() {
  requestAnimationFrame(drawPreview);
  if (!video.videoWidth || video.readyState < 2 || !preview.offsetParent) return;
  const pw = preview.width, ph = preview.height;
  pctx.fillStyle = "#000";
  pctx.fillRect(0, 0, pw, ph);
  if (layout.mode === "split" && layout.cam && layout.content) {
    const topH = Math.round(ph * layout.split);
    drawPart(layout.cam, partAspect("cam"), 0, topH);
    drawPart(layout.content, partAspect("content"), topH, ph - topH);
  } else {
    const W = video.videoWidth, H = video.videoHeight;
    const c = clipById(selectedId);
    const cx = liveCropX ?? c?.crop_x ?? 0.5;
    if (W / H > 9 / 16) {
      const cw = (H * 9) / 16;
      const x = Math.min(Math.max(cx * W - cw / 2, 0), W - cw);
      pctx.drawImage(video, x, 0, cw, H, 0, 0, pw, ph);
    } else {
      const ch = (W * 16) / 9;
      pctx.drawImage(video, 0, (H - ch) / 2, W, ch, 0, 0, pw, ph);
    }
  }
}
requestAnimationFrame(drawPreview);

// ---------- toolbar ----------

$("#play").addEventListener("click", () => ws?.playPause());

$("#zoom").addEventListener("input", (e) => {
  if (!ws) return;
  const max = 200; // px per second when fully zoomed in
  const px = fitPx * Math.pow(max / fitPx, Number(e.target.value) / 100);
  ws.zoom(px);
});

$("#add-here").addEventListener("click", () => {
  if (!ws) return;
  const t = ws.getCurrentTime();
  const dur = ws.getDuration();
  createClip(t, Math.min(dur, t + 30));
});

$("#rerun").addEventListener("click", async () => {
  if (!confirm("Ask Gemini to pick clips again? AI clips you haven't edited will be replaced. Clips you made or edited are kept.")) return;
  const btn = $("#rerun");
  btn.disabled = true;
  try {
    job = await api(`/api/jobs/${jobId}/analyze`, { method: "POST" });
    $("#ai-msg").classList.remove("hidden");
    $("#ai-msg").textContent = "Gemini is picking clips…";
    while (isBusy(job.status)) {
      await new Promise((r) => setTimeout(r, 2000));
      job = await api(`/api/jobs/${jobId}`);
    }
    clips = await api(`/api/jobs/${jobId}/clips`);
    if (!clipById(selectedId)) selectedId = null;
    ensurePolling();
    addAllRegions();
    renderList();
    renderDetail();
    layoutCrop();
    showAiMessage();
    if (!job.ai_error) toast(`Gemini suggested ${clips.filter((c) => c.origin === "ai").length} clips`);
  } catch (e) {
    toast(e.message, true);
  } finally {
    btn.disabled = false;
  }
});

document.addEventListener("keydown", (e) => {
  if (e.code !== "Space" || !ws) return;
  if (e.target.closest("input, textarea, select, button, [contenteditable]")) return;
  e.preventDefault();
  ws.playPause();
});

init();
