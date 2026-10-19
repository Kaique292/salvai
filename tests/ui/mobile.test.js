import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { loadMobile } from "./helpers.js";

const $ = (s) => document.querySelector(s);
const settle = () => vi.advanceTimersByTimeAsync(0);
const stateCalls = (calls) => calls.filter((c) => c.path === "/api/state").length;

const setHidden = (value) => Object.defineProperty(document, "hidden", { configurable: true, get: () => value });

async function boot(responses = {}) {
  const result = await loadMobile({ "/api/state": { computer: "PC", downloads: [] }, ...responses });
  await settle();
  return result;
}

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
  delete document.hidden;
});

describe("formato e qualidade", () => {
  test("inicia em MP4 com as qualidades de vídeo", async () => {
    await boot();
    expect($("#format").dataset.value).toBe("MP4");
    expect([...$("#quality").options].map((o) => o.value)).toEqual(["max", "1080", "720", "480"]);
    expect($('#format button[data-value="MP4"]').classList.contains("active")).toBe(true);
  });

  test("trocar para MP3 atualiza as qualidades e o botão ativo", async () => {
    await boot();
    $('#format button[data-value="MP3"]').click();
    expect($("#format").dataset.value).toBe("MP3");
    expect([...$("#quality").options].map((o) => o.textContent)).toEqual([
      "Máxima",
      "320 kbps",
      "192 kbps",
      "128 kbps",
    ]);
    expect($('#format button[data-value="MP3"]').classList.contains("active")).toBe(true);
    expect($('#format button[data-value="MP4"]').classList.contains("active")).toBe(false);
  });
});

describe("conexão", () => {
  test("mostra o computador conectado", async () => {
    await boot({ "/api/state": { computer: "Meu PC", downloads: [] } });
    expect($("#computer").textContent).toBe("Conectado ao Meu PC");
    expect($("#link-state").classList.contains("ok")).toBe(true);
    expect($("#offline").classList.contains("show")).toBe(false);
  });

  test("mostra desconectado quando a API falha", async () => {
    await boot({ "/api/state": { status: 500, body: { error: "falhou" } } });
    expect($("#computer").textContent).toBe("Desconectado");
    expect($("#offline").classList.contains("show")).toBe(true);
    expect($("#link-state").classList.contains("ok")).toBe(false);
  });

  test("mostra desconectado quando a resposta não é JSON", async () => {
    await boot();
    globalThis.fetch = window.fetch = vi.fn(async () => ({
      ok: false,
      status: 502,
      json: async () => {
        throw new Error("não é json");
      },
    }));
    await vi.advanceTimersByTimeAsync(5000);
    expect($("#computer").textContent).toBe("Desconectado");
  });
});

describe("aparelho desconectado no computador", () => {
  test("mostra o aviso de desconexão em vez do erro de conexão", async () => {
    await boot({
      "/api/state": {
        status: 403,
        body: { error: "Este aparelho foi desconectado no computador. Peça um QR code novo.", revoked: true },
      },
    });
    expect($("#offline").classList.contains("show")).toBe(true);
    expect($("#offline strong").textContent).toBe("Desconectado pelo computador");
    expect($("#offline span").textContent).toBe("Este aparelho foi desconectado no computador. Peça um QR code novo.");
  });

  test("outros erros mantêm o aviso padrão", async () => {
    await boot({ "/api/state": { status: 403, body: { error: "Abra pelo QR code" } } });
    expect($("#offline strong").textContent).toBe("Sem conexão com o computador");
  });
});

