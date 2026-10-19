import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { loadHtml } from "./helpers.js";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const tick = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
const visible = () =>
  $$("[data-view]")
    .filter((el) => !el.hidden)
    .map((el) => el.dataset.view);
const button = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent === label);

function reply(value) {
  if (value?.raw) return value.raw;
  const { status = 200, body = {} } =
    value && typeof value === "object" && "status" in value ? value : { body: value ?? {} };
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => {
      if (body === "bad") throw new Error("não é json");
      return body;
    },
  };
}

async function load(responses = {}) {
  vi.resetModules();
  loadHtml("room/index.html");
  const calls = [];
  globalThis.fetch = window.fetch = vi.fn(async (path, options = {}) => {
    calls.push({ path, options });
    const handler = responses[String(path).split("?")[0]];
    return reply(typeof handler === "function" ? await handler(path, options) : handler);
  });
  await import("../../src/ui/room/room.js");
  await tick(0);
  return { calls };
}

function state(extra = {}) {
  return { host: "Kaique", me: { id: "g", name: "Ana" }, items: [], mine: [], requests: [], chunk: 4, ...extra };
}

const approved = { state: "approved", host: "Kaique", name: "Ana" };

function pick(id, files) {
  const input = $(id);
  Object.defineProperty(input, "files", { configurable: true, value: files });
  input.dispatchEvent(new Event("change"));
}

function file(name, content, rel = "") {
  const f = new File([content], name);
  Object.defineProperty(f, "webkitRelativePath", { value: rel });
  return f;
}

beforeEach(() => {
  vi.useFakeTimers();
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  delete window.showDirectoryPicker;
  delete HTMLInputElement.prototype.webkitdirectory;
});

