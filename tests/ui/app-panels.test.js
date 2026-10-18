import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { loadApp } from "./helpers.js";

const $ = (s) => document.querySelector(s);
const tick = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
const click = (el) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
const esc = () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));

let listeners;

async function setup(overrides = {}) {
  listeners = [];
  const original = EventTarget.prototype.addEventListener;
  vi.spyOn(EventTarget.prototype, "addEventListener").mockImplementation(function (type, fn, opts) {
    listeners.push({ target: this, type, fn });
    return original.call(this, type, fn, opts);
  });
  const result = await loadApp(overrides);
  $("#queue-list").scrollTo = vi.fn();
  return result;
}

function listenerOf(el, type = "click") {
  return listeners.find((l) => l.target === el && l.type === type).fn;
}

async function boot(items = []) {
  window.dispatchEvent(new Event("pywebviewready"));
  await tick(100);
  return items;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

const MB = 1048576;
const GB = 1024 ** 3;

function storageInfo(extra = {}) {
  const categories = [
    { key: "webview", name: "Cache da interface", desc: "Arquivos <temporários>", size: 500 * 1024, default: true },
    { key: "ytdlp", name: "Dados do YouTube", desc: "Cache", size: 5 * MB, default: true },
    { key: "temp", name: "Sobras", desc: "Sobras", size: 50 * MB, default: false },
    { key: "components", name: "Componentes", desc: "Extras", size: 2 * GB, default: false },
    { key: "essential", name: "ffmpeg", desc: "Essencial", size: 100 * MB, locked: true },
  ];
  return { version: "1.0.0", categories, total: categories.reduce((s, c) => s + c.size, 0), ...extra };
}

const rowOf = (key) =>
  [...document.querySelectorAll("#st-list .st-row")].find(
    (r) => r.style.getPropertyValue("--c") && r.querySelector(".st-name").textContent.trim() === key,
  );

describe("armazenamento", () => {
  test("abre com esqueleto, carrega categorias, anima o total e foca o fechar", async () => {
    const { api } = await setup({ storage_info: async () => storageInfo() });
    const btn = $("#storage-btn");
    btn.focus();
    click(btn);
    const modal = $("#storage-modal");
    expect(modal.classList.contains("open")).toBe(true);
    expect(modal.getAttribute("aria-hidden")).toBe("false");
    expect(document.querySelectorAll("#st-list .st-row.loading")).toHaveLength(5);
    expect($("#st-clear").disabled).toBe(true);
    await tick(0);
    expect(api.storage_info).toHaveBeenCalledTimes(1);
    const rows = document.querySelectorAll("#st-list label.st-row");
    expect(rows).toHaveLength(5);
    expect(rowOf("Cache da interface").classList.contains("checked")).toBe(true);
    expect(rowOf("Dados do YouTube").classList.contains("checked")).toBe(true);
    expect(rowOf("Sobras").classList.contains("checked")).toBe(false);
    expect(rowOf("ffmpeg").classList.contains("locked")).toBe(true);
    expect(rowOf("Cache da interface").innerHTML).toContain("Arquivos &lt;temporários&gt;");
    expect(rowOf("Cache da interface").querySelector(".st-size").textContent).toBe("500 KB");
    expect(rowOf("Dados do YouTube").querySelector(".st-size").textContent).toBe("5.0 MB");
    expect(rowOf("Sobras").querySelector(".st-size").textContent).toBe("50 MB");
    expect(rowOf("Componentes").querySelector(".st-size").textContent).toBe("2.00 GB");
    expect($("#st-clear").disabled).toBe(false);
    expect($("#st-clear").textContent).toBe("Limpar selecionados · 5.5 MB");
    const segs = document.querySelectorAll("#st-bar span");
    expect(segs).toHaveLength(5);
    expect($('#st-bar [data-key="temp"]').classList.contains("off")).toBe(true);
    expect($('#st-bar [data-key="webview"]').classList.contains("off")).toBe(false);
    expect($('#st-bar [data-key="webview"]').title).toBe("Cache da interface: 500 KB");
    expect(Number($('#st-bar [data-key="components"]').style.flexGrow)).toBeGreaterThan(0.9);
    await tick(50);
    expect(document.activeElement).toBe(modal.querySelector(".modal-close"));
    await tick(1000);
    expect($("#st-total").textContent).toBe("2.15 GB");
  });

  test("marca e desmarca categorias, ignora a bloqueada e desabilita quando nada está selecionado", async () => {
    await setup({ storage_info: async () => storageInfo() });
    click($("#storage-btn"));
    await tick(0);
    click(rowOf("Sobras"));
    expect(rowOf("Sobras").classList.contains("checked")).toBe(true);
    expect($("#st-clear").textContent).toBe("Limpar selecionados · 55 MB");
    click(rowOf("ffmpeg"));
    expect(rowOf("ffmpeg").classList.contains("checked")).toBe(false);
    click(rowOf("Sobras"));
    click(rowOf("Cache da interface"));
    click(rowOf("Dados do YouTube"));
    expect($("#st-clear").disabled).toBe(true);
    expect($("#st-clear").textContent).toBe("Nada para limpar");
    expect([...document.querySelectorAll("#st-bar span")].every((s) => s.classList.contains("off"))).toBe(true);
  });

  test("reabre sem esqueleto, mantém seleção e respeita seleção vazia após o primeiro carregamento", async () => {
    let n = 0;
    const { api } = await setup({
      storage_info: async () => (++n === 1 ? storageInfo() : storageInfo({ total: 0 })),
    });
    const btn = $("#storage-btn");
    btn.focus();
    click(btn);
    await tick(50);
    click($("#storage-modal .modal-backdrop"));
    expect($("#storage-modal").classList.contains("open")).toBe(false);
    expect($("#storage-modal").getAttribute("aria-hidden")).toBe("true");
    expect(document.activeElement).toBe(btn);
    click(btn);
    expect(document.querySelectorAll("#st-list .st-row.loading")).toHaveLength(0);
    await tick(0);
    expect(rowOf("Cache da interface").classList.contains("checked")).toBe(true);
    expect($('#st-bar [data-key="webview"]').style.flexGrow).toBe("0");
    click(rowOf("Cache da interface"));
    click(rowOf("Dados do YouTube"));
    click(document.querySelectorAll("#storage-modal [data-close]")[2]);
    click(btn);
    await tick(0);
    expect(api.storage_info).toHaveBeenCalledTimes(3);
    expect(document.querySelectorAll("#st-list .st-row.checked")).toHaveLength(0);
    expect($("#st-clear").textContent).toBe("Nada para limpar");
  });

  test("limpa os selecionados e mostra o resultado com notas escapadas", async () => {
    let resolve;
    const { api } = await setup({
      storage_info: async () => storageInfo(),
      clear_storage: () => new Promise((r) => (resolve = r)),
    });
    click($("#storage-btn"));
    await tick(0);
    click($("#st-clear"));
    expect(api.clear_storage).toHaveBeenCalledWith(["webview", "ytdlp"]);
    expect($("#st-clear").disabled).toBe(true);
    expect($("#st-clear").textContent).toContain("Limpando…");
    resolve({ info: storageInfo(), freed: 3 * MB, notes: ["<b>nota</b>", "outra"] });
    await tick(0);
    const box = $("#st-result");
    expect(box.classList.contains("show")).toBe(true);
    expect(box.querySelector("strong").textContent).toBe("✓ 3.0 MB liberados");
    expect(box.querySelectorAll("p")).toHaveLength(2);
    expect(box.querySelector("p").textContent).toBe("<b>nota</b>");
    click(document.querySelectorAll("#storage-modal [data-close]")[1]);
    click($("#storage-btn"));
    expect(box.classList.contains("show")).toBe(false);
  });

  test("fecha com Esc só quando aberto e fechar antes de abrir não quebra", async () => {
    await setup({ storage_info: async () => storageInfo() });
    click($("#storage-modal .modal-close"));
    expect($("#storage-modal").getAttribute("aria-hidden")).toBe("true");
    esc();
    expect($("#storage-modal").classList.contains("open")).toBe(false);
    click($("#storage-btn"));
    await tick(0);
    const ev = new KeyboardEvent("keydown", { key: "Enter", bubbles: true });
    document.dispatchEvent(ev);
    expect($("#storage-modal").classList.contains("open")).toBe(true);
    esc();
    expect($("#storage-modal").classList.contains("open")).toBe(false);
  });
});

const SINCE = 1760000000;

function accountsA(
  browsers = [
    { key: "chrome", name: "Chrome" },
    { key: "edge", name: "Edge" },
  ],
) {
  return {
    sites: [
      { key: "instagram", name: "Instagram", connected: true, since: SINCE, source: "app", busy: false },
      { key: "tiktok", name: "TikTok", connected: true, since: SINCE, source: "chrome", busy: false },
      { key: "x", name: "X", connected: false, since: null, source: null, busy: false },
      { key: "facebook", name: "Facebook", connected: false, since: null, source: null, busy: true },
    ],
    browsers,
  };
}

function accountsB(browsers = []) {
  return {
    sites: [
      { key: "instagram", name: "Instagram", connected: true, since: SINCE, source: null, busy: false },
      { key: "tiktok", name: "TikTok", connected: false, since: null, source: null, busy: false },
    ],
    browsers,
  };
}

const accRow = (name) =>
  [...document.querySelectorAll("#acc-list .acc-row")].find((r) => r.querySelector("strong").textContent === name);

async function addLink(url) {
  const input = $("#link-input");
  input.value = url;
  input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
  await tick(0);
}

describe("contas", () => {
  test("abre a lista, mostra estados, troca navegador, entra e sai", async () => {
    let n = 0;
    const { api } = await setup({
      accounts: async () => (++n === 1 ? accountsA() : accountsA([{ key: "firefox", name: "Firefox" }])),
      logout: async () => accountsB(),
    });
    const btn = $("#accounts-btn");
    btn.focus();
    click(btn);
    expect($("#accounts-modal").classList.contains("open")).toBe(true);
    expect($("#accounts-modal").getAttribute("aria-hidden")).toBe("false");
    await tick(0);
    const date = new Date(SINCE * 1000).toLocaleDateString("pt-BR", { day: "2-digit", month: "short" });
    expect(accRow("Instagram").className).toBe("acc-row connected");
    expect(accRow("Instagram").querySelector("small").textContent).toBe(`Conectado · desde ${date}`);
    expect(accRow("Instagram").querySelector(".acc-logo").textContent).toBe("IG");
    expect(accRow("TikTok").querySelector("small").textContent).toBe(`Conectado · desde ${date} (importado do chrome)`);
    expect(accRow("X").querySelector("small").textContent).toBe("Não conectado");
    expect(accRow("X").querySelector("[data-act]").dataset.act).toBe("login");
    expect(accRow("Facebook").className).toBe("acc-row busy");
    expect(accRow("Facebook").querySelector(".acc-wait")).not.toBeNull();
    expect(accRow("Facebook").querySelector("[data-act]")).toBeNull();
    expect($("#acc-import").hidden).toBe(false);
    expect($("#acc-browsers .chip.active").dataset.b).toBe("chrome");
    click($('#acc-browsers [data-b="edge"]'));
    expect($("#acc-browsers .chip.active").dataset.b).toBe("edge");
    click($('#acc-browsers [data-b="edge"]'));
    expect($("#acc-browsers .chip.active").dataset.b).toBe("edge");
    await tick(50);
    expect(document.activeElement).toBe($("#accounts-modal .modal-close"));
    click(accRow("X").querySelector("[data-act]"));
    await tick(0);
    expect(api.login).toHaveBeenCalledWith("x");
    click(accRow("Instagram").querySelector("[data-act]"));
    await tick(0);
    expect(api.logout).toHaveBeenCalledWith("instagram");
    expect(accRow("Instagram").querySelector("small").textContent).toBe(`Conectado · desde ${date}`);
    expect(document.querySelectorAll("#acc-list .acc-row")).toHaveLength(2);
    expect($("#acc-import").hidden).toBe(true);
    click($("#accounts-modal .modal-backdrop"));
    expect($("#accounts-modal").classList.contains("open")).toBe(false);
    expect($("#accounts-modal").getAttribute("aria-hidden")).toBe("true");
    expect(document.activeElement).toBe(btn);
    click(btn);
    await tick(0);
    expect($("#acc-browsers .chip.active").dataset.b).toBe("firefox");
  });

  test("abre focando o site pedido pelo card e fecha com Esc", async () => {
    await setup({
      init: async () => ({
        theme: "dark",
        version: "1.0.0",
        engine_version: "x",
        out_dir: "C:/",
        items: [{ id: "a", url: "u", fmt: "MP4", status: "error", login_site: "tiktok", error: "login" }],
      }),
      accounts: async () => accountsA(),
    });
    await boot();
    click(document.querySelector('.card[data-id="a"] .card-login'));
    await tick(0);
    expect(accRow("TikTok").classList.contains("focus")).toBe(true);
    expect(accRow("Instagram").classList.contains("focus")).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "a", bubbles: true }));
    expect($("#accounts-modal").classList.contains("open")).toBe(true);
    esc();
    expect($("#accounts-modal").classList.contains("open")).toBe(false);
    esc();
    click($("#accounts-btn"));
    await tick(0);
    expect(document.querySelector("#acc-list .focus")).toBeNull();
  });

  test("fechar antes de abrir não quebra", async () => {
    await setup();
    click($("#accounts-modal .modal-close"));
    expect($("#accounts-modal").getAttribute("aria-hidden")).toBe("true");
  });

  test("importa do navegador com sucesso e tenta de novo os links que pediam login", async () => {
    let resolve;
    const { api } = await setup({
      accounts: async () => accountsA(),
      import_browser: () => new Promise((r) => (resolve = r)),
      peek: async (url) =>
        url.includes("instagram")
          ? { error: "Precisa de login", site: "Instagram", login_site: "instagram" }
          : { title: "Vídeo", site: "Vimeo" },
    });
    await addLink("https://www.instagram.com/p/abc");
    await addLink("https://vimeo.com/123");
    expect(api.peek).toHaveBeenCalledTimes(2);
    click($("#accounts-btn"));
    await tick(0);
    const btn = $("#acc-import-btn");
    click(btn);
    expect(btn.disabled).toBe(true);
    expect(btn.textContent).toContain("Importando…");
    expect(api.import_browser).toHaveBeenCalledWith("chrome");
    resolve({ ok: true, message: "Importado <ok>", accounts: accountsB([{ key: "chrome", name: "Chrome" }]) });
    await tick(0);
    expect(btn.disabled).toBe(false);
    expect(btn.textContent).toBe("Importar");
    expect(document.querySelectorAll("#acc-list .acc-row")).toHaveLength(2);
    const box = $("#acc-result");
    expect(box.classList.contains("show")).toBe(true);
    expect(box.querySelector(".acc-result-box").className).toBe("acc-result-box ok");
    expect(box.querySelector(".acc-result-box").textContent).toBe("Importado <ok>");
    expect(api.peek).toHaveBeenCalledTimes(3);
    expect(api.peek).toHaveBeenLastCalledWith("https://www.instagram.com/p/abc");
  });

  test("importa do navegador com falha e mostra aviso sem tentar de novo", async () => {
    const { api } = await setup({
      accounts: async () => accountsA(),
      import_browser: async () => ({ ok: false, message: "Feche o Chrome", accounts: accountsA() }),
      peek: async () => ({ error: "Precisa de login", site: "Instagram", login_site: "instagram" }),
    });
    await addLink("https://www.instagram.com/p/abc");
    click($("#accounts-btn"));
    await tick(0);
    click($("#acc-import-btn"));
    await tick(0);
    expect($("#acc-result .acc-result-box").className).toBe("acc-result-box warn");
    expect(api.peek).toHaveBeenCalledTimes(1);
  });

  test("accountsChanged atualiza a lista, avisa e tenta de novo cards e links do site conectado", async () => {
    const { api } = await setup({
      init: async () => ({
        theme: "dark",
        version: "1.0.0",
        engine_version: "x",
        out_dir: "C:/",
        items: [
          { id: "a", url: "u1", fmt: "MP4", status: "error", login_site: "instagram" },
          { id: "b", url: "u2", fmt: "MP4", status: "error", login_site: "tiktok" },
          { id: "c", url: "u3", fmt: "MP4", status: "done" },
        ],
      }),
      accounts: async () => accountsA(),
      peek: async (url) =>
        url.includes("instagram")
          ? { error: "login", site: "Instagram", login_site: "instagram" }
          : { error: "login", site: "TikTok", login_site: "tiktok" },
    });
    await boot();
    await addLink("https://www.instagram.com/p/abc");
    await addLink("https://www.tiktok.com/@a/video/1");
    window.app.accountsChanged({ accounts: accountsB(), connected: null });
    expect($("#acc-list").children).toHaveLength(0);
    expect($("#acc-result").classList.contains("show")).toBe(false);
    window.app.accountsChanged({ accounts: accountsB(), connected: "instagram" });
    await tick(0);
    expect($("#acc-result .acc-result-box").textContent).toBe(
      "✓ Conta do Instagram conectada. Os links que precisavam de login vão ser tentados de novo.",
    );
    expect($("#acc-result .acc-result-box").className).toBe("acc-result-box ok");
    expect(api.retry).toHaveBeenCalledTimes(1);
    expect(api.retry).toHaveBeenCalledWith("a");
    expect(api.peek).toHaveBeenCalledTimes(3);
    expect(api.peek).toHaveBeenLastCalledWith("https://www.instagram.com/p/abc");
    click($("#accounts-btn"));
    await tick(0);
    window.app.accountsChanged({ accounts: accountsB(), connected: "facebook" });
    expect(document.querySelectorAll("#acc-list .acc-row")).toHaveLength(2);
    expect($("#acc-result .acc-result-box").textContent).toContain("Conta do undefined conectada");
  });
});

