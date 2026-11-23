import { api, toast, fmtTime, esc, STATUS, isBusy } from "/common.js";

const $ = (s) => document.querySelector(s);
let pollTimer;

// ---------- setup checks ----------
async function loadChecks() {
  try {
    const h = await api("/api/health");
    const problems = h.checks.filter((c) => !c.ok);
    $("#checks-card").classList.toggle("hidden", problems.length === 0);
    $("#checks").innerHTML = h.checks.map((c) => `
      <div class="check">
        <span class="dot ${c.level}"></span>
        <div><div>${esc(c.label)}</div>${c.fix ? `<div class="muted small">${fixHtml(c.fix)}</div>` : ""}</div>
      </div>`).join("");
  } catch (e) {
    toast(`Could not load setup checks: ${e.message}`, true);
  }
}
// Show install commands as copyable code.
const fixHtml = (fix) => esc(fix).replace(/(brew install [\w-]+|winget install [\w.]+)/g, "<code>$1</code>");

// ---------- add video ----------
document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $("#url-form").classList.toggle("hidden", b.dataset.tab !== "url");
    $("#file-form").classList.toggle("hidden", b.dataset.tab !== "file");
  })
);

$("#url-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = e.submitter;
  btn.disabled = true;
  try {
    await api("/api/jobs", { method: "POST", body: { url: $("#url").value } });
    $("#url").value = "";
    loadJobs();
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
  }
});

$("#file-form").addEventListener("submit", (e) => {
  e.preventDefault();
  const file = $("#file").files[0];
  if (!file) return;
  const btn = e.submitter;
  const bar = $("#upload-bar");
  const form = new FormData();
  form.append("file", file);
  // XHR (not fetch) so we get upload progress for big files.
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs/upload");
  xhr.upload.onprogress = (ev) => {
    if (ev.lengthComputable) bar.firstElementChild.style.width = `${(ev.loaded / ev.total) * 100}%`;
  };
  xhr.onload = () => {
    btn.disabled = false;
    bar.classList.add("hidden");
    if (xhr.status >= 200 && xhr.status < 300) {
      $("#file").value = "";
      loadJobs();
    } else {
      let msg = "Upload failed";
      try { msg = JSON.parse(xhr.responseText).detail || msg; } catch {}
      toast(msg, true);
    }
  };
  xhr.onerror = () => { btn.disabled = false; bar.classList.add("hidden"); toast("Upload failed", true); };
  btn.disabled = true;
  bar.classList.remove("hidden");
  bar.firstElementChild.style.width = "0";
  xhr.send(form);
});

// ---------- job list ----------
function jobHtml(j) {
  const st = STATUS[j.status] || { label: j.status, cls: "" };
  const name = j.title || j.url || `Video ${j.id}`;
  const busy = isBusy(j.status);
  const pct = j.status === "queued" ? 0 : Math.round((j.progress || 0) * 100);
  const actions = [];
  if (j.status === "ready") actions.push(`<a class="btn sm primary" href="/editor.html?job=${j.id}">Open editor</a>`);
  if (j.status === "error") actions.push(`<button class="btn sm" data-act="retry" data-id="${j.id}">Retry</button>`);
  if (!["downloading", "transcribing", "analyzing"].includes(j.status))
    actions.push(`<button class="btn sm danger" data-act="delete" data-id="${j.id}">Delete</button>`);
  let msg = "";
  if (j.status === "error" && j.message) msg = `<div class="msg notice err">${esc(j.message)}</div>`;
  else if (j.status === "ready" && j.ai_error) msg = `<div class="msg notice warn">${esc(j.ai_error)}</div>`;
  else if (j.message) msg = `<div class="msg notice warn">${esc(j.message)}</div>`;
  return `
    <div class="job">
      <div style="min-width:0">
        <div class="title" title="${esc(name)}">${esc(name)}</div>
        <div class="meta">
          <span class="pill ${st.cls}">${st.label}${busy && pct ? ` · ${pct}%` : ""}</span>
          ${j.duration ? `<span>${fmtTime(j.duration)}</span>` : ""}
          ${j.status === "ready" ? `<span>${j.clip_count} clip${j.clip_count === 1 ? "" : "s"}</span>` : ""}
          <span>${new Date(j.created_at).toLocaleString()}</span>
        </div>
      </div>
      <div class="actions">${actions.join("")}</div>
      ${busy ? `<div class="bar"><i style="width:${pct}%"></i></div>` : ""}
      ${msg}
    </div>`;
}

async function loadJobs() {
  clearTimeout(pollTimer);
  try {
    const jobs = await api("/api/jobs");
    $("#jobs").innerHTML = jobs.length
      ? jobs.map(jobHtml).join("")
      : `<div class="empty">No videos yet. Paste a YouTube link above to start.</div>`;
    if (jobs.some((j) => isBusy(j.status))) pollTimer = setTimeout(loadJobs, 2000);
  } catch (e) {
    toast(`Could not load videos: ${e.message}`, true);
    pollTimer = setTimeout(loadJobs, 5000);
  }
}

$("#jobs").addEventListener("click", async (e) => {
  const b = e.target.closest("button[data-act]");
  if (!b) return;
  const id = b.dataset.id;
  try {
    if (b.dataset.act === "delete") {
      if (!confirm("Delete this video, its transcript and all its clips?")) return;
      await api(`/api/jobs/${id}`, { method: "DELETE" });
    } else if (b.dataset.act === "retry") {
      await api(`/api/jobs/${id}/retry`, { method: "POST" });
    }
    loadJobs();
  } catch (err) {
    toast(err.message, true);
  }
});

loadChecks();
loadJobs();
