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
const INFO_ICON = '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.5"/></svg>';

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
    root.querySelector(".dd-tag").textContent = cur[1];
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
    shakeInput();
    showMsg("Isso não parece um link");
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
  stack.replaceChildren(
    ...thumbs.map((src) => {
      const img = document.createElement("img");
      img.alt = "";
      img.src = src;
      return img;
    }),
  );
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
    return showMsg("O que está copiado não é um link");
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
  const COLORS = {
    webview: "#3E63DD",
    ytdlp: "#F76B15",
    temp: "#FFB224",
    components: "#8E4EC6",
    essential: "#6B6B76",
  };
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
    return info.categories.filter((c) => selected.has(c.key)).reduce((s, c) => s + c.size, 0);
  }

  function updateButton() {
    const bytes = selectedBytes();
    clearBtn.disabled = bytes === 0;
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
      "Componentes baixados",
      "Essenciais",
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
        <span class="st-name"><span class="st-dot"></span>${escapeHtml(c.name)}</span>
        <span class="st-size">${fmtSize(c.size)}</span>
        <span class="st-desc">${escapeHtml(c.desc)}</span>`;
      if (c.locked) row.classList.add("locked");
      row.addEventListener("click", (e) => {
        e.preventDefault();
        if (c.locked) return;
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
    box.firstElementChild.innerHTML = `<div class="st-result-box"><strong>✓ ${fmtSize(res.freed)} liberados</strong>${res.notes.map((n) => `<p>${escapeHtml(n)}</p>`).join("")}</div>`;
    box.classList.add("show");
  }

  async function checkNow() {
    const btn = $("#st-check");
    btn.disabled = true;
    btn.innerHTML = '<span class="spin"></span> Procurando…';
    const result = await api().check_updates_now();
    btn.disabled = false;
    if (result.found) {
      btn.textContent = "Procurar atualizações";
      return close();
    }
    btn.textContent = result.offline ? "Sem conexão. Tente de novo" : "Você já está na versão mais recente";
    setTimeout(() => (btn.textContent = "Procurar atualizações"), 3500);
  }

  $("#storage-btn").addEventListener("click", open);
  modal.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
  clearBtn.addEventListener("click", clear);
  $("#st-check").addEventListener("click", checkNow);
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
    box.firstElementChild.innerHTML = `<div class="acc-result-box ${ok ? "ok" : "warn"}">${escapeHtml(text)}</div>`;
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
    if (current.kind === "claude") {
      title.textContent = "Salvaí conectado ao Claude";
      desc.textContent = "Feche e abra o Claude Desktop para ele começar a buscar e baixar vídeos e músicas por aqui.";
      action.textContent = "Entendi";
      later.hidden = true;
    } else if (current.kind === "engine") {
      title.textContent = "Motor de download novo disponível";
      desc.textContent = `Os sites mudam o tempo todo: a versão ${current.latest} mantém os downloads funcionando (você está na ${current.current}).`;
      action.textContent = "Atualizar";
    } else {
      title.innerHTML = `Salvaí ${escapeHtml(current.latest)} disponível <button class="notice-info" title="O que muda nesta versão" aria-label="O que muda nesta versão">${INFO_ICON}</button>`;
      desc.innerHTML = `Você está na versão ${escapeHtml(current.current)}. A atualização leva menos de um minuto · <a href="#" class="notice-link">o que muda</a>`;
      const notice = current;
      const showNotes = (e) => {
        e.preventDefault();
        whatsNew.open(notice, () => current === notice && notice.stage !== "manual" && updateApp());
      };
      title.querySelector(".notice-info").addEventListener("click", showNotes);
      desc.querySelector(".notice-link").addEventListener("click", showNotes);
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
    if (current.kind === "claude") {
      next();
    } else if (current.kind === "app" && current.stage === "manual") {
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
      const same = (n) => n && n.kind === notice.kind && n.latest === notice.latest;
      if (same(current) || queue.some(same)) return;
      queue.push(notice);
      if (!current) next();
    },
  };
})();
window.app.updateAvailable = (notice) => notices.add(notice);

const whatsNew = (() => {
  const modal = $("#notes-modal");
  const body = $("#notes-body");
  let onUpdate = null;
  let lastFocus = null;
  let page = null;

  const fmtDate = (iso) => (iso ? iso.split("-").reverse().join("/") : "");

  function render(releases) {
    if (!releases.length) {
      body.innerHTML = '<p class="notes-empty">Nenhuma novidade registrada para essa versão.</p>';
      return;
    }
    body.innerHTML = releases
      .map((r) => {
        const sections = r.sections.length
          ? r.sections
              .map(
                (s) =>
                  `<h5>${escapeHtml(s.title)}</h5><ul>${s.items.map((i) => `<li>${escapeHtml(i)}</li>`).join("")}</ul>`,
              )
              .join("")
          : "<h5>Melhorias internas</h5>";
        return `<section class="notes-version"><h4>Versão ${escapeHtml(r.version)} <small>${escapeHtml(fmtDate(r.date))}</small></h4>${sections}</section>`;
      })
      .join("");
  }

  async function open(notice, update) {
    lastFocus = document.activeElement;
    onUpdate = update;
    $("#notes-title").textContent = `O que muda da ${notice.current} para a ${notice.latest}`;
    body.innerHTML = '<div class="notes-loading"><span class="spin"></span> Buscando as novidades…</div>';
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    const data = await api().release_notes();
    page = data.url;
    if (!data.ok) {
      body.innerHTML = '<p class="notes-empty">Não deu para buscar as novidades agora. Veja no GitHub.</p>';
      return;
    }
    render(data.releases);
  }

  function close() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    lastFocus?.focus();
  }

  modal.querySelectorAll("[data-close]").forEach((el) => el.addEventListener("click", close));
  $("#notes-github").addEventListener("click", () => page && api().open_release(page));
  $("#notes-update").addEventListener("click", () => {
    close();
    onUpdate?.();
  });
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
  return { open };
})();
window.app.otaProgress = (pct) => {
  const action = $("#notice-action");
  if (action.disabled)
    action.innerHTML = `<span class="spin"></span> ${pct < 100 ? `Baixando ${pct}%` : "Instalando…"}`;
};

function size(n) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = n;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit++;
  }
  return `${unit ? value.toFixed(value < 10 ? 1 : 0).replace(".", ",") : value} ${units[unit]}`;
}

const phone = (() => {
  const modal = $("#phone-modal");
  const sw = $("#phone-switch");
  let timer = null;
  let lastFocus = null;
  let state = { on: false };
  let confirming = null;
  let confirmTimer = null;

  const two = (n) => String(n).padStart(2, "0");
  function when(seconds) {
    const d = new Date(seconds * 1000);
    const ago = Math.max(0, Date.now() / 1000 - seconds);
    const time = `${two(d.getHours())}:${two(d.getMinutes())}`;
    if (ago < 60) return "agora há pouco";
    if (ago < 3600) return `há ${Math.floor(ago / 60)} min`;
    if (new Date().toDateString() === d.toDateString()) return `hoje às ${time}`;
    return `${two(d.getDate())}/${two(d.getMonth() + 1)} às ${time}`;
  }

  function deviceRow(d, live) {
    const row = document.createElement("div");
    row.className = "dev-row";
    const status = live
      ? `${d.online ? "Conectado agora" : `Visto ${when(d.seen)}`} · desde ${when(d.since)}`
      : `Última vez ${when(d.last)}`;
    row.innerHTML = `<span class="dev-dot${live && d.online ? " on" : ""}"></span><div class="dev-meta"><strong>${escapeHtml(d.name)}</strong><small>${escapeHtml(d.ip)} · ${escapeHtml(status)}</small></div>`;
    if (live) {
      const btn = document.createElement("button");
      btn.className = `ghost dev-revoke${confirming === d.id ? " confirm" : ""}`;
      btn.textContent = confirming === d.id ? "Confirmar" : "Desconectar";
      btn.addEventListener("click", () => askRevoke(d.id));
      row.appendChild(btn);
    } else if (d.revoked) {
      row.insertAdjacentHTML("beforeend", '<span class="dev-tag revoked">Desconectado por você</span>');
    }
    return row;
  }

  function renderDevices() {
    const live = state.devices;
    const history = state.history || [];
    $("#phone-count").textContent = live.length ? String(live.length) : "";
    const liveEl = $("#dev-live");
    liveEl.replaceChildren(...live.map((d) => deviceRow(d, true)));
    if (!live.length) liveEl.innerHTML = '<div class="dev-empty">Nenhum aparelho conectado agora</div>';
    const historyEl = $("#dev-history");
    historyEl.replaceChildren(...history.map((d) => deviceRow(d, false)));
    if (!history.length) historyEl.innerHTML = '<div class="dev-empty">Nenhum aparelho no histórico</div>';
    $("#dev-clear-history").hidden = !history.length;
    const all = $("#dev-revoke-all");
    all.hidden = !live.length;
    all.classList.toggle("confirm", confirming === "*");
    all.textContent = confirming === "*" ? "Confirmar: desconectar todos" : "Desconectar todos";
  }

  async function askRevoke(id) {
    clearTimeout(confirmTimer);
    if (confirming !== id) {
      confirming = id;
      confirmTimer = setTimeout(() => {
        confirming = null;
        render();
      }, 4000);
      return render();
    }
    confirming = null;
    state = id === "*" ? await api().phone_revoke_all() : await api().phone_revoke(id);
    render();
  }

  function showTab(name) {
    document.querySelectorAll(".phone-tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.ptab === name);
      b.setAttribute("aria-selected", String(b.dataset.ptab === name));
    });
    $("#phone-pane-connect").hidden = name !== "connect";
    $("#phone-pane-devices").hidden = name !== "devices";
    $("#phone-pane-received").hidden = name !== "received";
  }

  function receivedRow(r) {
    const row = document.createElement("div");
    row.className = "dev-row";
    const where = `${size(r.size)} · de ${r.device} · ${when(r.at)}`;
    row.innerHTML = `<div class="dev-meta"><strong>${escapeHtml(r.name)}</strong><small>${escapeHtml(where)}</small></div>`;
    const btn = document.createElement("button");
    btn.className = "ghost";
    btn.textContent = "Mostrar na pasta";
    btn.addEventListener("click", () => api().phone_open_received(r.id));
    row.appendChild(btn);
    return row;
  }

  function renderReceived() {
    const received = state.received || [];
    $("#received-count").textContent = received.length ? String(received.length) : "";
    const list = $("#received-list");
    list.replaceChildren(...received.map(receivedRow));
    if (!received.length) list.innerHTML = '<div class="dev-empty">Nada recebido do celular ainda</div>';
    const incoming = state.incoming;
    $("#received-incoming").hidden = !incoming;
    if (!incoming) return;
    const pct = Math.floor((incoming.done / incoming.total) * 100);
    const files = incoming.files === 1 ? "1 arquivo" : `${incoming.files} arquivos`;
    $("#received-incoming-text").textContent = `Recebendo ${files} do celular · ${pct}%`;
    $("#received-incoming-bar").style.width = `${pct}%`;
  }

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
    const online = state.devices.filter((d) => d.online);
    $("#phone-devices").innerHTML = online.length
      ? online.map((d) => `<span class="device">● ${escapeHtml(d.name)} conectado</span>`).join("")
      : '<span class="waiting">Nenhum celular conectado ainda</span>';
    renderDevices();
    renderReceived();
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
    const btn = e.currentTarget;
    await navigator.clipboard.writeText(state.url);
    btn.textContent = "Copiado!";
    setTimeout(() => (btn.textContent = "Copiar"), 1500);
  });
  $("#phone-whatsapp").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const result = await api().share_whatsapp();
    if (!result.ok) return;
    btn.lastChild.textContent = result.app === "desktop" ? " Abrindo…" : " Abrindo no navegador…";
    setTimeout(() => (btn.lastChild.textContent = " WhatsApp"), 2500);
  });
  document
    .querySelectorAll(".phone-tabs button")
    .forEach((b) => b.addEventListener("click", () => showTab(b.dataset.ptab)));
  $("#dev-revoke-all").addEventListener("click", () => askRevoke("*"));
  $("#dev-clear-history").addEventListener("click", async () => {
    state = await api().phone_clear_history();
    render();
  });
  $("#received-folder").addEventListener("click", () => api().phone_open_inbox());
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

const room = (() => {
  const modal = $("#room-modal");
  const FILE_ICON =
    '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>';
  const FOLDER_ICON =
    '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>';
  const BUSY_TITLES = {
    starting: "Abrindo a sala…",
    joining: "Entrando na sala…",
    pending: "Esperando aprovação",
  };
  const selected = new Set();
  let state = { role: null, phase: "idle" };
  let timer = null;
  let lastFocus = null;
  let tab = "theirs";
  let risky = null;
  let named = false;
  let drawn = "";

  function describe(item) {
    const count = item.kind === "folder" ? ` · ${item.count} ${item.count === 1 ? "arquivo" : "arquivos"}` : "";
    return `${size(item.size)}${count}`;
  }

  function viewOf(phase) {
    if (phase === "open") return "open";
    if (phase === "closed" || phase === "error") return "ended";
    return BUSY_TITLES[phase] ? "busy" : "start";
  }

  function addButton(parent, label, cls, fn) {
    const b = document.createElement("button");
    b.className = cls;
    b.textContent = label;
    b.addEventListener("click", fn);
    parent.append(b);
  }

  function itemRow(item, side) {
    const li = document.createElement("li");
    li.className = "room-item";
    const tag = item.risky ? '<span class="room-tag">programa</span>' : "";
    li.innerHTML = `<span class="room-item-icon">${item.kind === "folder" ? FOLDER_ICON : FILE_ICON}</span><div class="room-item-meta"><div class="room-item-name"><strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong>${tag}</div><small></small></div>`;
    const small = li.querySelector("small");
    const p = item.progress;
    const words =
      side === "theirs"
        ? { done: "Recebido", sending: "Recebendo", waiting: "Na fila", error: "Não deu para receber" }
        : { done: "Enviado", sending: "Enviando", waiting: "Pedido, já vai começar", error: "Não deu para enviar" };
    let info = describe(item);
    if (item.owner) info += ` · de ${item.owner}`;
    if (item.fetched?.length) info += ` · baixado por ${item.fetched.join(", ")}`;
    small.textContent = info;
    if (p?.state === "done") {
      small.textContent = `${words.done} · ${describe(item)}`;
      small.className = "ok";
    } else if (p?.state === "error") {
      small.textContent = p.error || words.error;
      small.className = "bad";
    } else if (p) {
      const pct = p.total ? Math.floor((p.done / p.total) * 100) : 0;
      small.textContent =
        p.state === "waiting" ? words.waiting : `${words.sending} ${pct}% · ${size(p.done)} de ${size(p.total)}`;
      small.insertAdjacentHTML("afterend", `<div class="room-item-bar"><i style="width:${pct}%"></i></div>`);
    }
    if (side === "mine") {
      addButton(li, "Tirar", "ghost", () => act(api().room_remove(item.id)));
      return li;
    }
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = selected.has(item.id);
    box.setAttribute("aria-label", `Selecionar ${item.name}`);
    box.addEventListener("change", () => {
      if (box.checked) selected.add(item.id);
      else selected.delete(item.id);
      tools();
    });
    li.prepend(box);
    if (p?.state === "done") addButton(li, "Mostrar", "ghost", () => api().room_reveal(item.id));
    else if (!p || p.state === "error") addButton(li, "Baixar", "ghost", () => download([item.id]));
    return li;
  }

  function personRow(person) {
    const row = document.createElement("div");
    const pending = person.state === "pending";
    row.className = `dev-row${pending ? " pending" : ""}`;
    const status = pending ? "Quer entrar na sala" : person.online ? "Na sala agora" : "Sem sinal";
    row.innerHTML = `<span class="dev-dot${!pending && person.online ? " on" : ""}"></span><div class="dev-meta"><strong>${escapeHtml(person.name)}</strong><small>${escapeHtml(person.device)} · ${status}</small></div>`;
    if (pending) {
      addButton(row, "Recusar", "ghost", () => act(api().room_kick(person.id)));
      addButton(row, "Deixar entrar", "acc-btn primary-soft", () => act(api().room_approve(person.id)));
    } else {
      addButton(row, "Tirar da sala", "ghost", () => act(api().room_kick(person.id)));
    }
    return row;
  }

  function tools() {
    $("#room-get-selected").disabled = !selected.size;
    $("#room-get-all").disabled = !state.theirs.length;
  }

  function showTab(name) {
    tab = name;
    document.querySelectorAll(".room-tabs button").forEach((b) => {
      b.classList.toggle("active", b.dataset.rtab === name);
      b.setAttribute("aria-selected", String(b.dataset.rtab === name));
    });
    $("#room-pane-theirs").hidden = name !== "theirs";
    $("#room-pane-mine").hidden = name !== "mine";
  }

  function render() {
    const view = viewOf(state.phase);
    document.querySelectorAll("[data-rview]").forEach((el) => (el.hidden = el.dataset.rview !== view));
    const people = state.people || [];
    const pending = people.filter((p) => p.state === "pending").length;
    $("#room-btn").classList.toggle("on", view === "open" || view === "busy");
    $("#room-badge").textContent = pending ? String(pending) : "";
    if (!named && state.name) {
      $("#room-name").value = state.name;
      named = true;
    }
    if (view === "busy") {
      $("#room-busy-title").textContent = BUSY_TITLES[state.phase];
      $("#room-busy-text").textContent =
        state.phase === "pending"
          ? "Quem criou a sala precisa deixar você entrar pelo Salvaí."
          : state.step || "Isso leva alguns segundos.";
      const bar = $("#room-busy-bar");
      bar.hidden = state.progress == null;
      bar.firstElementChild.style.width = `${state.progress || 0}%`;
      return;
    }
    if (view === "ended") {
      $("#room-ended-title").textContent = state.phase === "error" ? "Não deu para abrir a sala" : "A sala fechou";
      $("#room-ended-text").textContent = state.error || state.reason;
      return;
    }
    if (view !== "open") return;
    const host = state.role === "host";
    $("#room-share").hidden = !host;
    $("#room-close").textContent = host ? "Fechar sala" : "Sair da sala";
    $("#room-code-text").textContent = state.code;
    $("#room-url").textContent = state.url;
    $("#room-with").innerHTML = host ? "" : `Você está na sala de <strong>${escapeHtml(state.host)}</strong>.`;
    showTab(tab);
    tools();
    const key = JSON.stringify([state.role, people, state.theirs, state.mine]);
    if (key === drawn) return;
    drawn = key;
    const list = $("#room-people");
    list.replaceChildren(...people.map(personRow));
    if (host && !people.length)
      list.innerHTML = '<div class="dev-empty">Ninguém entrou ainda. Mande o link e o código pelo WhatsApp.</div>';
    const ids = new Set(state.theirs.map((i) => i.id));
    selected.forEach((id) => ids.has(id) || selected.delete(id));
    $("#room-theirs").replaceChildren(...state.theirs.map((i) => itemRow(i, "theirs")));
    if (!state.theirs.length)
      $("#room-theirs").innerHTML = '<li class="room-empty">Nada para receber ainda. Os arquivos aparecem aqui.</li>';
    $("#room-mine").replaceChildren(...state.mine.map((i) => itemRow(i, "mine")));
    if (!state.mine.length)
      $("#room-mine").innerHTML = '<li class="room-empty">Adicione arquivos ou pastas para mandar.</li>';
    $("#room-theirs-count").textContent = state.theirs.length ? String(state.theirs.length) : "";
    $("#room-mine-count").textContent = state.mine.length ? String(state.mine.length) : "";
    tools();
  }

  async function act(promise) {
    state = await promise;
    const notice = state.notice || "";
    $("#room-notice").textContent = state.phase === "open" ? notice : "";
    $("#room-msg").textContent = state.phase === "open" ? "" : notice;
    render();
  }

  async function poll() {
    state = await api().room_status();
    render();
  }

  function download(ids) {
    if (state.theirs.some((i) => i.risky && ids.includes(i.id))) {
      risky = ids;
      $("#room-risky").hidden = false;
      return;
    }
    act(api().room_download(ids));
  }

  function open() {
    lastFocus = document.activeElement;
    modal.classList.add("open");
    modal.setAttribute("aria-hidden", "false");
    poll();
    clearInterval(timer);
    timer = setInterval(poll, 1000);
  }

  function close() {
    modal.classList.remove("open");
    modal.setAttribute("aria-hidden", "true");
    clearInterval(timer);
    lastFocus?.focus();
  }

  const leave = () => act(api().room_close());
  $("#room-create").addEventListener("click", () => act(api().room_create($("#room-name").value.trim())));
  $("#room-join-form").addEventListener("submit", (e) => {
    e.preventDefault();
    act(api().room_join($("#room-link").value.trim(), $("#room-code").value, $("#room-name").value.trim()));
  });
  $("#room-code").addEventListener("input", (e) => {
    const raw = e.target.value
      .toUpperCase()
      .replace(/[^A-Z0-9]/g, "")
      .slice(0, 6);
    e.target.value = raw.length > 3 ? `${raw.slice(0, 3)} ${raw.slice(3)}` : raw;
  });
  $("#room-cancel").addEventListener("click", leave);
  $("#room-again").addEventListener("click", leave);
  $("#room-close").addEventListener("click", leave);
  $("#room-copy").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    await navigator.clipboard.writeText(`${state.url}\nCódigo: ${state.code}`);
    btn.textContent = "Copiado!";
    setTimeout(() => (btn.textContent = "Copiar"), 1500);
  });
  $("#room-whatsapp").addEventListener("click", async (e) => {
    const btn = e.currentTarget;
    const result = await api().room_share_whatsapp();
    if (!result.ok) return;
    btn.lastChild.textContent = result.app === "desktop" ? " Abrindo…" : " Abrindo no navegador…";
    setTimeout(() => (btn.lastChild.textContent = " WhatsApp"), 2500);
  });
  $("#room-add-files").addEventListener("click", () => act(api().room_add("files")));
  $("#room-add-folder").addEventListener("click", () => act(api().room_add("folder")));
  $("#room-get-selected").addEventListener("click", () => download([...selected]));
  $("#room-get-all").addEventListener("click", () => download(state.theirs.map((i) => i.id)));
  $("#room-risky-no").addEventListener("click", () => {
    risky = null;
    $("#room-risky").hidden = true;
  });
  $("#room-risky-yes").addEventListener("click", () => {
    $("#room-risky").hidden = true;
    act(api().room_download(risky));
    risky = null;
  });
  document
    .querySelectorAll(".room-tabs button")
    .forEach((b) => b.addEventListener("click", () => showTab(b.dataset.rtab)));
  $("#room-btn").addEventListener("click", open);
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

  return { sync: poll };
})();
window.app.roomChanged = () => room.sync();
