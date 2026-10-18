const QUALITIES = {
  MP4: [
    ["Máxima", "Melhor"],
    ["2160p (4K)", "4K"],
    ["1440p", "2K"],
    ["1080p", "Full HD"],
    ["720p", "HD"],
    ["480p", "SD"],
    ["360p", "SD"],
  ],
  MP3: [
    ["Máxima", "Melhor"],
    ["320 kbps", "Alta"],
    ["256 kbps", "Alta"],
    ["192 kbps", "Média"],
    ["128 kbps", "Leve"],
  ],
};
const CIRC = 2 * Math.PI * 21;
const PENDING = new Set(["setup", "queued", "fetching", "downloading", "processing", "paused"]);

const $ = (s) => document.querySelector(s);
const input = $("#link-input");
const grid = $("#grid");
const tpl = $("#card-tpl");
const cards = new Map();
let fmt = "MP4";

const api = () => window.pywebview.api;

function setFormat(value) {
  fmt = value;
  $("#format").dataset.value = value;
  document.querySelectorAll("#format button").forEach((b) => b.classList.toggle("active", b.dataset.value === value));
  quality.setOptions(QUALITIES[value], value);
  queueMicrotask(() => refreshApplyAll());
}
const quality = (() => {
  const root = $("#quality"),
    trigger = root.querySelector(".dd-trigger"),
    menu = root.querySelector(".dd-menu");
  const check = '<svg class="check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  let options = [],
    value = null,
    active = 0;

  const render = () => {
    menu.innerHTML = options
      .map(
        ([label, tag], i) =>
          (i === 1 ? '<div class="dd-sep"></div>' : "") +
          `<button class="dd-option${label === value ? " selected" : ""}${i === active ? " active" : ""}" data-i="${i}" role="option">
        ${check}<span class="label">${label}</span><span class="tag">${tag}</span></button>`,
      )
      .join("");
    const cur = options.find((o) => o[0] === value);
    root.querySelector(".dd-value").textContent = value;
    root.querySelector(".dd-tag").textContent = cur ? cur[1] : "";
  };
  const open = () => {
    active = Math.max(
      0,
      options.findIndex((o) => o[0] === value),
    );
    render();
    root.classList.add("open");
    trigger.setAttribute("aria-expanded", "true");
  };
  const close = () => {
    root.classList.remove("open");
    trigger.setAttribute("aria-expanded", "false");
  };
  const pick = (i) => {
    value = options[i][0];
    render();
    close();
    trigger.focus();
    root.dispatchEvent(new Event("change"));
  };

  trigger.addEventListener("click", () => (root.classList.contains("open") ? close() : open()));
  menu.addEventListener("click", (e) => {
    const b = e.target.closest(".dd-option");
    if (b) pick(+b.dataset.i);
  });
  menu.addEventListener("mousemove", (e) => {
    const b = e.target.closest(".dd-option");
    if (b && +b.dataset.i !== active) {
      active = +b.dataset.i;
      menu.querySelectorAll(".dd-option").forEach((o, i) => o.classList.toggle("active", i === active));
    }
  });
  document.addEventListener("mousedown", (e) => {
    if (!root.contains(e.target)) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
  root.addEventListener("keydown", (e) => {
    const isOpen = root.classList.contains("open");
    if (e.key === "Escape") return close();
    if (["ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      if (!isOpen) return open();
      active = (active + (e.key === "ArrowDown" ? 1 : -1) + options.length) % options.length;
      render();
    } else if ((e.key === "Enter" || e.key === " ") && isOpen) {
      e.preventDefault();
      pick(active);
    }
  });

  return {
    get value() {
      return value;
    },
    setOptions(opts, fmt) {
      options = opts;
      value = opts[0][0];
      root.dataset.fmt = fmt;
      render();
    },
  };
})();

document
  .querySelectorAll("#format button")
  .forEach((b) => b.addEventListener("click", () => setFormat(b.dataset.value)));
setFormat("MP4");

const URL_RE = /https?:\/\/[^\s"'<>]+/gi;
const ID_RE = /(?:v=|youtu\.be\/|shorts\/|live\/|embed\/)([\w-]{11})/;
const YT_RE = /^https?:\/\/(?:[\w-]+\.)?(?:youtube\.com|youtu\.be)\//i;
const youtubeId = (url) => (YT_RE.test(url) ? url.match(ID_RE)?.[1] : null);
const queueEl = $("#queue"),
  list = $("#queue-list"),
  linkBox = $("#link-box");
const pending = new Map();
const seen = new Set();
let msgTimer;

function findUrls(text) {
  return [...new Set((text.match(URL_RE) || []).map((u) => u.replace(/[.,;)\]]+$/, "")))];
}
function videoKey(url) {
  const yt = youtubeId(url);
  if (yt) return yt;
  try {
    const u = new URL(url);
    const keepQuery = u.pathname === "/" || /watch|video\.php|story\.php/.test(u.pathname);
    return (
      u.host.replace(/^(www|m)\./, "") +
      u.pathname.replace(/\/$/, "") +
      (keepQuery ? u.search : "")
    ).toLowerCase();
  } catch {
    return url;
  }
}
function showMsg(text, kind = "error") {
  const el = $("#link-msg");
  el.querySelector("span").textContent = text;
  el.className = `link-msg show ${kind}`;
  clearTimeout(msgTimer);
  msgTimer = setTimeout(() => el.classList.remove("show"), 2600);
}
function shakeInput() {
  linkBox.classList.remove("shake");
  void linkBox.offsetWidth;
  linkBox.classList.add("shake");
  input.focus();
}

function addLinks(text) {
  const urls = findUrls(text);
  if (!urls.length) {
    if (text.trim()) {
      shakeInput();
      showMsg("Isso não parece um link");
    }
    return 0;
  }
  let added = 0,
    dupes = 0;
  for (const url of urls) {
    const key = videoKey(url);
    seen.add(key);
    const existing = [...pending.entries()].find(([u]) => videoKey(u) === key);
    if (existing) {
      dupes++;
      const li = existing[1];
      li.classList.remove("flash");
      void li.offsetWidth;
      li.classList.add("flash");
      continue;
    }
    pending.set(url, createLinkItem(url));
    added++;
  }
  if (dupes && !added) showMsg(dupes > 1 ? "Esses links já estão na lista" : "Esse link já está na lista", "info");
  else if (dupes) showMsg(`${added} adicionado(s) · ${dupes} já estava(m) na lista`, "info");
  if (added) queueEl.classList.remove("collapsed");
  refreshQueue();
  return added;
}

function createLinkItem(url) {
  const id = youtubeId(url);
  const li = document.createElement("li");
  li.className = "q-item loading entering";
  li.innerHTML = `
    <div class="q-row">
      <img class="q-thumb" alt="" draggable="false">
      <div class="q-meta"><div class="q-title">Carregando…</div><div class="q-sub"></div></div>
      <button class="q-cfg" title="Trocar formato e qualidade deste link"></button>
      <button class="q-remove" title="Remover da lista"><svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg></button>
    </div>`;
  const img = li.querySelector(".q-thumb");
  img.addEventListener("load", () => img.classList.remove("pending"));
  img.addEventListener("error", () => {
    img.classList.remove("pending");
    img.removeAttribute("src");
    refreshQueue();
  });
  if (id) img.classList.add("pending");
  if (id) img.src = `https://i.ytimg.com/vi/${id}/mqdefault.jpg`;
  setItemConfig(li, fmt, quality.value);
  li.querySelector(".q-cfg").addEventListener("click", (e) => cfgPop.open(li, e.currentTarget));
  li.querySelector(".q-sub").textContent = url.replace(/^https?:\/\/(www\.)?/, "");
  li.querySelector(".q-remove").addEventListener("click", () => removeLink(url));
  list.appendChild(li);
  requestAnimationFrame(() => requestAnimationFrame(() => li.classList.remove("entering")));
  list.scrollTo({ top: list.scrollHeight, behavior: "smooth" });

  peekInto(li, url);
  return li;
}

function peekInto(li, url) {
  const id = youtubeId(url),
    img = li.querySelector(".q-thumb");
  li.classList.add("loading");
  li.classList.remove("warn");
  li.querySelector(".q-login")?.remove();
  api()
    .peek(url)
    .then((info) => {
      li.classList.remove("loading");
      const title = li.querySelector(".q-title"),
        sub = li.querySelector(".q-sub");
      if (info?.error) {
        li.classList.add("warn");
        title.textContent = `Link do ${info.site}`;
        sub.textContent = info.error;
        sub.title = info.error;
        li.dataset.loginSite = info.login_site || "";
        if (info.login_site) {
          const b = document.createElement("button");
          b.className = "q-login";
          b.textContent = "Conectar";
          b.addEventListener("click", () => accounts.open(info.login_site));
          li.querySelector(".q-remove").before(b);
        }
      } else {
        title.textContent = info?.title || url;
        title.title = info?.title || url;
        sub.textContent = [info?.site, info?.author].filter(Boolean).join(" · ") || sub.textContent;
        if (!id && info?.thumb) {
          img.classList.add("pending");
          img.src = info.thumb;
        }
      }
      refreshQueue();
    });
}

function removeLink(url) {
  const li = pending.get(url);
  if (!li) return;
  pending.delete(url);
  li.classList.add("leaving");
  setTimeout(() => li.remove(), 300);
  refreshQueue();
}

function refreshQueue() {
  const n = pending.size;
  refreshApplyAll();
  queueEl.classList.toggle("has-links", n > 0);
  $("#queue-n").textContent = n;
  $("#queue-word").textContent = n === 1 ? "link" : "links";
  const thumbs = [...pending.values()]
    .slice(0, 4)
    .map((li) => li.querySelector(".q-thumb").src)
    .filter(Boolean);
  const stack = $("#queue-stack");
  stack.innerHTML = thumbs.map((s) => `<img src="${s}" alt="">`).join("");
  stack.style.width =
    queueEl.classList.contains("collapsed") && thumbs.length ? `${28 + (thumbs.length - 1) * 19}px` : "0px";
}

$("#queue-toggle").addEventListener("click", () => {
  const collapsed = queueEl.classList.toggle("collapsed");
  $("#queue-toggle").setAttribute("aria-expanded", String(!collapsed));
  refreshQueue();
});

function setSuggested(on) {
  linkBox.classList.toggle("suggested", on);
}
async function checkClipboard() {
  if (input.value.trim()) return;
  let text = "";
  try {
    text = await api().paste();
  } catch {
    return;
  }
  const url = findUrls(text || "").find((u) => !seen.has(videoKey(u)));
  if (!url || input.value.trim()) return;
  if (!(await api().check_url(url)) || input.value.trim()) return;
  seen.add(videoKey(url));
  input.value = url;
  setSuggested(true);
}
window.addEventListener("focus", checkClipboard);
input.addEventListener("input", () => setSuggested(false));

function commitInput() {
  setSuggested(false);
  if (!input.value.trim()) return 0;
  const hadUrls = findUrls(input.value).length;
  const added = addLinks(input.value);
  if (hadUrls) input.value = "";
  return added || hadUrls;
}
input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.ctrlKey) {
    e.preventDefault();
    commitInput();
  }
});
input.addEventListener("paste", (e) => {
  const text = e.clipboardData.getData("text");
  if (findUrls(text).length) {
    e.preventDefault();
    const extra = linkBox.classList.contains("suggested") ? "" : input.value;
    setSuggested(false);
    addLinks(extra + " " + text);
    input.value = "";
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && e.ctrlKey) {
    e.preventDefault();
    startDownload();
  }
});
$("#add").addEventListener("click", () => {
  if (!input.value.trim()) {
    shakeInput();
    showMsg("Cole um link primeiro");
    return;
  }
  commitInput();
  input.focus();
});
$("#paste").addEventListener("click", async () => {
  const text = (await api().paste()).trim();
  if (!text) return showMsg("A área de transferência está vazia");
  if (!findUrls(text).length) {
    shakeInput();
    return showMsg("O que está copiado não é um link do YouTube");
  }
  addLinks(text);
  input.focus();
});
$("#clear").addEventListener("click", () => {
  [...pending.keys()].forEach((u) => removeLink(u));
  input.value = "";
  setSuggested(false);
  input.focus();
});

