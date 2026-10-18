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
    expect(add.options.headers).toEqual({ "Content-Type": "application/json" });
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
