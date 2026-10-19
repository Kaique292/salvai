const $ = (s) => document.querySelector(s);
const OFFER_BATCH = 50;
const FILE_ICON =
  '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>';
const FOLDER_ICON =
  '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';

const local = new Map();
const downloads = new Map();
const selected = new Set();
let state = null;
let timer = null;
let misses = 0;
let uploading = false;
let toastTimer = null;
let drawn = "";

function escapeHtml(s) {
  return String(s).replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

function size(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${unit ? value.toFixed(value < 10 ? 1 : 0).replace(".", ",") : value} ${units[unit]}`;
}

function describe(item) {
  const count = item.kind === "folder" ? ` · ${item.count} ${item.count === 1 ? "arquivo" : "arquivos"}` : "";
  return `${size(item.size)}${count}`;
}

function percent(progress) {
  return progress.total ? Math.floor((progress.done / progress.total) * 100) : 100;
}

function toast(text, error = false) {
  const el = $("#toast");
  el.textContent = text;
  el.className = `toast show${error ? " error" : ""}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (el.className = "toast"), 3500);
}

function show(view) {
  document.querySelectorAll("[data-view]").forEach((el) => (el.hidden = el.dataset.view !== view));
  $("#leave").hidden = view !== "room" && view !== "wait";
}

async function call(path, options = {}) {
  const headers = { "X-Sala": "1", ...options.headers };
  if (typeof options.body === "string") headers["Content-Type"] = "application/json";
  const res = await fetch(path, { credentials: "same-origin", ...options, headers });
  let body = {};
  try {
    body = await res.json();
  } catch {
    body = {};
  }
  if (!res.ok) {
    const error = new Error(body.error || "Algo deu errado. Tente de novo.");
    error.status = res.status;
    error.body = body;
    throw error;
  }
  return body;
}

const post = (path, data) => call(path, { method: "POST", body: JSON.stringify(data) });

function setHost(name) {
  $("#host-label").textContent = name ? `Sala de ${name}` : "Sala de troca";
  $("#join-title").textContent = name ? `Entrar na sala de ${name}` : "Entrar na sala";
  $("#theirs-title").textContent = name ? `Arquivos de ${name}` : "Arquivos da sala";
}

function stop(text) {
  clearInterval(timer);
  timer = null;
  $("#link-state").classList.remove("ok");
  $("#gone-text").textContent = text;
  show("gone");
}

async function boot() {
  try {
    const name = localStorage.getItem("sala-name");
    if (name) $("#join-name").value = name;
  } catch {}
  $("#add-folder").hidden = !("webkitdirectory" in document.createElement("input"));
  let me;
  try {
    me = await call("/api/me");
  } catch {
    return stop("Não deu para falar com a sala. Confira o link e a sua internet.");
  }
  setHost(me.host);
  route(me.state);
}

function route(status) {
  if (status === "approved") return enter();
  if (status === "pending") return waitApproval();
  if (status === "revoked") return stop("Quem criou a sala não deixou você entrar ou tirou você dela.");
  show("join");
  $("#join-code").focus();
}

function waitApproval() {
  show("wait");
  clearInterval(timer);
  timer = setInterval(async () => {
    try {
      const me = await call("/api/me");
      if (me.state !== "pending") route(me.state);
    } catch {}
  }, 2000);
}

async function join(e) {
  e.preventDefault();
  const name = $("#join-name").value.trim();
  const msg = $("#join-msg");
  msg.textContent = "";
  $("#join-btn").disabled = true;
  try {
    localStorage.setItem("sala-name", name);
  } catch {}
  try {
    const result = await post("/api/join", { name, code: $("#join-code").value });
    route(result.state);
  } catch (error) {
    msg.textContent = error.message;
  }
  $("#join-btn").disabled = false;
}

function enter() {
  show("room");
  $("#link-state").classList.add("ok");
  clearInterval(timer);
  sync();
  timer = setInterval(sync, 1500);
}

async function sync() {
  try {
    state = await call("/api/state");
    misses = 0;
  } catch (error) {
    if (error.status === 403) return stop(error.message);
    misses++;
    if (misses >= 8) stop("A sala não responde mais. Ela pode ter sido fechada.");
    return;
  }
  setHost(state.host);
  render();
  pump();
}

function row(item, extra) {
  const li = document.createElement("li");
  li.className = "item";
  li.dataset.id = item.id;
  const risky = item.risky ? '<span class="risky">programa</span>' : "";
  li.innerHTML = `<span class="item-icon">${item.kind === "folder" ? FOLDER_ICON : FILE_ICON}</span><div class="item-meta"><div class="item-name"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong>${risky}</div><small>${escapeHtml(describe(item))}</small></div>`;
  extra(li, li.querySelector("small"));
  return li;
}