$("#folder").addEventListener("click", async () => {
  const path = await api().choose_folder();
  if (path) $("#folder-path").textContent = path;
});

$("#theme").addEventListener("click", (e) => {
  const root = document.documentElement;
  const next = root.dataset.theme === "dark" ? "light" : "dark";
  const r = e.currentTarget.getBoundingClientRect();
  const x = r.left + r.width / 2,
    y = r.top + r.height / 2;
  const radius = Math.hypot(Math.max(x, innerWidth - x), Math.max(y, innerHeight - y));
  const apply = () => {
    root.dataset.theme = next;
  };
  api().set_theme(next);
  if (!document.startViewTransition) return apply();
  const vt = document.startViewTransition(apply);
  vt.ready.then(() => {
    root.animate(
      { clipPath: [`circle(0px at ${x}px ${y}px)`, `circle(${radius}px at ${x}px ${y}px)`] },
      { duration: 550, easing: "cubic-bezier(.4,0,.2,1)", pseudoElement: "::view-transition-new(root)" },
    );
  });
});

async function startDownload() {
  commitInput();
  const urls = [...pending.keys()];
  if (!urls.length) {
    shakeInput();
    showMsg("Adicione pelo menos um link");
    return;
  }
  const items = urls.map((url) => ({
    url,
    fmt: pending.get(url).dataset.fmt,
    quality: pending.get(url).dataset.quality,
  }));
  const added = await api().add_items(items);
  if (added) urls.forEach((u) => removeLink(u));
}
$("#download").addEventListener("click", startDownload);
$("#clear-done").addEventListener("click", async () => {
  const removed = await api().clear_done();
  removed.forEach(removeCard);
});