describe("lista de downloads", () => {
  test("mostra mensagem quando não há downloads", async () => {
    await boot();
    expect($("#downloads").textContent).toContain("Nenhum download ainda");
  });

  test("renderiza cada status em ordem inversa", async () => {
    const downloads = [
      { id: 1, url: "https://a", status: "done", format: "MP4", quality: "720", file_id: "a b", thumb: "t.jpg" },
      { id: 2, title: "Erro <x>", status: "error" },
      { id: 3, title: "Baixando", status: "downloading", progress: 42 },
      { id: 4, title: "Processando", status: "processing" },
      { id: 5, title: "Pausado", status: "paused", progress: 10 },
      { id: 6, title: "Fila", status: "queued", format: "MP3", quality: "320" },
      { id: 7, title: "Sem arquivo", status: "done", format: "MP4", quality: "max" },
    ];
    await boot({ "/api/state": { computer: "PC", downloads } });
    const items = [...document.querySelectorAll("#downloads .item")];
    expect(items).toHaveLength(7);
    expect(items.every((i) => i.classList.contains("new"))).toBe(true);
    expect(items[0].textContent).toContain("Sem arquivo");
    expect(items[0].querySelector("a.save")).toBeNull();
    expect(items[0].querySelector(".icon svg")).not.toBeNull();
    expect(items[1].textContent).toContain("Na fila · MP3 320");
    expect(items[2].textContent).toContain("Pausado · 10%");
    expect(items[3].textContent).toContain("Finalizando…");
    expect(items[3].querySelector(".bar span").style.width).toBe("100%");
    expect(items[4].textContent).toContain("Baixando no PC · 42%");
    expect(items[4].querySelector(".bar span").style.width).toBe("42%");
    expect(items[5].querySelector("strong").textContent).toBe("Erro <x>");
    expect(items[5].querySelector("small.error").textContent).toBe("");
    expect(items[6].querySelector("strong").textContent).toBe("https://a");
    expect(items[6].querySelector("img").getAttribute("src")).toBe("t.jpg");
    expect(items[6].textContent).toContain("Pronto no PC · MP4 720");
    expect(items[6].querySelector("a.save").getAttribute("href")).toBe("/api/file?id=a%20b&dl=1");
  });

  test("escapa caracteres especiais e mostra o erro", async () => {
    await boot({
      "/api/state": {
        computer: "PC",
        downloads: [{ id: 1, title: `&<>"'`, status: "error", error: "Falhou & parou" }],
      },
    });
    expect($("#downloads strong").innerHTML).toBe("&amp;&lt;&gt;\"'");
    expect($("#downloads small.error").textContent).toBe("Falhou & parou");
  });

  test("não re-renderiza quando nada mudou e marca itens já vistos", async () => {
    let downloads = [{ id: 1, title: "A", status: "done", format: "MP4", quality: "720" }];
    await boot({ "/api/state": () => ({ computer: "PC", downloads }) });
    const first = $("#downloads .item");
    await vi.advanceTimersByTimeAsync(5000);
    expect($("#downloads .item")).toBe(first);
    downloads = [...downloads, { id: 2, title: "B", status: "done", format: "MP4", quality: "720" }];
    await vi.advanceTimersByTimeAsync(5000);
    const items = [...document.querySelectorAll("#downloads .item")];
    expect(items[0].classList.contains("new")).toBe(true);
    expect(items[1].classList.contains("new")).toBe(false);
  });
});