function progressInto(li, small, progress, labels) {
  if (!progress) return;
  const pct = percent(progress);
  if (progress.state === "done") {
    small.textContent = labels.done;
    small.className = "ok";
    return;
  }
  if (progress.state === "error") {
    small.textContent = progress.error || labels.error;
    small.className = "bad";
    return;
  }
  small.textContent = progress.state === "waiting" ? labels.waiting : `${labels.sending} ${pct}%`;
  li.querySelector(".item-meta").insertAdjacentHTML(
    "beforeend",
    `<div class="bar"><i style="width:${pct}%"></i></div>`,
  );
}

function render() {
  const ids = new Set(state.items.map((i) => i.id));
  selected.forEach((id) => ids.has(id) || selected.delete(id));
  $("#keep-open").hidden = !busy();
  buttons();
  const key = JSON.stringify([state.items, state.mine, [...downloads], [...local.keys()]]);
  if (key === drawn) return;
  drawn = key;
  const theirs = $("#theirs");
  theirs.replaceChildren(
    ...state.items.map((item) =>
      row(item, (li, small) => {
        const box = document.createElement("input");
        box.type = "checkbox";
        box.checked = selected.has(item.id);
        box.setAttribute("aria-label", `Selecionar ${item.name}`);
        box.addEventListener("change", () => {
          if (box.checked) selected.add(item.id);
          else selected.delete(item.id);
          buttons();
        });
        li.prepend(box);
        const btn = document.createElement("button");
        btn.className = "item-btn";
        btn.type = "button";
        btn.textContent = "Baixar";
        btn.addEventListener("click", () => download([item.id]));
        li.append(btn);
        progressInto(li, small, downloads.get(item.id), {
          done: "Baixado",
          error: "Não deu para baixar",
          waiting: "Na fila",
          sending: "Baixando",
        });
      }),
    ),
  );
  if (!state.items.length)
    theirs.innerHTML =
      '<li class="empty">Ainda não tem nada aqui. Os arquivos aparecem assim que forem adicionados.</li>';
  const mine = $("#mine");
  mine.replaceChildren(
    ...state.mine.map((item) =>
      row(item, (li, small) => {
        if (!item.progress) small.textContent = `${describe(item)} · esperando ser pedido`;
        progressInto(li, small, item.progress, {
          done: "Enviado",
          error: "Não deu para enviar",
          waiting: "Pedido, já vai começar",
          sending: "Enviando",
        });
        if (!local.has(item.id) && item.progress?.state !== "done") {
          small.textContent = "Adicione de novo para continuar enviando";
          small.className = "bad";
        }
        const btn = document.createElement("button");
        btn.className = "item-btn";
        btn.type = "button";
        btn.textContent = "Tirar";
        btn.addEventListener("click", () => remove(item.id));
        li.append(btn);
      }),
    ),
  );
  if (!state.mine.length) mine.innerHTML = '<li class="empty">Adicione arquivos ou pastas para mandar.</li>';
}

function busy() {
  const sending = state.requests.some((r) => local.has(r.item));
  return sending || [...downloads.values()].some((d) => d.state === "sending");
}

function buttons() {
  $("#get-selected").disabled = !selected.size;
  $("#get-all").disabled = !state.items.length;
}

function pump() {
  if (uploading) return;
  const req = state.requests.find((r) => local.has(r.item));
  if (!req) return;
  uploading = true;
  upload(req)
    .catch((error) => toast(error.message, true))
    .finally(() => {
      uploading = false;
    });
}

async function upload(req) {
  const file = local.get(req.item)[req.f];
  let offset = req.offset;
  while (offset < req.size) {
    const blob = file.slice(offset, Math.min(req.size, offset + state.chunk));
    try {
      const reply = await call(`/api/upload?t=${req.id}&offset=${offset}`, {
        method: "PUT",
        body: blob,
        headers: { "Content-Type": "application/octet-stream" },
      });
      offset = reply.received;
    } catch (error) {
      if (error.status !== 409) throw error;
      offset = error.body.received;
    }
  }
}

function group(files) {
  const folders = new Map();
  const items = [];
  for (const file of files) {
    const rel = file.webkitRelativePath || "";
    if (!rel.includes("/")) {
      items.push({ kind: "file", name: file.name, files: [file], rels: [file.name] });
      continue;
    }
    const top = rel.split("/")[0];
    if (!folders.has(top)) {
      const folder = { kind: "folder", name: top, files: [], rels: [] };
      folders.set(top, folder);
      items.push(folder);
    }
    folders.get(top).files.push(file);
    folders.get(top).rels.push(rel);
  }
  return items;
}