function fmtDuration(s) {
  if (!s) return "";
  s = Math.round(s);
  const h = Math.floor(s / 3600),
    m = Math.floor((s % 3600) / 60),
    sec = s % 60;
  return (h ? `${h}:${String(m).padStart(2, "0")}` : m) + ":" + String(sec).padStart(2, "0");
}

function statusText(it) {
  const pct = `${Math.floor((it.progress || 0) * 100)}%`;
  switch (it.status) {
    case "queued":
      return `Na fila · ${it.quality}`;
    case "setup":
      return "Preparando o app (só na 1ª vez)…";
    case "fetching":
      return "Obtendo informações…";
    case "downloading": {
      const parts = [pct];
      if (it.speed) parts.push(`${(it.speed / 1048576).toFixed(1)} MB/s`);
      if (it.eta) parts.push(`${Math.floor(it.eta / 60)}:${String(Math.floor(it.eta % 60)).padStart(2, "0")} restante`);
      return "Baixando · " + parts.join(" · ");
    }
    case "processing":
      return it.fmt === "MP3" ? "Convertendo para MP3…" : "Finalizando…";
    case "paused":
      return `Pausado · ${pct}`;
    case "done":
      return `Salvo! · ${it.quality}`;
    case "error":
      return it.error || "Não deu certo";
  }
  return "";
}

