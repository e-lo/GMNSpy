// Fetch + SSE client for the workbench API. Every state change goes through dispatch().
async function readJSON(r) {
  const j = await r.json().catch(() => ({}));
  if (!r.ok) {
    // FastAPI's own 422 `detail` is an array of error objects, not a string;
    // stringify it so the toast shows something readable instead of "[object Object]".
    const detail = typeof j.detail === "string" ? j.detail : j.detail != null ? JSON.stringify(j.detail) : undefined;
    throw new Error(j.error || detail || r.statusText);
  }
  return j;
}

export const getJSON = path => fetch(path).then(readJSON);

export async function getBuffer(path) {
  const r = await fetch(path);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.arrayBuffer();
}

export async function dispatch(action) {
  const r = await fetch("/api/actions", {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(action),
  });
  return (await readJSON(r)).result;
}

export const netPath = (netId, rest) => `/api/n/${encodeURIComponent(netId)}/roadway/${rest}`;

export function subscribe(handlers) {
  const source = new EventSource("/api/events");
  for (const [type, fn] of Object.entries(handlers)) source.addEventListener(type, e => fn(JSON.parse(e.data)));
  return source;
}
