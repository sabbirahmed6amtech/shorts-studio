import { api, toast, esc } from "/common.js";

const when = (iso) => new Date(iso).toLocaleString([], { weekday: "short", dateStyle: "medium", timeStyle: "short" });
const LABEL = {
  queued: ["Waiting to upload", "busy"],
  uploading: ["Uploading", "busy"],
  scheduled: ["Scheduled", "ok"],
  published: ["Uploaded", "ok"],
  error: ["Failed", "err"],
};
let timer;

/** One entry per platform a clip was sent to. */
function entries(c) {
  const out = [];
  if (c.yt_status) out.push({ c, platform: "YouTube", status: c.yt_status, at: c.yt_publish_at, done: c.yt_uploaded_at,
    progress: c.yt_progress, error: c.yt_error, links: c.yt_video_id
      ? `<a href="https://youtube.com/shorts/${c.yt_video_id}" target="_blank" rel="noopener">Watch</a> ·
         <a href="https://studio.youtube.com/video/${c.yt_video_id}/edit" target="_blank" rel="noopener">Studio</a>` : "" });
  if (c.fb_status) out.push({ c, platform: "Facebook", status: c.fb_status, at: c.fb_publish_at, done: c.fb_uploaded_at,
    progress: c.fb_progress, error: c.fb_error, links: c.fb_video_id
      ? `<a href="https://www.facebook.com/reel/${c.fb_video_id}" target="_blank" rel="noopener">Open</a>` : "" });
  return out;
}

function row(e) {
  const c = e.c;
  const [label, cls] = LABEL[e.status] || [e.status, ""];
  const live = e.status === "scheduled" && new Date(e.at) <= new Date();
  const time = e.at ? when(e.at) : e.done ? when(e.done) : "–";
  return `
    <tr>
      <td>${time}${e.at ? "" : ` <span class="muted small">(immediately)</span>`}</td>
      <td><b>${esc(c.title) || '<span class="muted">Untitled</span>'}</b>
        <div class="muted small"><a href="/editor.html?job=${c.job_id}">${esc(c.job_title || "Video")}</a></div>
        ${e.status === "error" ? `<div class="small" style="color:var(--err)">${esc(e.error)}</div>` : ""}</td>
      <td class="small">${e.platform}</td>
      <td><span class="pill ${cls}">${live ? "Live" : label}${e.status === "uploading" ? ` ${Math.round((e.progress || 0) * 100)}%` : ""}</span></td>
      <td class="small">${e.links}</td>
    </tr>`;
}

function table(list, empty) {
  if (!list.length) return `<div class="empty">${empty}</div>`;
  return `<div class="table-wrap"><table class="sched">
    <thead><tr><th>Publish time</th><th>Short</th><th>Platform</th><th>Status</th><th></th></tr></thead>
    <tbody>${list.map(row).join("")}</tbody></table></div>`;
}

async function load() {
  clearTimeout(timer);
  try {
    const all = (await api("/api/schedule")).flatMap(entries);
    const now = new Date();
    const upcoming = all
      .filter((e) => ["queued", "uploading"].includes(e.status) || (e.status === "scheduled" && new Date(e.at) > now))
      .sort((a, b) => new Date(a.at || 0) - new Date(b.at || 0));
    const past = all.filter((e) => !upcoming.includes(e))
      .sort((a, b) => new Date(b.at || b.done || 0) - new Date(a.at || a.done || 0));
    document.getElementById("upcoming").innerHTML = table(upcoming,
      'Nothing scheduled. Open a video and press <b>Schedule</b> on a clip, or <b>Schedule all</b>.');
    document.getElementById("past").innerHTML = table(past, "Nothing posted yet.");
    if (all.some((e) => ["queued", "uploading"].includes(e.status))) timer = setTimeout(load, 3000);
  } catch (e) {
    toast(e.message, true);
  }
}

load();