function createCard(it) {
  const el = tpl.content.firstElementChild.cloneNode(true);
  el.dataset.id = it.id;
  el.dataset.fmt = it.fmt;
  el.querySelector(".badge").textContent = it.fmt;
  const img = el.querySelector("img");
  img.addEventListener("load", () => img.classList.add("loaded"));
  el.querySelector(".remove").addEventListener("click", (e) => {
    e.stopPropagation();
    api().remove(it.id);
    removeCard(it.id);
  });
  el.querySelector(".action").addEventListener("click", (e) => {
    e.stopPropagation();
    if (el.classList.contains("done")) api().open_item(it.id);
    else api().retry(it.id);
  });
  el.querySelector(".card-login").addEventListener("click", (e) => {
    e.stopPropagation();
    accounts.open(e.currentTarget.dataset.site);
  });
  grid.appendChild(el);
  cards.set(it.id, el);
  return el;
}

function removeCard(id) {
  const el = cards.get(id);
  if (!el) return;
  cards.delete(id);
  el.animate(
    [
      { opacity: 1, transform: "scale(1)" },
      { opacity: 0, transform: "scale(.9)" },
    ],
    { duration: 180, easing: "ease-in" },
  ).onfinish = () => {
    el.remove();
    refresh();
  };
}

function update(it) {
  const el = cards.get(it.id) || createCard(it);
  el.className = "card " + it.status + (["setup", "fetching", "processing"].includes(it.status) ? " busy" : "");
  el.querySelector(".title").textContent = it.title || it.url;
  el.querySelector(".title").title = it.title || it.url;
  el.querySelector(".status").textContent = statusText(it);
  el.querySelector(".dur").textContent = fmtDuration(it.duration);
  el.querySelector(".status").title = it.status === "error" ? it.error || "" : "";
  el.querySelector(".site").textContent = it.site && it.site !== "YouTube" ? it.site : "";
  const tags = [];
  if (it.folder)
    tags.push(
      `<span class="tag-folder" title="Salvo em ${escapeHtml(it.folder)}"><svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>${escapeHtml(it.folder.split("/").pop())}</span>`,
    );
  if (it.source === "claude") tags.push(`<span class="tag-claude" title="Download pedido pelo Claude">✦ Claude</span>`);
  if (it.source === "phone")
    tags.push(`<span class="tag-phone" title="Download pedido pelo celular">📱 Celular</span>`);
  el.querySelector(".card-tags").innerHTML = tags.join("");
  el.querySelector(".overlay span").textContent =
    it.status === "paused"
      ? "❚❚  Pausado"
      : ["login", "noaccess"].includes(it.error_kind)
        ? "🔒  Precisa de login"
        : "Falhou · clique em ↻";
  const loginBtn = el.querySelector(".card-login");
  loginBtn.hidden = !(it.status === "error" && it.login_site);
  loginBtn.dataset.site = it.login_site || "";
  const img = el.querySelector("img");
  if (it.thumb && img.dataset.src !== it.thumb) {
    img.dataset.src = it.thumb;
    img.src = it.thumb;
  }
  const progress = it.status === "done" ? 1 : it.progress || 0;
  el.querySelector(".bar").style.strokeDashoffset = CIRC * (1 - progress);
  refresh();
}

function refresh() {
  let n = 0;
  for (const el of grid.children) {
    const pending = [...el.classList].some((c) => PENDING.has(c));
    el.querySelector(".pos").textContent = pending ? `#${++n}` : "";
  }
  $("#count").textContent = grid.children.length || "";
  $(".downloads").classList.toggle("has-items", grid.children.length > 0);
}

Sortable.create(grid, {
  animation: 220,
  easing: "cubic-bezier(.4,0,.2,1)",
  delay: 150,
  delayOnTouchOnly: false,
  forceFallback: true,
  fallbackTolerance: 4,
  filter: ".remove, .action, .card-login",
  preventOnFilter: false,
  onEnd: () => {
    refresh();
    api().reorder([...grid.children].map((el) => el.dataset.id));
  },
});

