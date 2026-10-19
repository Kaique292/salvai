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
const MORE_ICON =
  '<svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1.2"/><circle cx="12" cy="12" r="1.2"/><circle cx="19" cy="12" r="1.2"/></svg>';
let format = "MP4";
let tab = "downloads";
let lastFiles = "";
let lastDownloads = "";
let currentFiles = [];
const seenItems = new Set();

const escapeHtml = (s) =>
  String(s ?? "").replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
const fileUrl = (id, download) => `/api/file?id=${encodeURIComponent(id)}${download ? "&dl=1" : ""}`;

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

function setOnline(ok, computer, revoked) {
  $("#offline").classList.toggle("show", !ok);
  if (revoked) {
    $("#offline strong").textContent = "Desconectado pelo computador";
    $("#offline span").textContent = revoked;
  }
  $("#link-state").classList.toggle("ok", ok);
  $("#computer").textContent = ok ? `Conectado ao ${computer}` : "Desconectado";
}

async function api(path, options = {}) {
  const headers = options.method ? { "X-Salvai": "1", ...options.headers } : options.headers;
  const res = await fetch(path, { cache: "no-cache", ...options, headers });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(data.error || "Algo deu errado");
    error.revoked = !!data.revoked;
    error.status = res.status;
    error.body = data;
    throw error;
  }
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
        d.status === "done" && d.file_id
          ? `<a class="save" href="${fileUrl(d.file_id, true)}" download>${SAVE_ICON}Salvar</a>`
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
    el.innerHTML =
      '<div class="empty">Nada salvo pelo Salvaí ainda. Os vídeos e músicas que ele baixar aparecem aqui.</div>';
    return;
  }
  currentFiles = files;
  const count = files.length === 1 ? "1 arquivo salvo pelo Salvaí" : `${files.length} arquivos salvos pelo Salvaí`;
  el.innerHTML =
    `<div class="files-head"><span>${count}</span><button type="button" class="link-btn" data-clear>Limpar lista</button></div>` +
    files
      .map((f) => {
        const where = [f.folder, `${f.size_mb} MB`].filter(Boolean).join(" · ");
        return `<div class="item"><button type="button" class="icon play" data-play="${escapeHtml(f.id)}" aria-label="Assistir no celular">${f.kind === "audio" ? "♪" : "▶"}</button><div class="meta"><strong>${escapeHtml(f.name)}</strong><small>${escapeHtml(where)}</small></div><a class="save" href="${fileUrl(f.id, true)}" download>${SAVE_ICON}Salvar</a><button type="button" class="more" data-more="${escapeHtml(f.id)}" aria-label="Mais opções">${MORE_ICON}</button></div>`;
      })
      .join("");
}

const sheet = (() => {
  const root = $("#sheet");
  let hideTimer;

  function open(title, desc, actions) {
    clearTimeout(hideTimer);
    $("#sheet-title").textContent = title;
    $("#sheet-desc").textContent = desc;
    $("#sheet-actions").replaceChildren(
      ...actions.map(({ label, danger, run }) => {
        const b = document.createElement("button");
        b.type = "button";
        b.textContent = label;
        if (danger) b.className = "danger";
        b.addEventListener("click", run);
        return b;
      }),
    );
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add("show"));
  }

  function close() {
    root.classList.remove("show");
    hideTimer = setTimeout(() => (root.hidden = true), 250);
  }

  root.querySelector("[data-close]").addEventListener("click", close);
  return { open, close };
})();

let toastTimer;
function toast(text, error = false) {
  const el = $("#toast");
  el.textContent = text;
  el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2800);
}

async function fileAction(path, id, done) {
  sheet.close();
  try {
    await api(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id }),
    });
    toast(done);
  } catch (err) {
    toast(err.message, true);
  }
  lastFiles = "";
  refresh();
}

function confirmTrash(file) {
  sheet.open(
    "Apagar do computador?",
    `"${file.name}" vai para a Lixeira do computador. Dá para recuperar por lá se mudar de ideia.`,
    [
      {
        label: "Apagar",
        danger: true,
        run: () => fileAction("/api/files/trash", file.id, "Arquivo enviado para a Lixeira do computador."),
      },
      { label: "Cancelar", run: sheet.close },
    ],
  );
}

