import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import { loadApp } from "./helpers.js";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const tick = (ms = 0) => vi.advanceTimersByTimeAsync(ms);
const click = (el) => el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
const visible = () =>
  $$("[data-rview]")
    .filter((el) => !el.hidden)
    .map((el) => el.dataset.rview);
const button = (root, label) => [...root.querySelectorAll("button")].find((b) => b.textContent === label);

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function hostState(extra = {}) {
  return {
    role: "host",
    phase: "open",
    name: "Kaique",
    host: "Kaique",
    url: "https://sala.trycloudflare.com",
    code: "ABC 123",
    people: [
      { id: "p1", name: "<Ana>", device: "Android", state: "pending", online: true },
      { id: "p2", name: "Bruno", device: "Windows", state: "approved", online: true },
      { id: "p3", name: "Caio", device: "iPhone", state: "approved", online: false },
    ],
    mine: [
      { id: "m1", kind: "folder", name: "Fotos", size: 52428800, count: 48, risky: false, fetched: ["Bruno", "Caio"] },
      { id: "m2", kind: "file", name: "nota.txt", size: 500, count: 1, risky: false, fetched: [] },
    ],
    theirs: [
      {
        id: "t1",
        kind: "file",
        name: "video.mp4",
        size: 734003200,
        count: 1,
        risky: false,
        owner: "Bruno",
        progress: { state: "sending", done: 367001600, total: 734003200 },
      },
      { id: "t2", kind: "file", name: "setup.exe", size: 2048, count: 1, risky: true, owner: "Bruno", progress: null },
      {
        id: "t3",
        kind: "folder",
        name: "Músicas",
        size: 5 * 1024 ** 5,
        count: 1,
        risky: false,
        owner: "Ana",
        progress: { state: "done", done: 1, total: 1 },
      },
      {
        id: "t4",
        kind: "file",
        name: "falhou.zip",
        size: 10,
        count: 1,
        risky: false,
        owner: "",
        progress: { state: "error", done: 0, total: 10, error: "" },
      },
      {
        id: "t5",
        kind: "file",
        name: "vazio",
        size: 0,
        count: 1,
        risky: false,
        owner: "Ana",
        progress: { state: "waiting", done: 0, total: 0 },
      },
      {
        id: "t6",
        kind: "file",
        name: "caiu.bin",
        size: 10,
        count: 1,
        risky: false,
        owner: "Ana",
        progress: { state: "error", done: 0, total: 10, error: "A conexão caiu" },
      },
      {
        id: "t7",
        kind: "file",
        name: "zero.bin",
        size: 0,
        count: 1,
        risky: false,
        owner: "Ana",
        progress: { state: "sending", done: 0, total: 0 },
      },
    ],
    ...extra,
  };
}

async function setup(states, overrides = {}) {
  let n = 0;
  const list = Array.isArray(states) ? states : [states];
  const result = await loadApp({
    room_status: async () => list[Math.min(n++, list.length - 1)],
    ...overrides,
  });
  window.dispatchEvent(new Event("pywebviewready"));
  await tick(100);
  return result;
}

async function openModal() {
  click($("#room-btn"));
  await tick(0);
}