async function offer(files) {
  const items = group(files);
  try {
    for (let start = 0; start < items.length; start += OFFER_BATCH) {
      const batch = items.slice(start, start + OFFER_BATCH);
      const payload = batch.map((item) => ({
        kind: item.kind,
        name: item.name,
        files: item.files.map((f, i) => ({ rel: item.rels[i], size: f.size })),
      }));
      const { ids } = await post("/api/offer", { items: payload });
      ids.forEach((id, i) => local.set(id, batch[i].files));
    }
    toast(items.length === 1 ? "Adicionado à sala" : `${items.length} itens adicionados à sala`);
  } catch (error) {
    toast(error.message, true);
  }
  await sync();
}

async function remove(id) {
  try {
    await post("/api/unoffer", { id });
    local.delete(id);
  } catch (error) {
    toast(error.message, true);
  }
  await sync();
}

const answer = { resolve: null };

function ask() {
  const sheet = $("#sheet");
  sheet.hidden = false;
  return new Promise((resolve) => {
    answer.resolve = (value) => {
      sheet.hidden = true;
      resolve(value);
    };
  });
}

function link(href) {
  const a = document.createElement("a");
  a.href = href;
  a.download = "";
  document.body.append(a);
  a.click();
  a.remove();
}

async function download(ids) {
  const items = state.items.filter((i) => ids.includes(i.id));
  if (items.some((i) => i.risky) && !(await ask())) return;
  if (items.length === 1 && items[0].kind === "file") return link(`/api/file?item=${items[0].id}&f=0&dl=1`);
  if (!window.showDirectoryPicker) return link(`/api/zip?items=${items.map((i) => i.id).join(",")}`);
  let dir;
  try {
    dir = await window.showDirectoryPicker({ mode: "readwrite" });
  } catch {
    return;
  }
  for (const item of items) await saveItem(dir, item);
}

async function saveItem(dir, item) {
  const progress = { done: 0, total: item.size, state: "sending", error: "" };
  downloads.set(item.id, progress);
  render();
  try {
    const { files } = await call(`/api/files?item=${item.id}`);
    for (const [index, file] of files.entries()) await saveFile(dir, item, index, file, progress);
    progress.state = "done";
  } catch (error) {
    progress.state = "error";
    progress.error = error.message;
  }
  render();
}

async function saveFile(dir, item, index, file, progress) {
  const parts = file.rel.split("/");
  let folder = dir;
  for (const part of parts.slice(0, -1)) folder = await folder.getDirectoryHandle(part, { create: true });
  const handle = await folder.getFileHandle(parts.at(-1), { create: true });
  const existing = (await handle.getFile()).size;
  if (existing === file.size) {
    progress.done += file.size;
    return;
  }
  const start = existing < file.size ? existing : 0;
  const res = await fetch(`/api/file?item=${item.id}&f=${index}`, {
    credentials: "same-origin",
    headers: start ? { Range: `bytes=${start}-` } : {},
  });
  if (!res.ok) throw new Error(`Não deu para baixar ${parts.at(-1)}`);
  const offset = res.status === 206 ? start : 0;
  const writable = await handle.createWritable({ keepExistingData: offset > 0 });
  await writable.truncate(offset);
  await writable.seek(offset);
  progress.done += offset;
  const reader = res.body.getReader();
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    await writable.write(value);
    progress.done += value.length;
  }
  await writable.close();
}

async function leave() {
  try {
    await post("/api/leave", {});
  } catch {}
  stop("Você saiu da sala. Para voltar, abra o link de novo e digite o código.");
}

$("#join-form").addEventListener("submit", join);
$("#join-code").addEventListener("input", (e) => {
  const raw = e.target.value
    .toUpperCase()
    .replace(/[^A-Z0-9]/g, "")
    .slice(0, 6);
  e.target.value = raw.length > 3 ? `${raw.slice(0, 3)} ${raw.slice(3)}` : raw;
});
$("#leave").addEventListener("click", leave);
$("#add-files").addEventListener("click", () => $("#pick-files").click());
$("#add-folder").addEventListener("click", () => $("#pick-folder").click());
for (const id of ["#pick-files", "#pick-folder"]) {
  $(id).addEventListener("change", async (e) => {
    const files = [...e.target.files];
    e.target.value = "";
    if (files.length) await offer(files);
  });
}
$("#get-selected").addEventListener("click", () => download([...selected]));
$("#get-all").addEventListener("click", () => download(state.items.map((i) => i.id)));
document
  .querySelectorAll("[data-answer]")
  .forEach((el) => el.addEventListener("click", () => answer.resolve?.(el.dataset.answer === "yes")));
window.addEventListener("beforeunload", (e) => {
  if (state && busy()) e.preventDefault();
});

boot();
