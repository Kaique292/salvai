const QUALITIES = {
  MP4: [
    ["max", "Máxima"],
    ["1080", "1080p"],
    ["720", "720p"],
    ["480", "480p"],
  ],
  MP3: [
    ["max", "Máxima"],
    ["320", "320 kbps"],
    ["192", "192 kbps"],
    ["128", "128 kbps"],
  ],
};
const $ = (s) => document.querySelector(s);
const SAVE_ICON = '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>';
let format = "MP4";
let tab = "downloads";
let lastFiles = "";
let lastDownloads = "";
const seenItems = new Set();

const escapeHtml = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
const fileUrl = (path, download) => `/api/file?path=${encodeURIComponent(path)}${download ? "&dl=1" : ""}`;

function setFormat(value) {
  format = value;
  $("#format").dataset.value = value;
  document.querySelectorAll("#format button").forEach((b) => b.classList.toggle("active", b.dataset.value === value));
  $("#quality").innerHTML = QUALITIES[value].map(([v, label]) => `<option value="${v}">${label}</option>`).join("");
}
document
  .querySelectorAll("#format button")
  .forEach((b) => b.addEventListener("click", () => setFormat(b.dataset.value)));
setFormat("MP4");

function setOnline(ok, computer) {
  $("#offline").classList.toggle("show", !ok);
  $("#link-state").classList.toggle("ok", ok);
  $("#computer").textContent = ok ? `Conectado ao ${computer}` : "Desconectado";
}

async function api(path, options) {
  const res = await fetch(path, { cache: "no-store", ...options });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "Algo deu errado");
  return data;
}

function statusLine(d) {
  switch (d.status) {
    case "done":
      return `<small class="done">Pronto no PC · ${escapeHtml(d.format)} ${escapeHtml(d.quality)}</small>`;
    case "error":
      return `<small class="error">${escapeHtml(d.error)}</small>`;
    case "downloading":
      return `<small>Baixando no PC · ${d.progress}%</small><div class="bar"><span style="width:${d.progress}%"></span></div>`;
    case "processing":
      return `<small>Finalizando…</small><div class="bar"><span style="width:100%"></span></div>`;
    case "paused":
      return `<small>Pausado · ${d.progress}%</small>`;
    default:
      return `<small>Na fila · ${escapeHtml(d.format)} ${escapeHtml(d.quality)}</small>`;
  }
}

function renderDownloads(downloads) {
  const key = JSON.stringify(downloads);
  if (key === lastDownloads) return;
  lastDownloads = key;
  const el = $("#downloads");
  if (!downloads.length) {
    el.innerHTML = '<div class="empty">Nenhum download ainda. Cole um link acima.</div>';
    return;
  }
  el.innerHTML = downloads
    .slice()
    .reverse()
    .map((d) => {
      const thumb = d.thumb ? `<img src="${escapeHtml(d.thumb)}" alt="" />` : `<span class="icon">${SAVE_ICON}</span>`;
      const save =
        d.status === "done" && d.file
          ? `<a class="save" href="${fileUrl(d.file, true)}" download>${SAVE_ICON}Salvar</a>`
          : "";
      const fresh = !seenItems.has(d.id);
      seenItems.add(d.id);
      return `<div class="item${fresh ? " new" : ""}">${thumb}<div class="meta"><strong>${escapeHtml(d.title || d.url)}</strong>${statusLine(d)}</div>${save}</div>`;
    })
    .join("");
}

function renderFiles(files) {
  const key = JSON.stringify(files);
  if (key === lastFiles) return;
  lastFiles = key;
  const el = $("#files");
  if (!files.length) {
    el.innerHTML = '<div class="empty">A pasta de downloads do PC ainda está vazia.</div>';
    return;
  }
  el.innerHTML = files
    .map((f) => {
      const where = [f.folder, `${f.size_mb} MB`].filter(Boolean).join(" · ");
      return `<div class="item"><a class="icon" href="${fileUrl(f.path, false)}">${f.kind === "audio" ? "♪" : "▶"}</a><div class="meta"><strong>${escapeHtml(f.name)}</strong><small>${escapeHtml(where)}</small></div><a class="save" href="${fileUrl(f.path, true)}" download>${SAVE_ICON}Salvar</a></div>`;
    })
    .join("");
}

async function refresh() {
  try {
    const state = await api("/api/state");
    setOnline(true, state.computer);
    renderDownloads(state.downloads);
    if (tab === "files") renderFiles((await api("/api/files")).files);
  } catch {
    setOnline(false);
  }
}

$("#add-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const btn = $("#add-btn");
  const msg = $("#form-msg");
  btn.disabled = true;
  try {
    await api("/api/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: $("#url").value.trim(), format, quality: $("#quality").value }),
    });
    $("#url").value = "";
    msg.className = "form-msg ok";
    msg.textContent = "Enviado! O download começou no computador.";
    refresh();
  } catch (err) {
    msg.className = "form-msg error";
    msg.textContent = err.message;
  } finally {
    btn.disabled = false;
  }
});

document.querySelectorAll(".tabs button").forEach((b) =>
  b.addEventListener("click", () => {
    tab = b.dataset.tab;
    document.querySelectorAll(".tabs button").forEach((x) => x.classList.toggle("active", x === b));
    $("#downloads").hidden = tab !== "downloads";
    $("#files").hidden = tab !== "files";
    refresh();
  }),
);

if (/iPhone|iPad/.test(navigator.userAgent)) $("#ios-tip").classList.add("show");
refresh();
setInterval(refresh, 2000);