describe("sala de troca", () => {
  test("começa na tela de escolha com o nome lembrado", async () => {
    const { api } = await setup([
      { role: null, phase: "idle", name: "Kaique" },
      { role: null, phase: "idle", name: "Outro" },
    ]);
    await openModal();
    expect($("#room-modal").classList.contains("open")).toBe(true);
    expect(visible()).toEqual(["start"]);
    expect($("#room-name").value).toBe("Kaique");
    await tick(1000);
    expect($("#room-name").value).toBe("Kaique");
    expect(api.room_status).toHaveBeenCalledTimes(2);
    expect($("#room-btn").classList.contains("on")).toBe(false);
  });

  test("sem nome salvo deixa o campo vazio", async () => {
    await setup({ role: null, phase: "idle", name: "" });
    await openModal();
    expect($("#room-name").value).toBe("");
  });

  test("criar sala mostra o progresso e depois a sala aberta", async () => {
    const { api } = await setup(
      { role: null, phase: "idle", name: "" },
      {
        room_create: async () => ({ role: "host", phase: "starting", step: "Baixando…", progress: 40 }),
      },
    );
    await openModal();
    $("#room-name").value = "  Kaique ";
    click($("#room-create"));
    await tick(0);
    expect(api.room_create).toHaveBeenCalledWith("Kaique");
    expect(visible()).toEqual(["busy"]);
    expect($("#room-busy-title").textContent).toBe("Abrindo a sala…");
    expect($("#room-busy-text").textContent).toBe("Baixando…");
    expect($("#room-busy-bar").hidden).toBe(false);
    expect($("#room-busy-bar i").style.width).toBe("40%");
    expect($("#room-btn").classList.contains("on")).toBe(true);
  });

  test("tela de espera sem passo e sem barra", async () => {
    await setup([
      { role: "host", phase: "starting", progress: null },
      { role: "guest", phase: "joining" },
      { role: "guest", phase: "pending" },
    ]);
    await openModal();
    expect($("#room-busy-text").textContent).toBe("Isso leva alguns segundos.");
    expect($("#room-busy-bar").hidden).toBe(true);
    expect($("#room-busy-bar i").style.width).toBe("0%");
    await tick(1000);
    expect($("#room-busy-title").textContent).toBe("Entrando na sala…");
    await tick(1000);
    expect($("#room-busy-title").textContent).toBe("Esperando aprovação");
    expect($("#room-busy-text").textContent).toContain("deixar você entrar");
  });

  test("mostra quando a sala fechou ou deu erro", async () => {
    const { api } = await setup(
      [
        { role: "host", phase: "error", error: "sem internet" },
        { role: "host", phase: "closed", reason: "Fechou por inatividade", error: "" },
      ],
      { room_close: async () => ({ role: null, phase: "idle", name: "K" }) },
    );
    await openModal();
    expect(visible()).toEqual(["ended"]);
    expect($("#room-ended-title").textContent).toBe("Não deu para abrir a sala");
    expect($("#room-ended-text").textContent).toBe("sem internet");
    await tick(1000);
    expect($("#room-ended-title").textContent).toBe("A sala fechou");
    expect($("#room-ended-text").textContent).toBe("Fechou por inatividade");
    click($("#room-again"));
    await tick(0);
    expect(api.room_close).toHaveBeenCalledTimes(1);
    expect(visible()).toEqual(["start"]);
  });

  test("sala aberta como anfitrião", async () => {
    const { api } = await setup(hostState(), {
      room_approve: async () => hostState({ people: [] }),
      room_kick: async () => hostState({ people: [] }),
      room_remove: async () => hostState(),
      room_download: async () => hostState(),
    });
    await openModal();
    expect(visible()).toEqual(["open"]);
    expect($("#room-share").hidden).toBe(false);
    expect($("#room-code-text").textContent).toBe("ABC 123");
    expect($("#room-url").textContent).toBe("https://sala.trycloudflare.com");
    expect($("#room-close").textContent).toBe("Fechar sala");
    expect($("#room-with").innerHTML).toBe("");
    expect($("#room-badge").textContent).toBe("1");
    const rows = $$("#room-people .dev-row");
    expect(rows[0].classList.contains("pending")).toBe(true);
    expect(rows[0].querySelector("strong").textContent).toBe("<Ana>");
    expect(rows[0].querySelector("small").textContent).toBe("Android · Quer entrar na sala");
    expect(rows[1].querySelector(".dev-dot").classList.contains("on")).toBe(true);
    expect(rows[1].querySelector("small").textContent).toBe("Windows · Na sala agora");
    expect(rows[2].querySelector("small").textContent).toBe("iPhone · Sem sinal");
    click(button(rows[0], "Recusar"));
    click(button(rows[0], "Deixar entrar"));
    click(button(rows[1], "Tirar da sala"));
    expect(api.room_kick.mock.calls).toEqual([["p1"], ["p2"]]);
    expect(api.room_approve).toHaveBeenCalledWith("p1");
    await tick(0);
    expect($("#room-people .dev-empty").textContent).toContain("Ninguém entrou ainda");
  });

  test("lista do que receber e do que compartilhar", async () => {
    const { api } = await setup(hostState(), { room_remove: async () => hostState() });
    await openModal();
    const items = $$("#room-theirs .room-item");
    const text = (i) => items[i].querySelector("small").textContent;
    expect(text(0)).toBe("Recebendo 50% · 350 MB de 700 MB");
    expect(items[0].querySelector(".room-item-bar i").style.width).toBe("50%");
    expect(button(items[0], "Baixar")).toBeUndefined();
    expect(text(1)).toBe("2,0 KB · de Bruno");
    expect(items[1].querySelector(".room-tag").textContent).toBe("programa");
    expect(text(2)).toBe("Recebido · 5120 TB · 1 arquivo");
    expect(items[2].querySelector("small").className).toBe("ok");
    expect(text(3)).toBe("Não deu para receber");
    expect(items[3].querySelector("small").className).toBe("bad");
    expect(text(4)).toBe("Na fila");
    expect(text(5)).toBe("A conexão caiu");
    expect(text(6)).toBe("Recebendo 0% · 0 B de 0 B");
    click(button(items[2], "Mostrar"));
    expect(api.room_reveal).toHaveBeenCalledWith("t3");
    expect($("#room-theirs-count").textContent).toBe("7");
    expect($("#room-mine-count").textContent).toBe("2");
    const mine = $$("#room-mine .room-item");
    expect(mine[0].querySelector("small").textContent).toBe("50 MB · 48 arquivos · baixado por Bruno, Caio");
    expect(mine[1].querySelector("small").textContent).toBe("500 B");
    click(button(mine[1], "Tirar"));
    expect(api.room_remove).toHaveBeenCalledWith("m2");
  });

  test("abas e progresso do que você compartilha", async () => {
    const mine = [
      { id: "a", kind: "file", name: "a", size: 10, count: 1, progress: { state: "sending", done: 5, total: 10 } },
      { id: "b", kind: "file", name: "b", size: 10, count: 1, progress: { state: "waiting", done: 0, total: 10 } },
      { id: "c", kind: "file", name: "c", size: 10, count: 1, progress: { state: "done", done: 10, total: 10 } },
      { id: "d", kind: "file", name: "d", size: 10, count: 1, progress: { state: "error", done: 0, total: 10 } },
    ];
    await setup({ role: "guest", phase: "open", host: "<Kaique>", name: "Bia", mine, theirs: [] });
    await openModal();
    expect($("#room-share").hidden).toBe(true);
    expect($("#room-close").textContent).toBe("Sair da sala");
    expect($("#room-with").innerHTML).toBe("Você está na sala de <strong>&lt;Kaique&gt;</strong>.");
    expect($("#room-theirs .room-empty").textContent).toContain("Nada para receber");
    expect($("#room-get-all").disabled).toBe(true);
    expect($("#room-theirs-count").textContent).toBe("");
    expect($("#room-pane-mine").hidden).toBe(true);
    click($('.room-tabs button[data-rtab="mine"]'));
    expect($("#room-pane-mine").hidden).toBe(false);
    expect($("#room-pane-theirs").hidden).toBe(true);
    expect($('.room-tabs button[data-rtab="mine"]').getAttribute("aria-selected")).toBe("true");
    const texts = $$("#room-mine small").map((s) => s.textContent);
    expect(texts).toEqual([
      "Enviando 50% · 5 B de 10 B",
      "Pedido, já vai começar",
      "Enviado · 10 B",
      "Não deu para enviar",
    ]);
    await tick(1000);
    expect($("#room-pane-mine").hidden).toBe(false);
  });

  test("lista vazia do que compartilhar e redesenho só quando muda", async () => {
    const empty = { role: "host", phase: "open", people: [], mine: [], theirs: [], url: "u", code: "c" };
    await setup([empty, empty, { ...empty, mine: [{ id: "x", kind: "file", name: "x", size: 1, count: 1 }] }]);
    await openModal();
    expect($("#room-mine .room-empty").textContent).toContain("Adicione arquivos");
    const before = $("#room-mine .room-empty");
    await tick(1000);
    expect($("#room-mine .room-empty")).toBe(before);
    await tick(1000);
    expect($$("#room-mine .room-item")).toHaveLength(1);
  });

  test("seleção, baixar e aviso de programas", async () => {
    const { api } = await setup(hostState(), { room_download: async () => hostState({ notice: "Escolha uma pasta" }) });
    await openModal();
    expect($("#room-get-selected").disabled).toBe(true);
    expect($("#room-get-all").disabled).toBe(false);
    const boxes = $$("#room-theirs input[type=checkbox]");
    boxes[0].checked = true;
    boxes[0].dispatchEvent(new Event("change"));
    expect($("#room-get-selected").disabled).toBe(false);
    click($("#room-get-selected"));
    await tick(0);
    expect(api.room_download).toHaveBeenLastCalledWith(["t1"]);
    expect($("#room-notice").textContent).toBe("Escolha uma pasta");
    expect($("#room-msg").textContent).toBe("");
    const again = $$("#room-theirs input[type=checkbox]");
    expect(again[0].checked).toBe(true);
    again[0].checked = false;
    again[0].dispatchEvent(new Event("change"));
    expect($("#room-get-selected").disabled).toBe(true);
    click(button($$("#room-theirs .room-item")[1], "Baixar"));
    expect($("#room-risky").hidden).toBe(false);
    click($("#room-risky-no"));
    expect($("#room-risky").hidden).toBe(true);
    click($("#room-get-all"));
    expect($("#room-risky").hidden).toBe(false);
    click($("#room-risky-yes"));
    await tick(0);
    expect(api.room_download).toHaveBeenLastCalledWith(["t1", "t2", "t3", "t4", "t5", "t6", "t7"]);
    expect($("#room-risky").hidden).toBe(true);
    click(button($$("#room-theirs .room-item")[3], "Baixar"));
    await tick(0);
    expect(api.room_download).toHaveBeenLastCalledWith(["t4"]);
  });

  test("seleção some quando o item sai da sala", async () => {
    await setup([hostState(), hostState(), hostState({ theirs: hostState().theirs.slice(1) })]);
    await openModal();
    const box = $$("#room-theirs input[type=checkbox]")[0];
    box.checked = true;
    box.dispatchEvent(new Event("change"));
    expect($("#room-get-selected").disabled).toBe(false);
    await tick(2000);
    expect($("#room-get-selected").disabled).toBe(true);
  });

  test("entrar numa sala e mensagens de erro", async () => {
    const { api } = await setup(
      { role: null, phase: "idle", name: "" },
      {
        room_join: async () => ({ role: null, phase: "idle", notice: "Cole o link" }),
        room_add: async () => hostState({ notice: undefined }),
      },
    );
    await openModal();
    $("#room-link").value = " https://x.trycloudflare.com ";
    const code = $("#room-code");
    code.value = "ab";
    code.dispatchEvent(new Event("input"));
    expect(code.value).toBe("AB");
    code.value = "ab-c12 3x9";
    code.dispatchEvent(new Event("input"));
    expect(code.value).toBe("ABC 123");
    $("#room-name").value = "Bia";
    $("#room-join-form").dispatchEvent(new Event("submit", { cancelable: true }));
    await tick(0);
    expect(api.room_join).toHaveBeenCalledWith("https://x.trycloudflare.com", "ABC 123", "Bia");
    expect($("#room-msg").textContent).toBe("Cole o link");
    expect($("#room-notice").textContent).toBe("");
    click($("#room-add-files"));
    click($("#room-add-folder"));
    await tick(0);
    expect(api.room_add.mock.calls).toEqual([["files"], ["folder"]]);
    expect($("#room-msg").textContent).toBe("");
  });

  test("cancelar, fechar, copiar e WhatsApp", async () => {
    let share = { ok: true, app: "desktop" };
    const writeText = vi.fn(async () => {});
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    const { api } = await setup(hostState(), {
      room_close: async () => ({ role: null, phase: "idle", name: "" }),
      room_share_whatsapp: async () => share,
    });
    await openModal();
    const copy = $("#room-copy");
    click(copy);
    await tick(0);
    expect(writeText).toHaveBeenCalledWith("https://sala.trycloudflare.com\nCódigo: ABC 123");
    expect(copy.textContent).toBe("Copiado!");
    await tick(1500);
    expect(copy.textContent).toBe("Copiar");
    const wa = $("#room-whatsapp");
    click(wa);
    await tick(0);
    expect(wa.textContent.trim()).toBe("Abrindo…");
    await tick(2500);
    expect(wa.textContent.trim()).toBe("WhatsApp");
    share = { ok: true, app: "web" };
    click(wa);
    await tick(0);
    expect(wa.textContent.trim()).toBe("Abrindo no navegador…");
    await tick(2500);
    share = { ok: false };
    click(wa);
    await tick(0);
    expect(wa.textContent.trim()).toBe("WhatsApp");
    click($("#room-cancel"));
    click($("#room-close"));
    await tick(0);
    expect(api.room_close).toHaveBeenCalledTimes(2);
  });

  test("fecha pelo fundo, pelo Esc e avisa mudanças", async () => {
    const { api } = await setup({ role: null, phase: "idle", name: "" });
    const btn = $("#room-btn");
    btn.focus();
    await openModal();
    click($("#room-modal .modal-backdrop"));
    expect($("#room-modal").classList.contains("open")).toBe(false);
    expect(document.activeElement).toBe(btn);
    await tick(3000);
    const calls = api.room_status.mock.calls.length;
    await openModal();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "x", bubbles: true }));
    expect($("#room-modal").classList.contains("open")).toBe(true);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    expect($("#room-modal").classList.contains("open")).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    await window.app.roomChanged();
    expect(api.room_status.mock.calls.length).toBe(calls + 2);
  });
});