window.app = {
  update,
  accountsChanged(data) {
    accounts.changed(data);
  },
};
window.addEventListener("pywebviewready", async () => {
  const state = await api().init();
  document.documentElement.dataset.theme = state.theme;
  $("#version").textContent = `v${state.version}`;
  $("#st-version").textContent = `Salvaí ${state.version} · motor ${state.engine_version}`;
  await api().ready();
  setTimeout(() => document.body.classList.add("ready"), 30);
  $("#folder-path").textContent = state.out_dir;
  state.items.forEach(update);
  refresh();
  input.focus();
  checkClipboard();
});

const storage = (() => {
  const modal = $("#storage-modal"),
    listEl = $("#st-list"),
    clearBtn = $("#st-clear");
  const COLORS = { webview: "#3E63DD", ytdlp: "#F76B15", temp: "#FFB224", components: "#8E4EC6" };
  const check = '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
  let info = null,
    shownTotal = 0,
    lastFocus = null;
  const selected = new Set();

  const fmtSize = (b) => {
    if (b < 1024 * 1024) return `${Math.round(b / 1024)} KB`;
    if (b < 1024 ** 3) return `${(b / 1048576).toFixed(b < 10 * 1048576 ? 1 : 0)} MB`;
    return `${(b / 1024 ** 3).toFixed(2)} GB`;
  };

  function animateTotal(to) {
    const from = shownTotal,
      start = performance.now(),
      el = $("#st-total");
    const step = (now) => {
      const t = Math.max(0, Math.min(1, (now - start) / 600)),
        e = 1 - Math.pow(1 - t, 3);
      shownTotal = from + (to - from) * e;
      el.textContent = fmtSize(shownTotal);
      if (t < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function selectedBytes() {
    return info ? info.categories.filter((c) => selected.has(c.key)).reduce((s, c) => s + c.size, 0) : 0;
  }

  function updateButton() {
    const bytes = selectedBytes();
    clearBtn.disabled = !info || bytes === 0;
    clearBtn.textContent = bytes ? `Limpar selecionados · ${fmtSize(bytes)}` : "Nada para limpar";
    $("#st-bar")
      .querySelectorAll("span")
      .forEach((s) => s.classList.toggle("off", !selected.has(s.dataset.key)));
  }

  function renderSkeleton() {
    listEl.innerHTML = [
      "Cache da interface",
      "Dados do YouTube",
      "Sobras de aberturas anteriores",
      "Componentes do app",
    ]
      .map(
        (n) =>
          `<div class="st-row loading"><span class="st-check"></span><span class="st-name">${n}</span><span class="st-size">…</span></div>`,
      )
      .join("");
  }

  function render() {
    listEl.innerHTML = "";
    for (const c of info.categories) {
      const row = document.createElement("label");
      row.className = "st-row" + (selected.has(c.key) ? " checked" : "");
      row.style.setProperty("--c", COLORS[c.key]);
      row.innerHTML = `
        <span class="st-check">${check}</span>
        <span class="st-name"><span class="st-dot"></span>${c.name}</span>
        <span class="st-size">${fmtSize(c.size)}</span>
        <span class="st-desc">${c.desc}</span>`;
      row.addEventListener("click", (e) => {
        e.preventDefault();
        selected.has(c.key) ? selected.delete(c.key) : selected.add(c.key);
        row.classList.toggle("checked", selected.has(c.key));
        updateButton();
      });
      listEl.appendChild(row);
    }
    const bar = $("#st-bar");
    if (!bar.children.length) {
      bar.innerHTML = info.categories
        .map((c) => `<span data-key="${c.key}" style="--c:${COLORS[c.key]};flex-grow:0"></span>`)
        .join("");
      void bar.offsetWidth;
    }
    for (const c of info.categories) {
      const seg = bar.querySelector(`[data-key="${c.key}"]`);
      seg.style.flexGrow = info.total ? c.size / info.total : 0;
      seg.title = `${c.name}: ${fmtSize(c.size)}`;
    }
    animateTotal(info.total);
    updateButton();
  }

  async function load() {
    info = await api().storage_info();
    if (!selected.size && !load.done) info.categories.forEach((c) => c.default && selected.add(c.key));
    load.done = true;
    render();
  }

  function open() {
    lastFocus = document.activeElement;
    $("#st-result").classList.remove("show");
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    if (!info) renderSkeleton();
    clearBtn.disabled = true;
    load();
    setTimeout(() => modal.querySelector(".modal-close").focus(), 50);
  }

  function close() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    lastFocus?.focus();
  }

  async function clear() {
    const keys = [...selected];
    clearBtn.disabled = true;
    clearBtn.innerHTML = '<span class="spin"></span> Limpando…';
    const res = await api().clear_storage(keys);
    info = res.info;
    render();
    const box = $("#st-result");
    box.firstElementChild.innerHTML = `<div class="st-result-box"><strong>✓ ${fmtSize(res.freed)} liberados</strong>${res.notes.map((n) => `<p>${n}</p>`).join("")}</div>`;
    box.classList.add("show");
  }

  $("#storage-btn").addEventListener("click", open);
  modal.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
  clearBtn.addEventListener("click", clear);
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Escape" && modal.classList.contains("open")) {
        e.stopPropagation();
        close();
      }
    },
    true,
  );

  return { open, close };
})();