describe("avisos de atualização", () => {
  test("conector do Claude: avisa uma vez, esconde o Depois e fecha no Entendi", async () => {
    const { api } = await setup();
    const el = $("#notice");
    const later = $("#notice-later");
    window.app.updateAvailable({ kind: "claude" });
    expect(el.classList.contains("show")).toBe(true);
    expect($("#notice-title").textContent).toBe("Salvaí conectado ao Claude");
    expect($("#notice-desc").textContent).toContain("Feche e abra o Claude Desktop");
    expect($("#notice-action").textContent).toBe("Entendi");
    expect(later.hidden).toBe(true);
    $("#notice-action").click();
    expect(el.classList.contains("show")).toBe(false);
    expect(api.skip_update).not.toHaveBeenCalled();
  });

  test("motor: falha, sucesso, reinício e fila para o próximo aviso", async () => {
    let n = 0;
    const { api } = await setup({
      update_engine: async () =>
        ++n === 1 ? { ok: false, message: "Sem internet" } : { ok: true, version: "2026.9.1" },
    });
    const el = $("#notice");
    const action = $("#notice-action");
    const later = $("#notice-later");
    window.app.updateAvailable({ kind: "engine", latest: "2026.9.1", current: "2026.8.19" });
    expect(el.classList.contains("show")).toBe(true);
    expect($("#notice-title").textContent).toBe("Motor de download novo disponível");
    expect($("#notice-desc").textContent).toContain("a versão 2026.9.1");
    expect($("#notice-desc").textContent).toContain("(você está na 2026.8.19)");
    expect(action.textContent).toBe("Atualizar");
    expect(later.hidden).toBe(false);
    window.app.updateAvailable({ kind: "app", latest: "2.0.0", current: "1.0.0", url: "https://rel" });
    expect($("#notice-title").textContent).toBe("Motor de download novo disponível");
    click(action);
    expect(action.disabled).toBe(true);
    expect(action.textContent).toContain("Atualizando…");
    expect(later.hidden).toBe(true);
    await tick(0);
    expect(action.disabled).toBe(false);
    expect(later.hidden).toBe(false);
    expect($("#notice-desc").textContent).toBe("Sem internet");
    expect(action.textContent).toBe("Tentar de novo");
    click(action);
    await tick(0);
    expect($("#notice-title").textContent).toBe("Motor 2026.9.1 pronto");
    expect(action.textContent).toBe("Reiniciar agora");
    click(action);
    expect(api.restart_app).toHaveBeenCalledTimes(1);
    click(later);
    expect(api.skip_update).not.toHaveBeenCalled();
    expect($("#notice-title").textContent).toBe("Salvaí 2.0.0 disponível");
    expect(action.textContent).toBe("Atualizar agora");
    expect(later.textContent).toBe("Depois");
    click($("#notice-desc .notice-link"));
    expect(api.open_release).toHaveBeenCalledWith("https://rel");
    click(later);
    expect(api.skip_update).toHaveBeenCalledWith("app", "2.0.0");
    expect(el.classList.contains("show")).toBe(false);
  });

  test("app: progresso OTA, instalação e reinício automático", async () => {
    let resolve;
    const { api } = await setup({ update_app: () => new Promise((r) => (resolve = r)) });
    const action = $("#notice-action");
    window.app.otaProgress(10);
    expect(action.textContent).toBe("");
    window.app.updateAvailable({ kind: "app", latest: "2.0.0", current: "<1.0.0>", url: "https://rel" });
    expect($("#notice-desc").innerHTML).toContain("&lt;1.0.0&gt;");
    window.app.otaProgress(10);
    expect(action.textContent).toBe("Atualizar agora");
    click(action);
    expect(action.textContent).toContain("Baixando 0%");
    expect($("#notice-later").hidden).toBe(true);
    window.app.otaProgress(42);
    expect(action.textContent).toContain("Baixando 42%");
    window.app.otaProgress(100);
    expect(action.textContent).toContain("Instalando…");
    resolve({ ok: true, version: "2.0.0" });
    await tick(0);
    expect($("#notice-title").textContent).toBe("Salvaí 2.0.0 instalado");
    expect($("#notice-desc").textContent).toBe("Reabrindo o app na versão nova…");
    expect(action.textContent).toContain("Reiniciando");
    expect(api.restart_app).not.toHaveBeenCalled();
    await tick(1200);
    expect(api.restart_app).toHaveBeenCalledTimes(1);
  });

  test("app: falha com página manual abre a página e falha sem página permite tentar de novo", async () => {
    let n = 0;
    const { api } = await setup({
      update_app: async () =>
        ++n === 1 ? { ok: false, message: "Falhou" } : { ok: false, message: "Baixe manualmente", url: "https://m" },
    });
    const action = $("#notice-action");
    window.app.updateAvailable({ kind: "app", latest: "2.0.0", current: "1.0.0", url: "https://rel" });
    click(action);
    await tick(0);
    expect(action.disabled).toBe(false);
    expect($("#notice-later").hidden).toBe(false);
    expect($("#notice-desc").textContent).toBe("Falhou");
    expect(action.textContent).toBe("Tentar de novo");
    window.app.otaProgress(50);
    expect(action.textContent).toBe("Tentar de novo");
    click(action);
    await tick(0);
    expect($("#notice-desc").textContent).toBe("Baixe manualmente");
    expect(action.textContent).toBe("Abrir página");
    click(action);
    expect(api.open_release).toHaveBeenCalledWith("https://m");
    expect(api.update_app).toHaveBeenCalledTimes(2);
    expect($("#notice").classList.contains("show")).toBe(false);
  });
});

