// Background jobs: header indicator + panel, kept live by SSE `job` events; Cancel posts to the jobs route.
import { getJSON, postJSON } from "./api.js";
import { $, esc, toast } from "./dom.js";

const jobs = new Map();

function row(j) {
  const pct = j.progress == null ? "" : ` ${Math.round(j.progress * 100)}%`;
  const eta = j.eta_s ? ` · ~${Math.ceil(j.eta_s)} s left` : "";
  const detail = j.status === "running" ? `${esc(j.stage)}${pct}${eta}${j.cancel_requested ? " · cancelling" : ""}`
    : j.status === "done" ? "done" : `${esc(j.status)}: ${esc(j.error || "")}`;
  const cancel = j.status === "running" && !j.cancel_requested
    ? `<button class="mini ghost" data-cancel="${esc(j.id)}">Cancel</button>` : "";
  return `<div class="job ${esc(j.status)}"><div class="job-text"><div class="job-label">${esc(j.label)}</div>` +
    `<div class="job-detail">${detail}</div></div>${cancel}</div>`;
}

function render() {
  const list = [...jobs.values()].sort((a, b) => b.started - a.started);
  // Key off `status`, not `cancel_requested`: a job can end `status="done"` with
  // `cancel_requested=True` when cancel arrived after the last checkpoint, and must not read as "running".
  const running = list.filter(j => j.status === "running").length;
  $("jobs-count").textContent = running;
  $("jobs-btn").classList.toggle("busy", running > 0);
  $("jobs-list").innerHTML = list.length ? list.map(row).join("") : '<span class="empty">No jobs yet.</span>';
}

// Idempotent upsert by job.id: terminal events can arrive more than once.
export function onJob(job) {
  const before = jobs.get(job.id);
  jobs.set(job.id, job);
  render();
  const newlyEnded = !before || before.status === "running";
  if (newlyEnded && job.status === "failed") toast(`${job.label}: ${job.error}`);
}

export function openJobsPanel() { $("jobs-panel").classList.add("open"); }

export async function loadJobs() {
  for (const j of (await getJSON("/api/jobs")).jobs) jobs.set(j.id, j);
  render();
}

export function wireJobs() {
  $("jobs-btn").onclick = () => $("jobs-panel").classList.toggle("open");
  $("jobs-list").onclick = async e => {
    const id = e.target.dataset && e.target.dataset.cancel;
    if (!id) return;
    try { onJob(await postJSON(`/api/jobs/${encodeURIComponent(id)}/cancel`, {})); } catch (err) { toast(err.message); }
  };
}