describe("agendamento", () => {
  test("consulta a cada 1,5s quando há downloads ativos", async () => {
    const { calls } = await boot({
      "/api/state": { computer: "PC", downloads: [{ id: 1, title: "A", status: "downloading", progress: 1 }] },
    });
    expect(stateCalls(calls)).toBe(1);
    await vi.advanceTimersByTimeAsync(1499);
    expect(stateCalls(calls)).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(stateCalls(calls)).toBe(2);
  });

  test("consulta a cada 5s quando tudo terminou", async () => {
    const { calls } = await boot({
      "/api/state": { computer: "PC", downloads: [{ id: 1, title: "A", status: "error", error: "x" }] },
    });
    await vi.advanceTimersByTimeAsync(4999);
    expect(stateCalls(calls)).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(stateCalls(calls)).toBe(2);
  });

  test("consulta a cada 15s com a página oculta", async () => {
    setHidden(true);
    const { calls } = await boot();
    await vi.advanceTimersByTimeAsync(14999);
    expect(stateCalls(calls)).toBe(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(stateCalls(calls)).toBe(2);
  });

  test("ignora nova atualização enquanto outra está em andamento", async () => {
    let release;
    const { calls } = await loadMobile({
      "/api/state": () =>
        new Promise((r) => {
          release = () => r({ computer: "PC", downloads: [] });
        }),
      "/api/files": { files: [] },
    });
    $('.tabs button[data-tab="files"]').click();
    expect(stateCalls(calls)).toBe(1);
    release();
    await settle();
    expect($("#computer").textContent).toBe("Conectado ao PC");
  });

  test("atualiza ao voltar a ficar visível", async () => {
    const { calls } = await boot();
    const before = stateCalls(calls);
    setHidden(true);
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(stateCalls(calls)).toBe(before);
    setHidden(false);
    document.dispatchEvent(new Event("visibilitychange"));
    await settle();
    expect(stateCalls(calls)).toBeGreaterThan(before);
  });
});

describe("abas", () => {
  test("mostra os arquivos do PC e volta para downloads", async () => {
    const files = [
      { name: "Música <1>", id: "m1", kind: "audio", folder: "Músicas", size_mb: 3.2 },
      { name: "Vídeo", id: "v1", kind: "video", folder: "", size_mb: 10 },
    ];
    const { calls } = await boot({ "/api/files": { files } });
    $('.tabs button[data-tab="files"]').click();
    await settle();
    expect($("#downloads").hidden).toBe(true);
    expect($("#files").hidden).toBe(false);
    expect($('.tabs button[data-tab="files"]').classList.contains("active")).toBe(true);
    expect($('.tabs button[data-tab="downloads"]').classList.contains("active")).toBe(false);
    const items = [...document.querySelectorAll("#files .item")];
    expect(items).toHaveLength(2);
    expect($("#files .files-head span").textContent).toBe("2 arquivos salvos pelo Salvaí");
    expect(items[0].querySelector(".icon.play").textContent).toBe("♪");
    expect(items[0].querySelector(".icon.play").dataset.play).toBe("m1");
    expect(items[0].querySelector("strong").textContent).toBe("Música <1>");
    expect(items[0].querySelector("small").textContent).toBe("Músicas · 3.2 MB");
    expect(items[1].querySelector(".icon.play").textContent).toBe("▶");
    expect(items[1].querySelector("small").textContent).toBe("10 MB");
    expect(items[1].querySelector("a.save").getAttribute("href")).toBe("/api/file?id=v1&dl=1");
    const first = $("#files .item");
    await vi.advanceTimersByTimeAsync(5000);
    expect($("#files .item")).toBe(first);
    expect(calls.filter((c) => c.path === "/api/files").length).toBe(2);
    $('.tabs button[data-tab="downloads"]').click();
    await settle();
    expect($("#downloads").hidden).toBe(false);
    expect($("#files").hidden).toBe(true);
  });

  test("mostra mensagem quando nada foi salvo pelo Salvaí", async () => {
    await boot({ "/api/files": { files: [] } });
    $('.tabs button[data-tab="files"]').click();
    await settle();
    expect($("#files").textContent).toContain("Nada salvo pelo Salvaí ainda");
  });

  test("conta um arquivo no singular", async () => {
    await boot({ "/api/files": { files: [{ name: "a.mp4", id: "a", kind: "video", folder: "", size_mb: 1 }] } });
    $('.tabs button[data-tab="files"]').click();
    await settle();
    expect($("#files .files-head span").textContent).toBe("1 arquivo salvo pelo Salvaí");
  });
});

const VIDEO = { name: "Aula <1>.mp4", id: "v1", kind: "video", folder: "Química", size_mb: 12 };
const MUSIC = { name: "Lofi.mp3", id: "m1", kind: "audio", folder: "", size_mb: 3 };

async function openFiles(responses = {}) {
  const result = await boot({ "/api/files": { files: [VIDEO, MUSIC] }, ...responses });
  $('.tabs button[data-tab="files"]').click();
  await settle();
  return result;
}

const sheetButtons = () => [...document.querySelectorAll("#sheet-actions button")];
const press = (label) =>
  sheetButtons()
    .find((b) => b.textContent === label)
    .click();
const posts = (calls, path) => calls.filter((c) => c.path === path).map((c) => JSON.parse(c.options.body));

describe("ações nos arquivos", () => {
  test("menu de um arquivo abre e fecha com animação", async () => {
    await openFiles();
    document.querySelector('[data-more="v1"]').click();
    expect($("#sheet").hidden).toBe(false);
    expect($("#sheet-title").textContent).toBe("Aula <1>.mp4");
    expect(sheetButtons().map((b) => b.textContent)).toEqual([
      "Assistir no celular",
      "Tirar da lista",
      "Apagar do computador",
      "Cancelar",
    ]);
    expect(sheetButtons()[2].className).toBe("danger");
    await vi.advanceTimersByTimeAsync(16);
    expect($("#sheet").classList.contains("show")).toBe(true);
    press("Cancelar");
    expect($("#sheet").classList.contains("show")).toBe(false);
    await vi.advanceTimersByTimeAsync(250);
    expect($("#sheet").hidden).toBe(true);
    document.querySelector('[data-more="m1"]').click();
    expect(sheetButtons()[0].textContent).toBe("Ouvir no celular");
    document.querySelector("#sheet [data-close]").click();
    expect($("#sheet").classList.contains("show")).toBe(false);
  });

  test("tirar da lista avisa que o arquivo continua no PC", async () => {
    const { calls } = await openFiles({ "/api/files/forget": { ok: true } });
    document.querySelector('[data-more="v1"]').click();
    press("Tirar da lista");
    await settle();
    expect(posts(calls, "/api/files/forget")).toEqual([{ id: "v1" }]);
    expect($("#toast").className).toBe("toast show");
    expect($("#toast").textContent).toContain("continua no computador");
    await vi.advanceTimersByTimeAsync(2800);
    expect($("#toast").classList.contains("show")).toBe(false);
  });

  test("apagar do PC pede confirmação e manda para a Lixeira", async () => {
    const { calls } = await openFiles({ "/api/files/trash": { trashed: "Aula <1>.mp4" } });
    document.querySelector('[data-more="v1"]').click();
    press("Apagar do computador");
    expect($("#sheet-title").textContent).toBe("Apagar do computador?");
    expect($("#sheet-desc").textContent).toContain('"Aula <1>.mp4" vai para a Lixeira do computador');
    expect(posts(calls, "/api/files/trash")).toEqual([]);
    press("Apagar");
    await settle();
    expect(posts(calls, "/api/files/trash")).toEqual([{ id: "v1" }]);
    expect($("#toast").textContent).toBe("Arquivo enviado para a Lixeira do computador.");
  });

  test("cancelar a confirmação não apaga nada", async () => {
    const { calls } = await openFiles();
    document.querySelector('[data-more="v1"]').click();
    press("Apagar do computador");
    press("Cancelar");
    await settle();
    expect(posts(calls, "/api/files/trash")).toEqual([]);
  });

  test("limpar lista pede confirmação", async () => {
    const { calls } = await openFiles({ "/api/files/clear": { ok: true } });
    $("#files [data-clear]").click();
    expect($("#sheet-title").textContent).toBe("Limpar a lista?");
    press("Limpar lista");
    await settle();
    expect(posts(calls, "/api/files/clear")).toEqual([{ id: "" }]);
    expect($("#toast").textContent).toContain("Lista limpa");
  });

  test("mostra o erro do PC em vermelho", async () => {
    await openFiles({ "/api/files/trash": { status: 400, body: { error: "Arquivo não encontrado." } } });
    document.querySelector('[data-more="v1"]').click();
    press("Apagar do computador");
    press("Apagar");
    await settle();
    expect($("#toast").className).toBe("toast show error");
    expect($("#toast").textContent).toBe("Arquivo não encontrado.");
  });

  test("ignora cliques fora dos botões e arquivos que sumiram", async () => {
    await openFiles();
    $("#files .meta").click();
    const stale = document.createElement("button");
    stale.dataset.more = "sumiu";
    $("#files").appendChild(stale);
    stale.click();
    expect($("#sheet").hidden).toBe(true);
  });
});

describe("assistir no celular", () => {
  let play;

  beforeEach(() => {
    play = vi.fn(() => Promise.resolve());
    HTMLMediaElement.prototype.play = play;
    HTMLMediaElement.prototype.pause = vi.fn();
    HTMLMediaElement.prototype.load = vi.fn();
  });

  test("toca o vídeo pelo ícone e fecha parando tudo", async () => {
    await openFiles();
    document.querySelector('[data-play="v1"]').click();
    await settle();
    const video = $("#player-video");
    expect($("#player").hidden).toBe(false);
    expect($("#player-title").textContent).toBe("Aula <1>.mp4");
    expect(video.getAttribute("src")).toBe("/api/file?id=v1");
    expect($("#player").classList.contains("audio")).toBe(false);
    expect(play).toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(16);
    expect($("#player").classList.contains("show")).toBe(true);
    $("#player-close").click();
    expect(video.pause).toHaveBeenCalled();
    expect(video.hasAttribute("src")).toBe(false);
    expect($("#player").hidden).toBe(true);
  });

  test("música abre no modo áudio pelo menu", async () => {
    await openFiles();
    document.querySelector('[data-more="m1"]').click();
    press("Ouvir no celular");
    await settle();
    expect($("#sheet").classList.contains("show")).toBe(false);
    expect($("#player").classList.contains("audio")).toBe(true);
    expect($("#player-video").getAttribute("src")).toBe("/api/file?id=m1");
  });

  test("avisa quando o formato não toca no celular", async () => {
    play.mockImplementation(() => Promise.reject(new Error("bloqueado")));
    await openFiles();
    document.querySelector('[data-play="v1"]').click();
    await settle();
    $("#player-video").dispatchEvent(new Event("error"));
    expect($("#player-error").textContent).toContain("não consegue tocar esse formato");
    $("#player-close").click();
    $("#player-video").dispatchEvent(new Event("error"));
    document.querySelector('[data-play="v1"]').click();
    expect($("#player-error").textContent).toBe("");
  });

  test("usa a versão convertida pelo PC quando o celular não toca o original", async () => {
    const { calls } = await openFiles({ "/api/play": { direct: false, stream: "/api/stream/index.m3u8?t=abc" } });
    document.querySelector('[data-play="v1"]').click();
    await settle();
    expect(calls.some((c) => c.path === "/api/play?id=v1")).toBe(true);
    expect($("#player-video").getAttribute("src")).toBe("/api/stream/index.m3u8?t=abc");
  });

  test("se o PC não responde, tenta o arquivo original", async () => {
    await openFiles({ "/api/play": { status: 500, body: {} } });
    document.querySelector('[data-play="v1"]').click();
    await settle();
    expect($("#player-video").getAttribute("src")).toBe("/api/file?id=v1");
  });

  test("fechar antes do PC responder não começa a tocar", async () => {
    let answer;
    await openFiles({ "/api/play": () => new Promise((resolve) => (answer = resolve)) });
    document.querySelector('[data-play="v1"]').click();
    $("#player-close").click();
    answer({ direct: true });
    await settle();
    expect($("#player-video").hasAttribute("src")).toBe(false);
    expect(HTMLMediaElement.prototype.play).not.toHaveBeenCalled();
  });
});

describe("envio de link", () => {
  test("envia o link com formato e qualidade e limpa o campo", async () => {
    const { calls } = await boot({ "/api/add": { ok: true } });
    $('#format button[data-value="MP3"]').click();
    $("#quality").value = "192";
    $("#url").value = "  https://youtu.be/x  ";
    $("#add-form").dispatchEvent(new Event("submit", { cancelable: true }));
    expect($("#add-btn").disabled).toBe(true);
    await settle();
    const add = calls.find((c) => c.path === "/api/add");
    expect(add.options.method).toBe("POST");
    expect(add.options.cache).toBe("no-cache");
    expect(add.options.headers).toEqual({ "X-Salvai": "1", "Content-Type": "application/json" });
    expect(JSON.parse(add.options.body)).toEqual({ url: "https://youtu.be/x", format: "MP3", quality: "192" });
    expect($("#url").value).toBe("");
    expect($("#form-msg").className).toBe("form-msg ok");
    expect($("#form-msg").textContent).toBe("Enviado! O download começou no computador.");
    expect($("#add-btn").disabled).toBe(false);
    expect(stateCalls(calls)).toBe(2);
  });

  test("mostra o erro retornado pelo PC", async () => {
    await boot({ "/api/add": { status: 400, body: { error: "Link inválido" } } });
    $("#url").value = "abc";
    $("#add-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    expect($("#form-msg").className).toBe("form-msg error");
    expect($("#form-msg").textContent).toBe("Link inválido");
    expect($("#url").value).toBe("abc");
    expect($("#add-btn").disabled).toBe(false);
  });

  test("mostra erro genérico quando o PC não informa o motivo", async () => {
    await boot({ "/api/add": { status: 500, body: {} } });
    $("#add-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await settle();
    expect($("#form-msg").textContent).toBe("Algo deu errado");
  });
});

describe("dica do iPhone", () => {
  test("aparece no iPhone", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0)");
    await boot();
    expect($("#ios-tip").classList.contains("show")).toBe(true);
  });

  test("não aparece em outros aparelhos", async () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Linux; Android 14)");
    await boot();
    expect($("#ios-tip").classList.contains("show")).toBe(false);
  });
});