const accounts = (() => {
  const modal = $("#accounts-modal"),
    listEl = $("#acc-list");
  const COLORS = { instagram: "#E1306C", tiktok: "#111", x: "#3a3a42", facebook: "#1877F2" };
  const LETTERS = { instagram: "IG", tiktok: "TT", x: "X", facebook: "f" };
  let data = null,
    focusSite = null,
    lastFocus = null,
    browser = null;

  const fmtDate = (ts) => new Date(ts * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });

  function render() {
    listEl.innerHTML = "";
    for (const s of data.sites) {
      const row = document.createElement("div");
      row.className =
        "acc-row" + (s.connected ? " connected" : "") + (s.busy ? " busy" : "") + (s.key === focusSite ? " focus" : "");
      const status = s.busy
        ? "Uma janela do site abriu. Entre normalmente — ela fecha sozinha."
        : s.connected
          ? `Conectado · desde ${fmtDate(s.since)}${s.source && s.source !== "app" ? ` (importado do ${s.source})` : ""}`
          : "Não conectado";
      row.innerHTML = `
        <span class="acc-logo" style="background:${COLORS[s.key]}">${LETTERS[s.key]}</span>
        <span class="acc-meta"><strong>${s.name}</strong><small>${status}</small></span>
        ${
          s.busy
            ? '<span class="acc-wait"><span class="spin"></span>Aguardando login…</span>'
            : s.connected
              ? '<button class="ghost acc-btn" data-act="logout">Sair</button>'
              : '<button class="acc-btn primary-soft" data-act="login">Entrar</button>'
        }`;
      row.querySelector("[data-act]")?.addEventListener("click", async (e) => {
        if (e.currentTarget.dataset.act === "login") {
          await api().login(s.key);
        } else {
          data = await api().logout(s.key);
          render();
        }
      });
      listEl.appendChild(row);
    }
    const bwrap = $("#acc-import");
    bwrap.hidden = !data.browsers.length;
    if (data.browsers.length) {
      if (!browser || !data.browsers.some((b) => b.key === browser)) browser = data.browsers[0].key;
      $("#acc-browsers").innerHTML = data.browsers
        .map((b) => `<button class="chip${b.key === browser ? " active" : ""}" data-b="${b.key}">${b.name}</button>`)
        .join("");
      $("#acc-browsers")
        .querySelectorAll(".chip")
        .forEach((c) =>
          c.addEventListener("click", () => {
            browser = c.dataset.b;
            render();
          }),
        );
    }
  }

  function showResult(text, ok) {
    const box = $("#acc-result");
    box.firstElementChild.innerHTML = `<div class="acc-result-box ${ok ? "ok" : "warn"}">${text}</div>`;
    box.classList.add("show");
  }

  async function open(site = null) {
    focusSite = site;
    lastFocus = document.activeElement;
    $("#acc-result").classList.remove("show");
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    data = await api().accounts();
    render();
    setTimeout(() => modal.querySelector(".modal-close").focus(), 50);
  }

  function close() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    focusSite = null;
    lastFocus?.focus();
  }

  function changed(payload) {
    data = payload.accounts;
    if (modal.classList.contains("open")) render();
    if (payload.connected) {
      const name = data.sites.find((s) => s.key === payload.connected)?.name;
      showResult(`✓ Conta do ${name} conectada. Os links que precisavam de login vão ser tentados de novo.`, true);
      for (const [id, el] of cards) {
        if (el.classList.contains("error") && el.querySelector(".card-login").dataset.site === payload.connected)
          api().retry(id);
      }
      for (const [url, li] of pending) if (li.dataset.loginSite === payload.connected) peekInto(li, url);
    }
  }

  $("#acc-import-btn").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span> Importando…';
    const res = await api().import_browser(browser);
    btn.disabled = false;
    btn.textContent = "Importar";
    data = res.accounts;
    render();
    showResult(res.message, res.ok);
    if (res.ok) for (const [url, li] of pending) if (li.dataset.loginSite) peekInto(li, url);
  });
  $("#accounts-btn").addEventListener("click", () => open());
  modal.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Escape" && modal.classList.contains("open")) {
        e.stopPropagation();
        close();
      }
    },
    true,
  );

  return { open, close, changed };
})();

const SHORT_Q = { Máxima: "Máx", "2160p (4K)": "4K" };
const shortQuality = (q) => SHORT_Q[q] || q.replace(" kbps", "k");

function setItemConfig(li, f, q) {
  li.dataset.fmt = f;
  li.dataset.quality = q;
  const b = li.querySelector(".q-cfg");
  b.textContent = `${f} · ${shortQuality(q)}`;
  b.dataset.fmt = f;
  b.classList.remove("pop");
  void b.offsetWidth;
  b.classList.add("pop");
}

