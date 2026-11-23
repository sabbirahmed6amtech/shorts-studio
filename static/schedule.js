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

function row(c) {
  const [label, cls] = LABEL[c.yt_status] || [c.yt_status, ""];
  const live = c.yt_status === "scheduled" && new Date(c.yt_publish_at) <= new Date();
  const time = c.yt_publish_at ? when(c.yt_publish_at) : c.yt_uploaded_at ? when(c.yt_uploaded_at) : "–";
  const links = c.yt_video_id
    ? `<a href="https://youtube.com/shorts/${c.yt_video_id}" target="_blank" rel="noopener">Watch</a> ·
       <a href="https://studio.youtube.com/video/${c.yt_video_id}/edit" target="_blank" rel="noopener">Studio</a>`
    : "";
  return `
    <tr>
      <td>${time}${c.yt_publish_at ? "" : ` <span class="muted small">(immediately)</span>`}</td>
      <td><b>${esc(c.title) || '<span class="muted">Untitled</span>'}</b>
        <div class="muted small"><a href="/editor.html?job=${c.job_id}">${esc(c.job_title || "Video")}</a></div>
        ${c.yt_status === "error" ? `<div class="small" style="color:var(--err)">${esc(c.yt_error)}</div>` : ""}</td>
      <td><span class="pill ${cls}">${live ? "Live" : label}${c.yt_status === "uploading" ? ` ${Math.round((c.yt_progress || 0) * 100)}%` : ""}</span></td>
      <td class="small">${links}</td>
    </tr>`;
}

function table(list, empty) {
  if (!list.length) return `<div class="empty">${empty}</div>`;
  return `<div class="table-wrap"><table class="sched">
    <thead><tr><th>Publish time</th><th>Short</th><th>Status</th><th></th></tr></thead>
    <tbody>${list.map(row).join("")}</tbody></table></div>`;
}

async function load() {
  clearTimeout(timer);
  try {
    const all = await api("/api/schedule");
    const now = new Date();
    const upcoming = all
      .filter((c) => ["queued", "uploading"].includes(c.yt_status) || (c.yt_status === "scheduled" && new Date(c.yt_publish_at) > now))
      .sort((a, b) => new Date(a.yt_publish_at || 0) - new Date(b.yt_publish_at || 0));
    const past = all.filter((c) => !upcoming.includes(c));
    document.getElementById("upcoming").innerHTML = table(upcoming,
      'Nothing scheduled. Open a video and press <b>Schedule</b> on a clip, or <b>Schedule all</b>.');
    document.getElementById("past").innerHTML = table(past, "Nothing uploaded yet.");
    if (all.some((c) => ["queued", "uploading"].includes(c.yt_status))) timer = setTimeout(load, 3000);
  } catch (e) {
    toast(e.message, true);
  }
}

load();