describe("enviar para o PC", () => {
  const fakeFile = (name, size) => ({ name, size, slice: (a, b) => `${name}:${a}-${b}` });
  const rows = () => [...document.querySelectorAll("#send-list .send-row")];
  const puts = (calls) => calls.filter((c) => c.path.startsWith("/api/upload"));

  function choose(files) {
    const input = $("#send-input");
    Object.defineProperty(input, "files", { configurable: true, get: () => files });
    input.dispatchEvent(new Event("change"));
  }

  function planner(chunk = 4) {
    let n = 0;
    return (path, options) => ({
      chunk,
      uploads: JSON.parse(options.body).files.map(() => ({ id: `j${n++}`, offset: 0 })),
    });
  }

  function receiver() {
    return (path, options) => {
      const [, offset] = path.match(/offset=(\d+)/);
      const [a, b] = options.body.split(":")[1].split("-").map(Number);
      return { received: Number(offset) + b - a };
    };
  }

  function lock() {
    const release = vi.fn(async () => {});
    const request = vi.fn(async () => ({ release }));
    Object.defineProperty(navigator, "wakeLock", { configurable: true, value: { request } });
    return { request, release };
  }

  afterEach(() => {
    delete navigator.wakeLock;
  });

  test("o botão abre o seletor de arquivos", async () => {
    await boot();
    const spy = vi.spyOn($("#send-input"), "click").mockImplementation(() => {});
    $("#send-btn").click();
    expect(spy).toHaveBeenCalledTimes(1);
    expect($("#send-panel").hidden).toBe(true);
  });

  test("não faz nada quando nenhum arquivo é escolhido", async () => {
    const { calls } = await boot();
    choose([]);
    await settle();
    expect(calls.some((c) => c.path === "/api/send")).toBe(false);
  });

  test("envia em pedaços, mostra o progresso e segura a tela acesa", async () => {
    const { request, release } = lock();
    let hold;
    const { calls } = await boot({
      "/api/send": planner(4),
      "/api/upload": (path, options) => {
        if (options.body === "video.mp4:4-8") return new Promise((r) => (hold = r));
        return receiver()(path, options);
      },
    });
    choose([fakeFile("video.mp4", 10)]);
    await settle();
    const plan = calls.find((c) => c.path === "/api/send");
    expect(plan.options.headers).toEqual({ "X-Salvai": "1", "Content-Type": "application/json" });
    expect(JSON.parse(plan.options.body)).toEqual({ files: [{ name: "video.mp4", size: 10 }] });
    expect($("#send-panel").hidden).toBe(false);
    expect($("#send-summary").textContent).toBe("Enviando 1 de 1…");
    expect($("#send-keep").hidden).toBe(false);
    expect($("#send-clear").hidden).toBe(true);
    expect(rows()[0].querySelector("small").textContent).toBe("1 KB de 1 KB · 40%");
    expect(rows()[0].querySelector(".bar span").style.width).toBe("40%");
    expect(request).toHaveBeenCalledWith("screen");
    const first = puts(calls)[0];
    expect(first.path).toBe("/api/upload?t=j0&offset=0");
    expect(first.options.method).toBe("PUT");
    expect(first.options.headers).toEqual({ "X-Salvai": "1", "Content-Type": "application/octet-stream" });
    hold({ received: 8 });
    await settle();
    expect(puts(calls).map((c) => c.options.body)).toEqual(["video.mp4:0-4", "video.mp4:4-8", "video.mp4:8-10"]);
    expect(rows()[0].querySelector("small").className).toBe("done");
    expect(rows()[0].querySelector("small").textContent).toBe("No computador · 1 KB");
    expect($("#send-summary").textContent).toBe("1 arquivo enviado para o PC");
    expect($("#send-keep").hidden).toBe(true);
    expect($("#send-clear").hidden).toBe(false);
    expect(release).toHaveBeenCalledTimes(1);
    $("#send-clear").click();
    expect($("#send-panel").hidden).toBe(true);
  });

  test("divide listas grandes e mostra tamanhos legíveis", async () => {
    const { calls } = await boot({ "/api/send": planner(1 << 30), "/api/upload": receiver() });
    const files = Array.from({ length: 50 }, (_, i) => fakeFile(`f${i}.txt`, 0));
    files.push(fakeFile("grande.mov", 3 * 1024 ** 3), fakeFile("medio.mp4", 5 * 1024 ** 2));
    choose(files);
    await settle();
    expect(calls.filter((c) => c.path === "/api/send")).toHaveLength(2);
    expect(rows()).toHaveLength(52);
    expect(rows()[50].querySelector("small").textContent).toBe("No computador · 3,00 GB");
    expect(rows()[51].querySelector("small").textContent).toBe("No computador · 5,0 MB");
    expect(rows()[0].querySelector("small").textContent).toBe("No computador · 0 KB");
    expect($("#send-summary").textContent).toBe("52 arquivos enviados para o PC");
  });

  test("ajusta a posição quando o PC já recebeu parte do arquivo", async () => {
    let first = true;
    const { calls } = await boot({
      "/api/send": () => ({ chunk: 4, uploads: [{ id: "j", offset: 2 }] }),
      "/api/upload": (path, options) => {
        if (first) {
          first = false;
          return { status: 409, body: { received: 6 } };
        }
        return receiver()(path, options);
      },
    });
    choose([fakeFile("a.bin", 8)]);
    await settle();
    expect(puts(calls).map((c) => c.options.body)).toEqual(["a.bin:2-6"]);
    await vi.advanceTimersByTimeAsync(300);
    expect(puts(calls).map((c) => c.options.body)).toEqual(["a.bin:2-6", "a.bin:6-8"]);
    expect($("#send-summary").textContent).toBe("1 arquivo enviado para o PC");
  });

  test("tenta de novo quando a conexão cai e desiste depois de muitas falhas", async () => {
    let failures = 1;
    const { calls } = await boot({
      "/api/send": planner(4),
      "/api/upload": (path, options) => {
        if (failures-- > 0) throw new TypeError("Failed to fetch");
        return receiver()(path, options);
      },
    });
    choose([fakeFile("a.bin", 4)]);
    await settle();
    expect(puts(calls)).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1500);
    expect($("#send-summary").textContent).toBe("1 arquivo enviado para o PC");
    failures = 21;
    choose([fakeFile("b.bin", 4)]);
    await vi.advanceTimersByTimeAsync(1500 * 21);
    expect(rows()[1].querySelector("small.error").textContent).toBe(
      "A conexão com o computador caiu. Confira o Wi-Fi.",
    );
    expect($("#send-summary").textContent).toBe("1 arquivo não foi enviado");
    rows()[1].querySelector("strong").click();
    expect(calls.filter((c) => c.path === "/api/send")).toHaveLength(2);
    rows()[1].querySelector("[data-retry]").click();
    await settle();
    expect(rows()[1].querySelector("small").className).toBe("done");
    expect(calls.filter((c) => c.path === "/api/send")).toHaveLength(3);
  });

  test("mostra o erro do PC e o erro ao preparar o envio", async () => {
    let plans = 0;
    await boot({
      "/api/send": (path, options) => {
        plans++;
        if (plans === 2) return { status: 400, body: { error: "Falta espaço no computador." } };
        return planner(4)(path, options);
      },
      "/api/upload": { status: 400, body: { error: "Esse envio não existe mais." } },
    });
    const many = Array.from({ length: 51 }, (_, i) => fakeFile(`f${i}.bin`, 0));
    choose(many);
    await settle();
    expect(rows().filter((r) => r.querySelector("small.done"))).toHaveLength(50);
    expect(rows()[50].querySelector("small.error").textContent).toBe("Falta espaço no computador.");
    choose([fakeFile("x.bin", 3)]);
    await settle();
    expect(rows()[51].querySelector("small.error").textContent).toBe("Esse envio não existe mais.");
    expect($("#send-summary").textContent).toBe("2 arquivos não foram enviados");
  });

  test("mostra na fila enquanto outro arquivo está sendo enviado", async () => {
    let hold;
    await boot({
      "/api/send": planner(4),
      "/api/upload": (path, options) =>
        options.body === "a.bin:0-4" ? new Promise((r) => (hold = r)) : receiver()(path, options),
    });
    choose([fakeFile("a.bin", 4)]);
    await settle();
    choose([fakeFile("b.bin", 2048)]);
    await settle();
    expect(rows()[1].querySelector("small").textContent).toBe("Na fila · 2 KB");
    expect($("#send-summary").textContent).toBe("Enviando 1 de 2…");
    hold({ received: 4 });
    await settle();
    expect($("#send-summary").textContent).toBe("2 arquivos enviados para o PC");
  });

  test("pede confirmação para sair durante o envio e reacende a tela ao voltar", async () => {
    const { request } = lock();
    let hold;
    await boot({ "/api/send": planner(4), "/api/upload": () => new Promise((r) => (hold = r)) });
    const leave = () => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    };
    expect(leave()).toBe(false);
    setHidden(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(request).not.toHaveBeenCalled();
    choose([fakeFile("a.bin", 4)]);
    await settle();
    expect(leave()).toBe(true);
    setHidden(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(request).toHaveBeenCalledTimes(1);
    setHidden(false);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(request).toHaveBeenCalledTimes(2);
    hold({ received: 4 });
    await settle();
  });

  test("funciona sem trava de tela ou quando ela falha", async () => {
    const release = vi.fn(async () => {
      throw new Error("já liberada");
    });
    Object.defineProperty(navigator, "wakeLock", {
      configurable: true,
      value: { request: vi.fn().mockRejectedValueOnce(new Error("negado")).mockResolvedValue({ release }) },
    });
    await boot({ "/api/send": planner(4), "/api/upload": receiver() });
    choose([fakeFile("a.bin", 4)]);
    await settle();
    choose([fakeFile("b.bin", 4)]);
    await settle();
    expect(release).toHaveBeenCalledTimes(1);
    delete navigator.wakeLock;
    choose([fakeFile("c.bin", 4)]);
    await settle();
    expect($("#send-summary").textContent).toBe("3 arquivos enviados para o PC");
  });
});