const NOW = new Date(2026, 9, 18, 20, 0, 0).getTime() / 1000;

function device(extra = {}) {
  return { id: "d1", name: "iPhone", ip: "192.168.0.5", since: NOW - 600, seen: NOW, online: true, ...extra };
}

function phoneState(extra = {}) {
  return {
    on: true,
    url: "http://192.168.0.2:8765/?k=1",
    qr: '<svg id="qr1"></svg>',
    network: { kind: "wifi", name: "Casa", public: true },
    devices: [device({ name: "<iPhone>" })],
    history: [],
    others: ["http://10.0.0.2:8765/?k=1"],
    ...extra,
  };
}

describe("celular", () => {
  test("abre, mostra QR, rede e dispositivos e atualiza por polling até fechar", async () => {
    const states = [
      phoneState(),
      phoneState({ network: { kind: "wifi" }, devices: [], others: undefined }),
      phoneState({ network: { kind: "cabo" } }),
      phoneState({ network: undefined, url: "http://outra", qr: '<svg id="qr2"></svg>' }),
    ];
    let n = 0;
    const { api } = await setup({ phone_status: async () => states[Math.min(n++, states.length - 1)] });
    const btn = $("#phone-btn");
    btn.focus();
    click(btn);
    expect($("#phone-modal").classList.contains("open")).toBe(true);
    expect($("#phone-modal").getAttribute("aria-hidden")).toBe("false");
    await tick(0);
    expect($("#phone-switch").classList.contains("on")).toBe(true);
    expect(btn.classList.contains("on")).toBe(true);
    expect($("#phone-on").classList.contains("show")).toBe(true);
    expect($("#phone-switch-hint").textContent).toBe("Ligado. Aponte a câmera do celular para o código.");
    expect($("#phone-qr svg").id).toBe("qr1");
    expect($("#phone-qr").dataset.url).toBe("http://192.168.0.2:8765/?k=1");
    expect($("#phone-url").textContent).toBe("http://192.168.0.2:8765/?k=1");
    expect($("#net-text").textContent).toBe("Conecte o celular ao Wi-Fi «Casa», o mesmo do computador");
    expect($("#phone-warn").classList.contains("show")).toBe(true);
    expect($("#phone-devices .device").textContent).toBe("● <iPhone> conectado");
    expect($("#phone-others").classList.contains("has")).toBe(true);
    expect($("#phone-others-list li").textContent).toBe("http://10.0.0.2:8765/?k=1");
    $("#phone-qr").innerHTML = '<svg id="mantido"></svg>';
    await tick(2000);
    expect($("#phone-qr svg").id).toBe("mantido");
    expect($("#net-text").textContent).toBe("Conecte o celular ao mesmo Wi-Fi do computador");
    expect($("#phone-warn").classList.contains("show")).toBe(false);
    expect($("#phone-devices .waiting").textContent).toBe("Nenhum celular conectado ainda");
    expect($("#phone-others").classList.contains("has")).toBe(false);
    expect($("#phone-others-list").children).toHaveLength(0);
    await tick(2000);
    expect($("#net-text").textContent).toBe("O computador está no cabo: conecte o celular ao Wi-Fi do mesmo roteador");
    await tick(2000);
    expect($("#net-text").textContent).toBe("Conecte o celular ao mesmo Wi-Fi do computador");
    expect($("#phone-qr svg").id).toBe("qr2");
    expect(api.phone_status).toHaveBeenCalledTimes(4);
    click($("#phone-modal .modal-backdrop"));
    expect($("#phone-modal").classList.contains("open")).toBe(false);
    expect($("#phone-modal").getAttribute("aria-hidden")).toBe("true");
    expect(document.activeElement).toBe(btn);
    await tick(6000);
    expect(api.phone_status).toHaveBeenCalledTimes(4);
  });

  test("reabrir reinicia o intervalo e Esc fecha só quando aberto", async () => {
    const { api } = await setup({ phone_status: async () => ({ on: false }) });
    click($("#phone-modal .modal-close"));
    esc();
    click($("#phone-btn"));
    click($("#phone-btn"));
    await tick(0);
    expect(api.phone_status).toHaveBeenCalledTimes(2);
    expect($("#phone-switch-hint").textContent).toBe("Desligado. Ligue para mostrar o QR code.");
    expect($("#phone-on").classList.contains("show")).toBe(false);
    await tick(2000);
    expect(api.phone_status).toHaveBeenCalledTimes(3);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "x", bubbles: true }));
    expect($("#phone-modal").classList.contains("open")).toBe(true);
    esc();
    expect($("#phone-modal").classList.contains("open")).toBe(false);
    await tick(4000);
    expect(api.phone_status).toHaveBeenCalledTimes(3);
  });

  test("liga e desliga pelo switch", async () => {
    let resolve;
    const { api } = await setup({
      phone_start: () => new Promise((r) => (resolve = r)),
      phone_stop: async () => ({ on: false }),
    });
    const sw = $("#phone-switch");
    click(sw);
    expect(sw.classList.contains("busy")).toBe(true);
    expect(api.phone_start).toHaveBeenCalledTimes(1);
    resolve(phoneState());
    await tick(0);
    expect(sw.classList.contains("busy")).toBe(false);
    expect(sw.classList.contains("on")).toBe(true);
    click(sw);
    await tick(0);
    expect(api.phone_stop).toHaveBeenCalledTimes(1);
    expect(sw.classList.contains("on")).toBe(false);
  });

  test("envia o link pelo WhatsApp do computador ou da web", async () => {
    let result = { ok: true, app: "desktop" };
    const { api } = await setup({ phone_start: async () => phoneState(), share_whatsapp: async () => result });
    click($("#phone-switch"));
    await tick(0);
    const btn = $("#phone-whatsapp");
    click(btn);
    await tick(0);
    expect(api.share_whatsapp).toHaveBeenCalledTimes(1);
    expect(btn.textContent.trim()).toBe("Abrindo…");
    await tick(2500);
    expect(btn.textContent.trim()).toBe("WhatsApp");
    result = { ok: true, app: "web" };
    click(btn);
    await tick(0);
    expect(btn.textContent.trim()).toBe("Abrindo no navegador…");
    await tick(2500);
    result = { ok: false };
    click(btn);
    await tick(0);
    expect(btn.textContent.trim()).toBe("WhatsApp");
  });

  test("copia o link, restaura o texto e aciona firewall e configurações", async () => {
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const { api } = await setup({ phone_start: async () => phoneState() });
    click($("#phone-switch"));
    await tick(0);
    const copy = $("#phone-copy");
    click(copy);
    await tick(0);
    expect(writeText).toHaveBeenCalledWith("http://192.168.0.2:8765/?k=1");
    expect(copy.textContent).toBe("Copiado!");
    await tick(1500);
    expect(copy.textContent).toBe("Copiar");
    click($("#phone-firewall"));
    expect(api.phone_allow_firewall).toHaveBeenCalledTimes(1);
    click($("#phone-settings"));
    expect(api.open_network_settings).toHaveBeenCalledTimes(1);
  });

  test("phoneChanged sincroniza o estado", async () => {
    const { api } = await setup({
      phone_status: async () =>
        phoneState({ devices: [device({ name: "Galaxy" }), device({ id: "d2", name: "Velho", online: false })] }),
    });
    window.app.phoneChanged();
    await tick(0);
    expect(api.phone_status).toHaveBeenCalledTimes(1);
    expect($("#phone-devices .device").textContent).toBe("● Galaxy conectado");
    expect($("#phone-btn").classList.contains("on")).toBe(true);
  });
});