function refreshApplyAll() {
  const btn = $("#apply-all");
  if (!btn) return;
  const q = quality.value;
  const differs = [...pending.values()].some((li) => li.dataset.fmt !== fmt || li.dataset.quality !== q);
  btn.classList.toggle("show", pending.size > 0 && differs);
  btn.querySelector("b").textContent = `${fmt} · ${shortQuality(q)}`;
  btn.dataset.fmt = fmt;
}
$("#apply-all").addEventListener("click", () => {
  for (const li of pending.values()) setItemConfig(li, fmt, quality.value);
  refreshApplyAll();
  showMsg(`Todos os links agora vão em ${fmt} · ${quality.value}`, "info");
});
$("#quality").addEventListener("change", refreshApplyAll);

const cfgPop = (() => {
  const pop = $("#cfg-pop");
  let li = null,
    anchor = null;

  function render() {
    const f = li.dataset.fmt,
      q = li.dataset.quality;
    pop.querySelector(".segmented").dataset.value = f;
    pop.querySelectorAll(".segmented button").forEach((b) => b.classList.toggle("active", b.dataset.value === f));
    pop.querySelector(".cfg-list").innerHTML = QUALITIES[f]
      .map(
        ([label, tag]) =>
          `<button class="dd-option${label === q ? " selected" : ""}" data-q="${label}">
        <svg class="check" viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>
        <span class="label">${label}</span><span class="tag">${tag}</span></button>`,
      )
      .join("");
    pop.dataset.fmt = f;
  }

  function place() {
    const r = anchor.getBoundingClientRect(),
      w = pop.offsetWidth,
      h = pop.offsetHeight;
    let top = r.bottom + 6;
    if (top + h > innerHeight - 8) top = r.top - h - 6;
    pop.style.top = `${Math.max(8, top)}px`;
    pop.style.left = `${Math.min(innerWidth - w - 8, Math.max(8, r.right - w))}px`;
    pop.style.transformOrigin = top < r.top ? "bottom right" : "top right";
  }

  function open(item, btn) {
    if (li === item && pop.classList.contains("open")) return close();
    li = item;
    anchor = btn;
    render();
    pop.classList.add("open");
    place();
  }
  function close() {
    pop.classList.remove("open");
    li = null;
  }

  pop.querySelectorAll(".segmented button").forEach((b) =>
    b.addEventListener("click", () => {
      if (b.dataset.value === li.dataset.fmt) return;
      setItemConfig(li, b.dataset.value, "Máxima");
      render();
      refreshApplyAll();
    }),
  );
  pop.querySelector(".cfg-list").addEventListener("click", (e) => {
    const opt = e.target.closest(".dd-option");
    if (!opt) return;
    setItemConfig(li, li.dataset.fmt, opt.dataset.q);
    refreshApplyAll();
    close();
  });
  document.addEventListener("mousedown", (e) => {
    if (pop.classList.contains("open") && !pop.contains(e.target) && !e.target.closest(".q-cfg")) close();
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") close();
  });
  list.addEventListener("scroll", () => close());
  window.addEventListener("resize", () => close());
  return { open, close };
})();

function escapeHtml(s) {
  return String(s).replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c],
  );
}