const player = (() => {
  const root = $("#player");
  const video = $("#player-video");
  const error = $("#player-error");
  let opening = 0;

  async function open(file) {
    const ticket = ++opening;
    $("#player-title").textContent = file.name;
    error.textContent = "";
    root.classList.toggle("audio", file.kind === "audio");
    root.hidden = false;
    requestAnimationFrame(() => root.classList.add("show"));
    // O PC diz se o celular toca o arquivo como está; se não, manda uma versão convertida na hora.
    const how = await api(`/api/play?id=${encodeURIComponent(file.id)}`).catch(() => ({ direct: true }));
    if (ticket !== opening) return;
    video.src = how.stream || fileUrl(file.id, false);
    video.play().catch(() => {});
  }

  function close() {
    opening++;
    video.pause();
    video.removeAttribute("src");
    video.load();
    root.classList.remove("show");
    root.hidden = true;
  }

  video.addEventListener("error", () => {
    if (!video.getAttribute("src")) return;
    error.textContent =
      "O navegador do celular não consegue tocar esse formato. Feche e toque em Salvar para abrir no app de vídeos.";
  });
  $("#player-close").addEventListener("click", close);
  return { open, close };
})();

function fileMenu(file) {
  sheet.open(file.name, "", [
    {
      label: file.kind === "audio" ? "Ouvir no celular" : "Assistir no celular",
      run: () => {
        sheet.close();
        player.open(file);
      },
    },
    {
      label: "Tirar da lista",
      run: () => fileAction("/api/files/forget", file.id, "Tirado da lista. O arquivo continua no computador."),
    },
    { label: "Apagar do computador", danger: true, run: () => confirmTrash(file) },
    { label: "Cancelar", run: sheet.close },
  ]);
}

function confirmClear() {
  sheet.open("Limpar a lista?", "Os arquivos somem só desta lista e continuam no computador.", [
    {
      label: "Limpar lista",
      danger: true,
      run: () => fileAction("/api/files/clear", "", "Lista limpa. Os arquivos continuam no computador."),
    },
    { label: "Cancelar", run: sheet.close },
  ]);
}

$("#files").addEventListener("click", (e) => {
  if (e.target.closest("[data-clear]")) return confirmClear();
  const target = e.target.closest("[data-more], [data-play]");
  const file = target && currentFiles.find((f) => f.id === (target.dataset.more || target.dataset.play));
  if (!file) return;
  if (target.dataset.play) player.open(file);
  else fileMenu(file);
});

let timer = null;
let busy = false;

function schedule(active) {
  clearTimeout(timer);
  timer = setTimeout(refresh, document.hidden ? 15000 : active ? 1500 : 5000);
}

async function refresh() {
  if (busy) return;
  busy = true;
  let active = false;
  try {
    const state = await api("/api/state");
    setOnline(true, state.computer);
    renderDownloads(state.downloads);
    active = state.downloads.some((d) => !["done", "error"].includes(d.status));
    if (tab === "files") renderFiles((await api("/api/files")).files);
  } catch (err) {
    setOnline(false, null, err.revoked && err.message);
  } finally {
    busy = false;
    schedule(active);
  }
}

document.addEventListener("visibilitychange", () => {
  if (document.hidden) return;
  refresh();
  sender.wake();
});

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