describe("entrada", () => {
  test("pede o código e entra depois de aprovado", async () => {
    let me = { state: "none", host: "Kaique" };
    localStorage.setItem("sala-name", "Ana");
    const { calls } = await load({
      "/api/me": () => me,
      "/api/join": { state: "pending" },
      "/api/state": state(),
    });
    expect(visible()).toEqual(["join"]);
    expect($("#join-title").textContent).toBe("Entrar na sala de Kaique");
    expect($("#host-label").textContent).toBe("Sala de Kaique");
    expect($("#join-name").value).toBe("Ana");
    expect($("#add-folder").hidden).toBe(true);
    expect($("#leave").hidden).toBe(true);
    const code = $("#join-code");
    code.value = "a";
    code.dispatchEvent(new Event("input"));
    expect(code.value).toBe("A");
    code.value = "abc-1234";
    code.dispatchEvent(new Event("input"));
    expect(code.value).toBe("ABC 123");
    $("#join-name").value = " Bia ";
    $("#join-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(0);
    const sent = calls.find((c) => c.path === "/api/join");
    expect(JSON.parse(sent.options.body)).toEqual({ name: "Bia", code: "ABC 123" });
    expect(sent.options.headers).toEqual({ "X-Sala": "1", "Content-Type": "application/json" });
    expect(localStorage.getItem("sala-name")).toBe("Bia");
    expect(visible()).toEqual(["wait"]);
    expect($("#leave").hidden).toBe(false);
    me = { state: "pending" };
    await tick(2000);
    expect(visible()).toEqual(["wait"]);
    me = approved;
    await tick(2000);
    expect(visible()).toEqual(["room"]);
    expect($("#link-state").classList.contains("ok")).toBe(true);
  });

  test("código errado mostra a mensagem", async () => {
    await load({
      "/api/me": { state: "none", host: "" },
      "/api/join": { status: 403, body: { error: "Código errado" } },
    });
    expect($("#join-title").textContent).toBe("Entrar na sala");
    expect($("#host-label").textContent).toBe("Sala de troca");
    $("#join-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(0);
    expect($("#join-msg").textContent).toBe("Código errado");
    expect($("#join-btn").disabled).toBe(false);
  });

  test("resposta sem json usa a mensagem padrão", async () => {
    await load({ "/api/me": { state: "none" }, "/api/join": { status: 500, body: "bad" } });
    $("#join-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(0);
    expect($("#join-msg").textContent).toBe("Algo deu errado. Tente de novo.");
  });

  test("recusado ou sem conexão", async () => {
    await load({ "/api/me": { state: "revoked", host: "K" } });
    expect(visible()).toEqual(["gone"]);
    expect($("#gone-text").textContent).toContain("não deixou você entrar");
    await load({ "/api/me": { status: 502, body: "bad" } });
    expect($("#gone-text").textContent).toContain("Confira o link");
  });

  test("espera aprovação e trata recusa e falhas", async () => {
    let fail = true;
    await load({
      "/api/me": (path) => {
        if (fail) {
          fail = false;
          return { state: "pending" };
        }
        return { status: 500, body: {} };
      },
    });
    expect(visible()).toEqual(["wait"]);
    await tick(2000);
    expect(visible()).toEqual(["wait"]);
  });

  test("sem localStorage continua funcionando", async () => {
    vi.stubGlobal("localStorage", {
      getItem: () => {
        throw new Error("bloqueado");
      },
      setItem: () => {
        throw new Error("bloqueado");
      },
    });
    HTMLInputElement.prototype.webkitdirectory = false;
    await load({ "/api/me": { state: "none" }, "/api/join": { state: "revoked" } });
    expect($("#add-folder").hidden).toBe(false);
    $("#join-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(0);
    expect(visible()).toEqual(["gone"]);
  });
});

describe("sala", () => {
  test("mostra os arquivos e para quando é removido", async () => {
    let current = state({
      items: [
        { id: "f", kind: "folder", name: "Fotos", size: 3 * 1024 * 1024, count: 2, risky: false },
        { id: "e", kind: "file", name: "<setup>.exe", size: 15 * 1024, count: 1, risky: true },
        { id: "u", kind: "folder", name: "Um", size: 5 * 1024 ** 5, count: 1, risky: false },
      ],
    });
    await load({ "/api/me": approved, "/api/state": () => current });
    const rows = $$("#theirs .item");
    expect(rows).toHaveLength(3);
    expect(rows[0].querySelector("small").textContent).toBe("3,0 MB · 2 arquivos");
    expect(rows[1].querySelector("strong").textContent).toBe("<setup>.exe");
    expect(rows[1].querySelector(".risky").textContent).toBe("programa");
    expect(rows[1].querySelector("small").textContent).toBe("15 KB");
    expect(rows[2].querySelector("small").textContent).toBe("5120 TB · 1 arquivo");
    expect($("#mine .empty").textContent).toContain("Adicione");
    expect($("#get-all").disabled).toBe(false);
    expect($("#get-selected").disabled).toBe(true);
    const box = rows[0].querySelector("input");
    box.checked = true;
    box.dispatchEvent(new Event("change"));
    expect($("#get-selected").disabled).toBe(false);
    box.checked = false;
    box.dispatchEvent(new Event("change"));
    expect($("#get-selected").disabled).toBe(true);
    box.checked = true;
    box.dispatchEvent(new Event("change"));
    const same = $("#theirs .item");
    await tick(1500);
    expect($("#theirs .item")).toBe(same);
    current = state();
    await tick(1500);
    expect($("#theirs .empty").textContent).toContain("Ainda não tem nada");
    expect($("#get-selected").disabled).toBe(true);
    expect($("#get-all").disabled).toBe(true);
    current = { status: 403, body: { error: "Quem criou a sala tirou você dela." } };
    await tick(1500);
    expect(visible()).toEqual(["gone"]);
    expect($("#gone-text").textContent).toBe("Quem criou a sala tirou você dela.");
    expect($("#link-state").classList.contains("ok")).toBe(false);
  });

  test("desiste depois de muitas falhas", async () => {
    let fail = false;
    await load({ "/api/me": approved, "/api/state": () => (fail ? { status: 530, body: "bad" } : state()) });
    fail = true;
    await tick(1500 * 7);
    expect(visible()).toEqual(["room"]);
    await tick(1500);
    expect($("#gone-text").textContent).toContain("não responde mais");
  });

  test("sair da sala", async () => {
    const { calls } = await load({ "/api/me": approved, "/api/state": state(), "/api/leave": { ok: true } });
    $("#leave").click();
    await tick(0);
    expect(calls.some((c) => c.path === "/api/leave")).toBe(true);
    expect($("#gone-text").textContent).toContain("Você saiu da sala");
    await load({ "/api/me": approved, "/api/state": state(), "/api/leave": { status: 500 } });
    $("#leave").click();
    await tick(0);
    expect(visible()).toEqual(["gone"]);
  });
});

describe("enviar", () => {
  test("adiciona arquivos e pastas e envia quando pedido", async () => {
    let current = state();
    const offers = [];
    const uploads = [];
    let uploadReply = (offset, size) => ({ received: offset + size });
    const { calls } = await load({
      "/api/me": approved,
      "/api/state": () => current,
      "/api/offer": (path, options) => {
        const items = JSON.parse(options.body).items;
        offers.push(items);
        return { ids: items.map((_, i) => `id${offers.length}-${i}`) };
      },
      "/api/upload": (path, options) => {
        const offset = Number(new URL(path, "http://x").searchParams.get("offset"));
        uploads.push({ offset, size: options.body.size, type: options.headers["Content-Type"] });
        return uploadReply(offset, options.body.size);
      },
    });
    $("#add-files").click();
    pick("#pick-files", [file("a.txt", "0123456789")]);
    await tick(0);
    expect(offers[0]).toEqual([{ kind: "file", name: "a.txt", files: [{ rel: "a.txt", size: 10 }] }]);
    expect($("#toast").textContent).toBe("Adicionado à sala");
    expect($("#toast").className).toBe("toast show");
    await tick(3500);
    expect($("#toast").className).toBe("toast");
    $("#add-folder").click();
    pick("#pick-folder", [
      file("1.jpg", "1", "Viagem/1.jpg"),
      file("2.jpg", "22", "Viagem/dia/2.jpg"),
      file("x.txt", "x", "Outra/x.txt"),
    ]);
    await tick(0);
    expect(offers[1]).toEqual([
      {
        kind: "folder",
        name: "Viagem",
        files: [
          { rel: "Viagem/1.jpg", size: 1 },
          { rel: "Viagem/dia/2.jpg", size: 2 },
        ],
      },
      { kind: "folder", name: "Outra", files: [{ rel: "Outra/x.txt", size: 1 }] },
    ]);
    expect($("#toast").textContent).toBe("2 itens adicionados à sala");
    pick("#pick-files", []);
    await tick(0);
    expect(offers).toHaveLength(2);
    current = state({
      mine: [
        {
          id: "id1-0",
          kind: "file",
          name: "a.txt",
          size: 10,
          count: 1,
          progress: { state: "sending", done: 4, total: 10 },
        },
        { id: "id2-0", kind: "folder", name: "Viagem", size: 3, count: 2, progress: null },
        {
          id: "id2-1",
          kind: "folder",
          name: "Outra",
          size: 1,
          count: 1,
          progress: { state: "waiting", done: 0, total: 1 },
        },
        {
          id: "velho",
          kind: "file",
          name: "velho.bin",
          size: 5,
          count: 1,
          progress: { state: "done", done: 5, total: 5 },
        },
        { id: "perdido", kind: "file", name: "perdido.bin", size: 5, count: 1, progress: null },
        {
          id: "zero",
          kind: "file",
          name: "zero",
          size: 0,
          count: 1,
          progress: { state: "error", done: 0, total: 0, error: "" },
        },
      ],
      requests: [
        { id: "r1", item: "id1-0", f: 0, offset: 0, size: 10 },
        { id: "r2", item: "outro", f: 0, offset: 0, size: 1 },
      ],
    });
    uploadReply = (offset, size) =>
      offset === 4 ? { status: 409, body: { received: 6 } } : { received: offset + size };
    await tick(1500);
    expect(uploads).toEqual([
      { offset: 0, size: 4, type: "application/octet-stream" },
      { offset: 4, size: 4, type: "application/octet-stream" },
      { offset: 6, size: 4, type: "application/octet-stream" },
    ]);
    expect(calls.find((c) => c.path.startsWith("/api/upload")).options.headers["X-Sala"]).toBe("1");
    const texts = $$("#mine small").map((s) => s.textContent);
    expect(texts).toEqual([
      "Enviando 40%",
      "3 B · 2 arquivos · esperando ser pedido",
      "Pedido, já vai começar",
      "Enviado",
      "Adicione de novo para continuar enviando",
      "Adicione de novo para continuar enviando",
    ]);
    expect($("#keep-open").hidden).toBe(false);
    const event = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(event);
    expect(event.defaultPrevented).toBe(true);
    current = state({ mine: [], requests: [{ id: "r3", item: "id1-0", f: 0, offset: 0, size: 10 }] });
    uploadReply = () => ({ status: 400, body: { error: "Esse envio não existe mais." } });
    await tick(1500);
    expect($("#toast").textContent).toBe("Esse envio não existe mais.");
    expect($("#toast").className).toBe("toast show error");
    current = state();
    await tick(1500);
    const quiet = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(quiet);
    expect(quiet.defaultPrevented).toBe(false);
  });

  test("só envia um por vez", async () => {
    let release;
    const uploads = [];
    await load({
      "/api/me": approved,
      "/api/state": state({ requests: [{ id: "r", item: "id1-0", f: 0, offset: 0, size: 2 }] }),
      "/api/offer": { ids: ["id1-0"] },
      "/api/upload": () => {
        uploads.push(1);
        return new Promise((r) => (release = () => r({ received: 2 })));
      },
    });
    pick("#pick-files", [file("a", "ab")]);
    await tick(0);
    await tick(1500);
    expect(uploads).toHaveLength(1);
    release();
    await tick(0);
  });

  test("erros ao adicionar e tirar", async () => {
    let fail = true;
    await load({
      "/api/me": approved,
      "/api/state": state({ mine: [{ id: "m", kind: "file", name: "m", size: 1, count: 1, progress: null }] }),
      "/api/offer": { status: 400, body: { error: "A sala já tem itens demais." } },
      "/api/unoffer": () => (fail ? { status: 400, body: { error: "não deu" } } : { ok: true }),
    });
    pick("#pick-files", [file("a", "a")]);
    await tick(0);
    expect($("#toast").textContent).toBe("A sala já tem itens demais.");
    button($("#mine .item"), "Tirar").click();
    await tick(0);
    expect($("#toast").textContent).toBe("não deu");
    fail = false;
    button($("#mine .item"), "Tirar").click();
    await tick(0);
  });
});

function directory(existing = {}) {
  const written = {};
  const make = (prefix) => ({
    getDirectoryHandle: async (name) => make(`${prefix}${name}/`),
    getFileHandle: async (name) => {
      const path = `${prefix}${name}`;
      return {
        getFile: async () => ({ size: existing[path] ?? 0 }),
        createWritable: async (options) => {
          const log = { options, ops: [] };
          written[path] = log;
          return {
            truncate: async (n) => log.ops.push(["truncate", n]),
            seek: async (n) => log.ops.push(["seek", n]),
            write: async (chunk) => log.ops.push(["write", chunk.length]),
            close: async () => log.ops.push(["close"]),
          };
        },
      };
    },
  });
  return { root: make(""), written };
}

function stream(...chunks) {
  const queue = chunks.map((c) => ({ done: false, value: new Uint8Array(c) }));
  return { getReader: () => ({ read: async () => queue.shift() || { done: true } }) };
}

describe("baixar", () => {
  const items = [
    { id: "s", kind: "file", name: "solo.mp4", size: 10, count: 1, risky: false },
    { id: "p", kind: "folder", name: "Pasta", size: 30, count: 3, risky: false },
    { id: "x", kind: "file", name: "setup.exe", size: 5, count: 1, risky: true },
  ];

  test("arquivo solto vira download direto e programas pedem confirmação", async () => {
    const clicks = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      clicks.push(this.getAttribute("href"));
    });
    await load({ "/api/me": approved, "/api/state": state({ items }) });
    button($$("#theirs .item")[0], "Baixar").click();
    await tick(0);
    expect(clicks).toEqual(["/api/file?item=s&f=0&dl=1"]);
    button($$("#theirs .item")[2], "Baixar").click();
    await tick(0);
    expect($("#sheet").hidden).toBe(false);
    $(".sheet-backdrop").click();
    await tick(0);
    expect($("#sheet").hidden).toBe(true);
    expect(clicks).toHaveLength(1);
    button($$("#theirs .item")[2], "Baixar").click();
    await tick(0);
    $('.sheet-actions [data-answer="yes"]').click();
    await tick(0);
    expect(clicks[1]).toBe("/api/file?item=x&f=0&dl=1");
    expect($$("a")).toHaveLength(0);
  });

  test("sem escolher pasta baixa um zip", async () => {
    const clicks = [];
    vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function () {
      clicks.push(this.getAttribute("href"));
    });
    await load({ "/api/me": approved, "/api/state": state({ items }) });
    $$("#theirs input")[0].checked = true;
    $$("#theirs input")[0].dispatchEvent(new Event("change"));
    $$("#theirs input")[1].checked = true;
    $$("#theirs input")[1].dispatchEvent(new Event("change"));
    $("#get-selected").click();
    await tick(0);
    expect(clicks).toEqual(["/api/zip?items=s,p"]);
    $('.sheet-actions [data-answer="no"]').click();
  });

  test("com pasta escolhida salva arquivo por arquivo e retoma", async () => {
    const { root, written } = directory({ "Pasta/a.txt": 4, "Pasta/sub/b.txt": 10, "Pasta/c.txt": 99 });
    window.showDirectoryPicker = vi.fn(async () => root);
    const files = [
      { rel: "Pasta/a.txt", size: 10 },
      { rel: "Pasta/sub/b.txt", size: 10 },
      { rel: "Pasta/c.txt", size: 10 },
    ];
    const asked = [];
    await load({
      "/api/me": approved,
      "/api/state": state({ items: [items[1]] }),
      "/api/files": { files },
      "/api/file": (path, options) => {
        asked.push([path, options.headers]);
        if (path.includes("f=0")) return { raw: { ok: true, status: 206, body: stream([1, 2, 3], [4, 5, 6]) } };
        return { raw: { ok: true, status: 200, body: stream(new Array(10).fill(0)) } };
      },
    });
    $("#get-all").click();
    await tick(0);
    expect(window.showDirectoryPicker).toHaveBeenCalledWith({ mode: "readwrite" });
    expect(asked).toEqual([
      ["/api/file?item=p&f=0", { Range: "bytes=4-" }],
      ["/api/file?item=p&f=2", {}],
    ]);
    expect(written["Pasta/a.txt"]).toEqual({
      options: { keepExistingData: true },
      ops: [["truncate", 4], ["seek", 4], ["write", 3], ["write", 3], ["close"]],
    });
    expect(written["Pasta/c.txt"].options).toEqual({ keepExistingData: false });
    expect(written["Pasta/sub/b.txt"]).toBeUndefined();
    expect($("#theirs small").textContent).toBe("Baixado");
    expect($("#keep-open").hidden).toBe(true);
  });

  test("mostra o progresso e os erros ao salvar na pasta", async () => {
    const { root } = directory();
    window.showDirectoryPicker = vi.fn(async () => root);
    let release;
    let mode = "slow";
    await load({
      "/api/me": approved,
      "/api/state": state({ items: [items[1]] }),
      "/api/files": () => (mode === "nofiles" ? { status: 500, body: {} } : { files: [{ rel: "Pasta/a", size: 30 }] }),
      "/api/file": () =>
        mode === "slow"
          ? new Promise((r) => (release = () => r({ raw: { ok: true, status: 200, body: stream([1]) } })))
          : { raw: { ok: false, status: 500 } },
    });
    $("#get-all").click();
    await tick(0);
    expect($("#theirs small").textContent).toBe("Baixando 0%");
    expect($("#theirs .bar i").style.width).toBe("0%");
    expect($("#keep-open").hidden).toBe(false);
    release();
    await tick(0);
    expect($("#theirs small").textContent).toBe("Baixado");
    mode = "fail";
    $("#get-all").click();
    await tick(0);
    expect($("#theirs small").textContent).toBe("Não deu para baixar a");
    expect($("#theirs small").className).toBe("bad");
    mode = "nofiles";
    $("#get-all").click();
    await tick(0);
    expect($("#theirs small").textContent).toBe("Algo deu errado. Tente de novo.");
  });

  test("progresso sem erro mostra a mensagem padrão e itens vazios ficam completos", async () => {
    const { root } = directory();
    window.showDirectoryPicker = vi.fn(async () => root);
    await load({
      "/api/me": approved,
      "/api/state": state({ items: [{ id: "v", kind: "folder", name: "Vazia", size: 0, count: 1, risky: false }] }),
      "/api/files": { files: [{ rel: "Vazia/x", size: 0 }] },
    });
    $("#get-all").click();
    await tick(0);
    expect($("#theirs small").textContent).toBe("Baixado");
  });

  test("cancelar a escolha da pasta não baixa nada", async () => {
    window.showDirectoryPicker = vi.fn(async () => {
      throw new Error("cancelado");
    });
    const { calls } = await load({ "/api/me": approved, "/api/state": state({ items: [items[1]] }) });
    $("#get-all").click();
    await tick(0);
    expect(calls.some((c) => c.path.startsWith("/api/files"))).toBe(false);
  });
});

describe("miniaturas", () => {
  test("mostra as de quem criou a sala e gera as suas", async () => {
    const posted = [];
    const media = HTMLMediaElement.prototype;
    vi.spyOn(media, "src", "set").mockImplementation(function (url) {
      queueMicrotask(() => this.dispatchEvent(new Event(url.includes("quebrado") ? "error" : "loadeddata")));
    });
    vi.spyOn(media, "currentTime", "set").mockImplementation(function () {
      queueMicrotask(() => this.dispatchEvent(new Event("seeked")));
    });
    vi.spyOn(media, "duration", "get").mockReturnValueOnce(NaN).mockReturnValue(10);
    vi.spyOn(HTMLVideoElement.prototype, "videoWidth", "get").mockReturnValue(1920);
    vi.spyOn(HTMLVideoElement.prototype, "videoHeight", "get").mockReturnValue(1080);
    const drawImage = vi.fn();
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue({ drawImage });
    vi.spyOn(HTMLCanvasElement.prototype, "toDataURL")
      .mockReturnValueOnce("data:image/jpeg;base64,AA==")
      .mockReturnValueOnce("data:image/jpeg;base64,BB==")
      .mockReturnValueOnce("data:,");
    vi.stubGlobal(
      "Image",
      class {
        constructor() {
          this.on = {};
          this.naturalWidth = 600;
          this.naturalHeight = 300;
        }
        addEventListener(type, fn) {
          this.on[type] = fn;
        }
        set src(url) {
          queueMicrotask(() => (url.includes("ruim") ? this.on.error : this.on.load)(new Event("x")));
        }
      },
    );
    const revoke = vi.fn();
    vi.spyOn(URL, "createObjectURL").mockImplementation((f) => `blob:${f.name}`);
    vi.spyOn(URL, "revokeObjectURL").mockImplementation(revoke);
    const names = ["foto.png", "ruim.png", "clip.mp4", "quebrado.mp4", "nota.txt", "estranho.png"];
    let mine = [];
    await load({
      "/api/me": approved,
      "/api/state": () =>
        state({
          items: [
            { id: "h1", kind: "file", name: "praia.jpg", size: 1, count: 1, thumb: true },
            { id: "h2", kind: "file", name: "a.txt", size: 1, count: 1, thumb: false },
          ],
          mine,
        }),
      "/api/offer": (path, options) => {
        const { items } = JSON.parse(options.body);
        mine = items.map((item, i) => ({ id: `m${i}`, kind: "file", name: item.name, size: 1, count: 1 }));
        return { ids: mine.map((m) => m.id) };
      },
      "/api/thumb": (path, options) => {
        const body = JSON.parse(options.body);
        posted.push(body);
        return body.id === "m2" ? { status: 400, body: { error: "não" } } : { ok: true };
      },
    });
    const theirs = $$("#theirs .item");
    expect(theirs[0].querySelector(".item-icon img").getAttribute("src")).toBe("/api/thumb?item=h1");
    expect(theirs[1].querySelector(".item-icon img")).toBeNull();
    const type = (name) => (name.endsWith(".txt") ? "text/plain" : name.endsWith(".mp4") ? "video/mp4" : "image/png");
    pick(
      "#pick-files",
      names.map((name) => new File(["x"], name, { type: type(name) })),
    );
    for (let i = 0; i < 20; i++) await tick(0);
    expect(posted).toEqual([
      { id: "m0", thumb: "data:image/jpeg;base64,AA==" },
      { id: "m2", thumb: "data:image/jpeg;base64,BB==" },
    ]);
    expect(drawImage.mock.calls.map((c) => c.slice(1))).toEqual([
      [0, 0, 240, 120],
      [0, 0, 240, 135],
      [0, 0, 240, 120],
    ]);
    expect(revoke).toHaveBeenCalledTimes(5);
    const rows = $$("#mine .item");
    expect(rows.map((r) => r.querySelector(".item-icon img")?.getAttribute("src") ?? "")).toEqual([
      "data:image/jpeg;base64,AA==",
      "",
      "data:image/jpeg;base64,BB==",
      "",
      "",
      "",
    ]);
    vi.restoreAllMocks();
  });
});