describe("aparelhos conectados", () => {
  beforeEach(() => {
    vi.setSystemTime(NOW * 1000);
  });

  async function openDevices(state, overrides = {}) {
    const result = await setup({ phone_status: async () => state, ...overrides });
    click($("#phone-btn"));
    await tick(0);
    click($('.phone-tabs button[data-ptab="devices"]'));
    return result;
  }

  test("troca entre as abas Conectar e Aparelhos", async () => {
    await openDevices(phoneState());
    expect($("#phone-pane-devices").hidden).toBe(false);
    expect($("#phone-pane-connect").hidden).toBe(true);
    expect($('.phone-tabs button[data-ptab="devices"]').getAttribute("aria-selected")).toBe("true");
    expect($("#phone-count").textContent).toBe("1");
    click($('.phone-tabs button[data-ptab="connect"]'));
    expect($("#phone-pane-connect").hidden).toBe(false);
    expect($("#phone-pane-devices").hidden).toBe(true);
  });

  test("lista conectados e histórico com horários legíveis", async () => {
    const yesterday = new Date(2026, 9, 17, 9, 5).getTime() / 1000;
    const state = phoneState({
      devices: [
        device({ name: "<iPhone>", ip: "192.168.0.5", seen: NOW - 5, since: NOW - 30 }),
        device({ id: "d2", name: "Android", ip: "192.168.0.6", online: false, seen: NOW - 300, since: NOW - 7200 }),
      ],
      history: [
        { id: "h1", name: "iPad", ip: "192.168.0.7", since: yesterday, last: yesterday, revoked: true },
        { id: "h2", name: "Windows", ip: "192.168.0.8", since: NOW - 4000, last: NOW - 3900 },
      ],
    });
    await openDevices(state);
    const live = [...document.querySelectorAll("#dev-live .dev-row")];
    expect(live).toHaveLength(2);
    expect(live[0].querySelector("strong").textContent).toBe("<iPhone>");
    expect(live[0].querySelector("small").textContent).toBe("192.168.0.5 · Conectado agora · desde agora há pouco");
    expect(live[0].querySelector(".dev-dot").classList.contains("on")).toBe(true);
    expect(live[1].querySelector("small").textContent).toBe("192.168.0.6 · Visto há 5 min · desde hoje às 18:00");
    expect(live[1].querySelector(".dev-dot").classList.contains("on")).toBe(false);
    const history = [...document.querySelectorAll("#dev-history .dev-row")];
    expect(history[0].querySelector("small").textContent).toBe("192.168.0.7 · Última vez 17/10 às 09:05");
    expect(history[0].querySelector(".dev-tag.revoked").textContent).toBe("Desconectado por você");
    expect(history[1].querySelector(".dev-tag")).toBeNull();
    expect(history[1].querySelector("button")).toBeNull();
    expect($("#dev-clear-history").hidden).toBe(false);
    expect($("#dev-revoke-all").hidden).toBe(false);
    expect($("#phone-count").textContent).toBe("2");
  });

  test("mostra vazios quando ninguém conectou", async () => {
    await openDevices(phoneState({ devices: [], history: undefined }));
    expect($("#dev-live .dev-empty").textContent).toBe("Nenhum aparelho conectado agora");
    expect($("#dev-history .dev-empty").textContent).toBe("Nenhum aparelho no histórico");
    expect($("#dev-clear-history").hidden).toBe(true);
    expect($("#dev-revoke-all").hidden).toBe(true);
    expect($("#phone-count").textContent).toBe("");
  });

  test("desconectar pede confirmação e cancela sozinho depois de 4 segundos", async () => {
    const after = phoneState({ devices: [] });
    const { api } = await openDevices(phoneState(), { phone_revoke: async () => after });
    const button = () => $("#dev-live .dev-revoke");
    click(button());
    expect(button().textContent).toBe("Confirmar");
    expect(button().classList.contains("confirm")).toBe(true);
    expect(api.phone_revoke).not.toHaveBeenCalled();
    await tick(4000);
    expect(button().textContent).toBe("Desconectar");
    click(button());
    click(button());
    await tick(0);
    expect(api.phone_revoke).toHaveBeenCalledWith("d1");
    expect($("#dev-live .dev-empty")).not.toBeNull();
  });

  test("desconectar todos também pede confirmação", async () => {
    const after = phoneState({
      devices: [],
      history: [{ id: "d1", name: "iPhone", ip: "x", last: NOW, revoked: true }],
    });
    const { api } = await openDevices(phoneState(), { phone_revoke_all: async () => after });
    const all = $("#dev-revoke-all");
    click(all);
    expect(all.textContent).toBe("Confirmar: desconectar todos");
    expect(all.classList.contains("confirm")).toBe(true);
    click(all);
    await tick(0);
    expect(api.phone_revoke_all).toHaveBeenCalledTimes(1);
    expect(all.hidden).toBe(true);
    expect($("#dev-history .dev-tag.revoked")).not.toBeNull();
  });

  test("limpar histórico", async () => {
    const before = phoneState({ history: [{ id: "h", name: "iPad", ip: "x", last: NOW - 100 }] });
    const { api } = await openDevices(before, { phone_clear_history: async () => phoneState() });
    click($("#dev-clear-history"));
    await tick(0);
    expect(api.phone_clear_history).toHaveBeenCalledTimes(1);
    expect($("#dev-history .dev-empty")).not.toBeNull();
  });
});