const sender = (() => {
  const tasks = [];
  let chunk = 4 << 20;
  let running = false;
  let wakeLock = null;
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  function size(bytes) {
    if (bytes < 1024 ** 2) return `${Math.ceil(bytes / 1024)} KB`;
    if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1).replace(".", ",")} MB`;
    return `${(bytes / 1024 ** 3).toFixed(2).replace(".", ",")} GB`;
  }

  function line(t) {
    const total = t.file.size;
    if (t.state === "done") return `<small class="done">No computador · ${size(total)}</small>`;
    if (t.state === "error") return `<small class="error">${escapeHtml(t.error)}</small>`;
    if (t.state !== "sending") return `<small>Na fila · ${size(total)}</small>`;
    const pct = total ? Math.floor((t.offset / total) * 100) : 100;
    return `<small>${size(t.offset)} de ${size(total)} · ${pct}%</small><div class="bar"><span style="width:${pct}%"></span></div>`;
  }

  function render() {
    const done = tasks.filter((t) => t.state === "done").length;
    const failed = tasks.filter((t) => t.state === "error").length;
    const busy = tasks.length - done - failed;
    let summary = done === 1 ? "1 arquivo enviado para o PC" : `${done} arquivos enviados para o PC`;
    if (failed) summary = failed === 1 ? "1 arquivo não foi enviado" : `${failed} arquivos não foram enviados`;
    if (busy) summary = `Enviando ${done + failed + 1} de ${tasks.length}…`;
    $("#send-panel").hidden = !tasks.length;
    $("#send-summary").textContent = summary;
    $("#send-keep").hidden = !busy;
    $("#send-clear").hidden = !!busy;
    $("#send-list").innerHTML = tasks
      .map((t, i) => {
        const retry =
          t.state === "error"
            ? `<button type="button" class="send-retry" data-retry="${i}">Tentar de novo</button>`
            : "";
        return `<div class="send-row"><div class="meta"><strong>${escapeHtml(t.file.name)}</strong>${line(t)}</div>${retry}</div>`;
      })
      .join("");
  }

  function hold(on) {
    if (!on) {
      wakeLock?.release().catch(() => {});
      wakeLock = null;
      return;
    }
    navigator.wakeLock?.request("screen").then(
      (lock) => (wakeLock = lock),
      () => {},
    );
  }

  async function plan(list) {
    for (let i = 0; i < list.length; i += 50) {
      const part = list.slice(i, i + 50);
      const reply = await api("/api/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ files: part.map((t) => ({ name: t.file.name, size: t.file.size })) }),
      });
      chunk = reply.chunk;
      reply.uploads.forEach((u, j) => Object.assign(part[j], { id: u.id, offset: u.offset, state: "waiting" }));
    }
  }

  async function prepare(list) {
    list.forEach((t) => Object.assign(t, { state: "planning", error: "" }));
    render();
    try {
      await plan(list);
    } catch (err) {
      list
        .filter((t) => t.state === "planning")
        .forEach((t) => Object.assign(t, { state: "error", error: err.message }));
    }
    render();
    pump();
  }

  async function send(t) {
    t.state = "sending";
    render();
    let failures = 0;
    while (t.offset < t.file.size) {
      try {
        const reply = await api(`/api/upload?t=${encodeURIComponent(t.id)}&offset=${t.offset}`, {
          method: "PUT",
          headers: { "Content-Type": "application/octet-stream" },
          body: t.file.slice(t.offset, Math.min(t.file.size, t.offset + chunk)),
        });
        t.offset = reply.received;
        failures = 0;
      } catch (err) {
        if (err.status === 409) {
          t.offset = err.body.received;
          await wait(300);
        } else if (err.status || ++failures > 20) {
          t.state = "error";
          t.error = err.status ? err.message : "A conexão com o computador caiu. Confira o Wi-Fi.";
          return render();
        } else {
          await wait(1500);
        }
      }
      render();
    }
    t.state = "done";
    render();
  }

  async function pump() {
    if (running) return;
    running = true;
    hold(true);
    let next;
    while ((next = tasks.find((t) => t.state === "waiting"))) await send(next);
    running = false;
    hold(false);
  }

  $("#send-btn").addEventListener("click", () => $("#send-input").click());
  $("#send-input").addEventListener("change", (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (!files.length) return;
    const fresh = files.map((file) => ({ file, id: "", offset: 0 }));
    tasks.push(...fresh);
    prepare(fresh);
  });
  $("#send-list").addEventListener("click", (e) => {
    const button = e.target.closest("[data-retry]");
    if (button) prepare([tasks[button.dataset.retry]]);
  });
  $("#send-clear").addEventListener("click", () => {
    tasks.length = 0;
    render();
  });
  window.addEventListener("beforeunload", (e) => {
    if (running) e.preventDefault();
  });

  return {
    wake() {
      if (running) hold(true);
    },
  };
})();

if (/iPhone|iPad/.test(navigator.userAgent)) $("#ios-tip").classList.add("show");
refresh();