const notices = (() => {
  const el = $("#notice");
  const title = $("#notice-title");
  const desc = $("#notice-desc");
  const action = $("#notice-action");
  const later = $("#notice-later");
  const queue = [];
  let current = null;

  function render() {
    later.hidden = false;
    later.textContent = "Depois";
    action.disabled = false;
    if (current.kind === "engine") {
      title.textContent = "Motor de download novo disponível";
      desc.textContent = `Os sites mudam o tempo todo: a versão ${current.latest} mantém os downloads funcionando (você está na ${current.current}).`;
      action.textContent = "Atualizar";
    } else {
      title.textContent = `Salvaí ${current.latest} disponível`;
      desc.innerHTML = `Você está na versão ${escapeHtml(current.current)}. A atualização leva menos de um minuto · <a href="#" class="notice-link">ver novidades</a>`;
      desc.querySelector(".notice-link").addEventListener("click", (e) => {
        e.preventDefault();
        api().open_release(current.url);
      });
      action.textContent = "Atualizar agora";
    }
  }

  async function updateApp() {
    action.disabled = true;
    action.innerHTML = '<span class="spin"></span> Baixando 0%';
    later.hidden = true;
    const result = await api().update_app();
    if (result.ok) {
      current.stage = "ready";
      title.textContent = `Salvaí ${result.version} instalado`;
      desc.textContent = "Reabrindo o app na versão nova…";
      action.innerHTML = '<span class="spin"></span> Reiniciando';
      setTimeout(() => api().restart_app(), 1200);
      return;
    }
    action.disabled = false;
    later.hidden = false;
    desc.textContent = result.message;
    if (result.url) {
      current.url = result.url;
      current.stage = "manual";
      action.textContent = "Abrir página";
    } else {
      action.textContent = "Tentar de novo";
    }
  }

  function next() {
    current = queue.shift() || null;
    if (!current) {
      el.classList.remove("show");
      return;
    }
    render();
    el.classList.add("show");
  }

  async function updateEngine() {
    action.disabled = true;
    action.innerHTML = '<span class="spin"></span> Atualizando…';
    later.hidden = true;
    const result = await api().update_engine();
    action.disabled = false;
    later.hidden = false;
    if (result.ok) {
      current.stage = "ready";
      title.textContent = `Motor ${result.version} pronto`;
      desc.textContent = "Reinicie o Salvaí para começar a usar. Se houver downloads em andamento, espere terminarem.";
      action.textContent = "Reiniciar agora";
    } else {
      desc.textContent = result.message;
      action.textContent = "Tentar de novo";
    }
  }

  action.addEventListener("click", () => {
    if (current.kind === "app" && current.stage === "manual") {
      api().open_release(current.url);
      next();
    } else if (current.kind === "app") {
      updateApp();
    } else if (current.stage === "ready") {
      api().restart_app();
    } else {
      updateEngine();
    }
  });
  later.addEventListener("click", () => {
    if (current.stage !== "ready") api().skip_update(current.kind, current.latest);
    next();
  });

  return {
    add(notice) {
      queue.push(notice);
      if (!current) next();
    },
  };
})();
window.app.updateAvailable = (notice) => notices.add(notice);
window.app.otaProgress = (pct) => {
  const action = $("#notice-action");
  if (action.disabled)
    action.innerHTML = `<span class="spin"></span> ${pct < 100 ? `Baixando ${pct}%` : "Instalando…"}`;
};

const phone = (() => {
  const modal = $("#phone-modal");
  const sw = $("#phone-switch");
  let timer = null;
  let lastFocus = null;
  let state = { on: false };

  function render() {
    sw.classList.toggle("on", state.on);
    $("#phone-btn").classList.toggle("on", state.on);
    $("#phone-on").classList.toggle("show", state.on);
    $("#phone-switch-hint").textContent = state.on
      ? "Ligado. Aponte a câmera do celular para o código."
      : "Desligado. Ligue para mostrar o QR code.";
    if (!state.on) return;
    if ($("#phone-qr").dataset.url !== state.url) {
      $("#phone-qr").innerHTML = state.qr;
      $("#phone-qr").dataset.url = state.url;
    }
    $("#phone-url").textContent = state.url;
    const net = state.network || {};
    let text = "Conecte o celular ao mesmo Wi-Fi do computador";
    if (net.kind === "wifi" && net.name) text = `Conecte o celular ao Wi-Fi «${net.name}», o mesmo do computador`;
    if (net.kind === "cabo") text = "O computador está no cabo: conecte o celular ao Wi-Fi do mesmo roteador";
    $("#net-text").textContent = text;
    $("#phone-warn").classList.toggle("show", !!net.public);
    $("#phone-devices").innerHTML = state.devices.length
      ? state.devices.map((d) => `<span class="device">● ${escapeHtml(d)} conectado</span>`).join("")
      : '<span class="waiting">Nenhum celular conectado ainda</span>';
    const others = state.others || [];
    $("#phone-others").classList.toggle("has", others.length > 0);
    $("#phone-others-list").innerHTML = others.map((u) => `<li>${escapeHtml(u)}</li>`).join("");
  }

  async function poll() {
    state = await api().phone_status();
    render();
  }

  function open() {
    lastFocus = document.activeElement;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    poll();
    clearInterval(timer);
    timer = setInterval(poll, 2000);
  }

  function close() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    clearInterval(timer);
    lastFocus?.focus();
  }

  sw.addEventListener("click", async (e) => {
    e.preventDefault();
    sw.classList.add("busy");
    state = state.on ? await api().phone_stop() : await api().phone_start();
    sw.classList.remove("busy");
    render();
  });
  $("#phone-copy").addEventListener("click", async (e) => {
    await navigator.clipboard.writeText(state.url);
    e.currentTarget.textContent = "Copiado!";
    setTimeout(() => (e.currentTarget.textContent = "Copiar"), 1500);
  });
  $("#phone-firewall").addEventListener("click", () => api().phone_allow_firewall());
  $("#phone-settings").addEventListener("click", () => api().open_network_settings());
  $("#phone-btn").addEventListener("click", open);
  modal.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
  document.addEventListener(
    "keydown",
    (e) => {
      if (e.key === "Escape" && modal.classList.contains("open")) {
        e.stopPropagation();
        close();
      }
    },
    true,
  );

  return {
    async sync() {
      state = await api().phone_status();
      render();
    },
  };
})();
window.app.phoneChanged = () => phone.sync();
