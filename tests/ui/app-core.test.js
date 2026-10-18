import { afterEach, beforeAll, beforeEach, describe, expect, test, vi } from "vitest";
import { loadApp } from "./helpers.js";

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const listeners = [];
const animations = [];

function track(target) {
  const orig = target.addEventListener;
  target.addEventListener = function (type, fn, opts) {
    listeners.push([target, type, fn, opts]);
    return orig.call(this, type, fn, opts);
  };
}

async function tick(ms = 0) {
  await vi.advanceTimersByTimeAsync(ms);
  for (let i = 0; i < 5; i++) await vi.advanceTimersByTimeAsync(1);
}

async function boot(overrides = {}) {
  const r = await loadApp({ accounts: async () => ({ sites: [], browsers: [] }), ...overrides });
  await tick();
  return r;
}

function key(el, k, extra = {}) {
  const e = new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true, ...extra });
  el.dispatchEvent(e);
  return e;
}

function mouse(el, type) {
  el.dispatchEvent(new MouseEvent(type, { bubbles: true, cancelable: true }));
}

function pasteInto(el, text) {
  const e = new Event("paste", { bubbles: true, cancelable: true });
  Object.defineProperty(e, "clipboardData", { value: { getData: () => text } });
  el.dispatchEvent(e);
  return e;
}

async function enter(text) {
  $("#link-input").value = text;
  key($("#link-input"), "Enter");
  await tick();
}

const items = () => $$("#queue-list .q-item");
const msg = () => $("#link-msg");
const YT = "https://www.youtube.com/watch?v=abcdefghijk";

beforeAll(() => {
  track(window);
  track(document);
  Element.prototype.scrollTo = vi.fn();
  Element.prototype.animate = function () {
    const a = { onfinish: null };
    animations.push(a);
    return a;
  };
});

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout", "setInterval", "clearInterval"] });
  animations.length = 0;
});

afterEach(() => {
  vi.useRealTimers();
  for (const [target, type, fn, opts] of listeners.splice(0)) target.removeEventListener(type, fn, opts);
  delete document.startViewTransition;
});

describe("formato e qualidade", () => {
  test("troca de formato atualiza botões e opções", async () => {
    await boot();
    const [mp4, mp3] = $$("#format button");
    expect($("#format").dataset.value).toBe("MP4");
    expect($("#quality").dataset.fmt).toBe("MP4");
    mp3.click();
    await tick();
    expect($("#format").dataset.value).toBe("MP3");
    expect(mp3.classList.contains("active")).toBe(true);
    expect(mp4.classList.contains("active")).toBe(false);
    expect($("#quality").dataset.fmt).toBe("MP3");
    expect($("#quality .dd-value").textContent).toBe("Máxima");
    expect($("#quality .dd-tag").textContent).toBe("Melhor");
    expect($("#apply-all b").textContent).toBe("MP3 · Máx");
  });

  test("dropdown abre, navega pelo teclado e escolhe", async () => {
    await boot();
    const root = $("#quality");
    const trigger = root.querySelector(".dd-trigger");
    const menu = root.querySelector(".dd-menu");
    trigger.click();
    expect(root.classList.contains("open")).toBe(true);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(menu.querySelectorAll(".dd-sep").length).toBe(1);
    expect(menu.querySelector(".selected .label").textContent).toBe("Máxima");
    expect(menu.querySelector(".active .label").textContent).toBe("Máxima");
    trigger.click();
    expect(root.classList.contains("open")).toBe(false);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    const down = key(root, "ArrowDown");
    expect(down.defaultPrevented).toBe(true);
    expect(root.classList.contains("open")).toBe(true);
    key(root, "ArrowDown");
    expect(menu.querySelector(".active .label").textContent).toBe("2160p (4K)");
    key(root, "ArrowUp");
    key(root, "ArrowUp");
    expect(menu.querySelector(".active .label").textContent).toBe("360p");
    const changed = vi.fn();
    root.addEventListener("change", changed);
    const ent = key(root, "Enter");
    expect(ent.defaultPrevented).toBe(true);
    expect(changed).toHaveBeenCalledTimes(1);
    expect(root.querySelector(".dd-value").textContent).toBe("360p");
    expect(root.querySelector(".dd-tag").textContent).toBe("SD");
    expect(root.classList.contains("open")).toBe(false);
    expect(document.activeElement).toBe(trigger);
    expect(key(root, "Enter").defaultPrevented).toBe(false);
    expect(key(root, " ").defaultPrevented).toBe(false);
    expect(key(root, "x").defaultPrevented).toBe(false);
    key(root, "ArrowUp");
    expect(root.classList.contains("open")).toBe(true);
    expect(menu.querySelector(".active .label").textContent).toBe("360p");
    key(root, "ArrowUp");
    key(root, " ");
    expect(root.querySelector(".dd-value").textContent).toBe("480p");
    trigger.click();
    key(root, "Escape");
    expect(root.classList.contains("open")).toBe(false);
  });

  test("dropdown responde a mouse e cliques fora", async () => {
    await boot();
    const root = $("#quality");
    const trigger = root.querySelector(".dd-trigger");
    const menu = root.querySelector(".dd-menu");
    trigger.click();
    const opts = () => menu.querySelectorAll(".dd-option");
    mouse(opts()[2].querySelector(".label"), "mousemove");
    expect(opts()[2].classList.contains("active")).toBe(true);
    expect(opts()[0].classList.contains("active")).toBe(false);
    mouse(opts()[2], "mousemove");
    expect(opts()[2].classList.contains("active")).toBe(true);
    mouse(menu.querySelector(".dd-sep"), "mousemove");
    expect(opts()[2].classList.contains("active")).toBe(true);
    menu.querySelector(".dd-sep").click();
    expect(root.classList.contains("open")).toBe(true);
    opts()[3].querySelector(".tag").click();
    expect(root.querySelector(".dd-value").textContent).toBe("1080p");
    expect(root.classList.contains("open")).toBe(false);
    trigger.click();
    mouse(trigger, "mousedown");
    expect(root.classList.contains("open")).toBe(true);
    mouse(document.body, "mousedown");
    expect(root.classList.contains("open")).toBe(false);
    trigger.click();
    key(document.body, "a");
    expect(root.classList.contains("open")).toBe(true);
    key(document.body, "Escape");
    expect(root.classList.contains("open")).toBe(false);
  });
});

describe("lista de links", () => {
  test("texto sem link sacode a caixa e mostra erro", async () => {
    await boot();
    await enter("isso não é link");
    expect($("#link-box").classList.contains("shake")).toBe(true);
    expect(msg().className).toBe("link-msg show error");
    expect(msg().textContent).toBe("Isso não parece um link");
    expect($("#link-input").value).toBe("isso não é link");
    await tick(2600);
    expect(msg().classList.contains("show")).toBe(false);
  });

  test("link do YouTube entra com miniatura e dados do peek", async () => {
    const { api } = await boot({
      peek: async () => ({ title: "Vídeo", site: "YouTube", author: "Canal", thumb: "https://x/t.jpg" }),
    });
    $("#queue").classList.add("collapsed");
    await enter(YT);
    const li = items()[0];
    expect(api.peek).toHaveBeenCalledWith(YT);
    expect($("#link-input").value).toBe("");
    expect($("#queue").classList.contains("collapsed")).toBe(false);
    expect($("#queue").classList.contains("has-links")).toBe(true);
    expect($("#queue-n").textContent).toBe("1");
    expect($("#queue-word").textContent).toBe("link");
    expect(li.classList.contains("entering")).toBe(false);
    expect(li.classList.contains("loading")).toBe(false);
    const img = li.querySelector(".q-thumb");
    expect(img.src).toBe("https://i.ytimg.com/vi/abcdefghijk/mqdefault.jpg");
    expect(img.classList.contains("pending")).toBe(true);
    img.dispatchEvent(new Event("load"));
    expect(img.classList.contains("pending")).toBe(false);
    expect(li.querySelector(".q-title").textContent).toBe("Vídeo");
    expect(li.querySelector(".q-title").title).toBe("Vídeo");
    expect(li.querySelector(".q-sub").textContent).toBe("YouTube · Canal");
    expect(li.querySelector(".q-cfg").textContent).toBe("MP4 · Máx");
    expect(li.dataset.fmt).toBe("MP4");
    expect(li.dataset.quality).toBe("Máxima");
    expect($("#queue-list").scrollTo).toHaveBeenCalled();
    expect($$("#queue-stack img").length).toBe(1);
    expect($("#queue-stack").style.width).toBe("0px");
  });

  test("link de outro site usa a miniatura do peek e trata erro de imagem", async () => {
    await boot({ peek: async () => ({ site: "Vimeo", thumb: "https://x/t.jpg" }) });
    await enter("https://vimeo.com/123");
    const li = items()[0];
    const img = li.querySelector(".q-thumb");
    expect(img.src).toBe("https://x/t.jpg");
    expect(img.classList.contains("pending")).toBe(true);
    expect(li.querySelector(".q-title").textContent).toBe("https://vimeo.com/123");
    expect(li.querySelector(".q-sub").textContent).toBe("Vimeo");
    expect($$("#queue-stack img").length).toBe(1);
    img.dispatchEvent(new Event("error"));
    expect(img.hasAttribute("src")).toBe(false);
    expect(img.classList.contains("pending")).toBe(false);
    expect($$("#queue-stack img").length).toBe(0);
  });

  test("peek vazio mantém o endereço como título", async () => {
    await boot();
    await enter("https://www.youtube.com/feed/library");
    const li = items()[0];
    expect(li.querySelector(".q-thumb").hasAttribute("src")).toBe(false);
    expect(li.querySelector(".q-title").textContent).toBe("https://www.youtube.com/feed/library");
    expect(li.querySelector(".q-sub").textContent).toBe("youtube.com/feed/library");
  });

  test("peek com erro marca o item e oferece conectar conta", async () => {
    let mode = "login";
    const { api } = await boot({
      peek: async () =>
        mode === "login"
          ? { error: "Precisa de login", site: "Instagram", login_site: "instagram" }
          : mode === "plain"
            ? { error: "Privado", site: "TikTok" }
            : { title: "Agora vai" },
      accounts: async () => ({ sites: [{ key: "instagram", name: "Instagram" }], browsers: [] }),
    });
    await enter("https://www.instagram.com/p/abc/");
    const li = items()[0];
    expect(li.classList.contains("warn")).toBe(true);
    expect(li.querySelector(".q-title").textContent).toBe("Link do Instagram");
    expect(li.querySelector(".q-sub").textContent).toBe("Precisa de login");
    expect(li.querySelector(".q-sub").title).toBe("Precisa de login");
    expect(li.dataset.loginSite).toBe("instagram");
    const btn = li.querySelector(".q-login");
    expect(btn.nextElementSibling.classList.contains("q-remove")).toBe(true);
    btn.click();
    await tick();
    expect(api.accounts).toHaveBeenCalled();
    expect($("#accounts-modal").classList.contains("open")).toBe(true);
    mode = "ok";
    window.app.accountsChanged({
      accounts: { sites: [{ key: "instagram", name: "Instagram" }], browsers: [] },
      connected: "instagram",
    });
    expect(li.querySelector(".q-login")).toBe(null);
    expect(li.classList.contains("loading")).toBe(true);
    await tick();
    expect(li.classList.contains("warn")).toBe(false);
    expect(li.querySelector(".q-title").textContent).toBe("Agora vai");
    mode = "plain";
    await enter("https://www.tiktok.com/@a/video/1");
    const li2 = items()[1];
    expect(li2.dataset.loginSite).toBe("");
    expect(li2.querySelector(".q-login")).toBe(null);
  });

  test("duplicados piscam e mostram aviso", async () => {
    await boot();
    await enter(YT);
    await enter("https://youtu.be/abcdefghijk");
    expect(items().length).toBe(1);
    expect(items()[0].classList.contains("flash")).toBe(true);
    expect(msg().className).toBe("link-msg show info");
    expect(msg().textContent).toBe("Esse link já está na lista");
    await enter("https://youtu.be/abcdefghijk https://www.youtube.com/shorts/abcdefghijk");
    expect(msg().textContent).toBe("Esses links já estão na lista");
    await enter("https://youtu.be/abcdefghijk, https://youtube.com/live/zzzzzzzzzzz.");
    expect(items().length).toBe(2);
    expect(msg().textContent).toBe("1 adicionado(s) · 1 já estava(m) na lista");
    expect($("#queue-word").textContent).toBe("links");
    expect(items()[1].querySelector(".q-sub").textContent).toBe("youtube.com/live/zzzzzzzzzzz");
  });

  test("chave de vídeo considera query só quando faz sentido", async () => {
    await boot();
    await enter("https://site.com/?a=1 https://site.com/?a=2");
    expect(items().length).toBe(2);
    await enter("https://www.facebook.com/watch?v=1 https://m.facebook.com/watch?v=2");
    expect(items().length).toBe(4);
    await enter("https://site.com/x/?a=1 https://site.com/x?b=2");
    expect(items().length).toBe(5);
    await enter("http://[bad");
    await enter("http://[bad");
    expect(items().length).toBe(6);
    expect(msg().textContent).toBe("Esse link já está na lista");
  });

  test("remover item tira da lista com animação", async () => {
    await boot();
    await enter(YT);
    const li = items()[0];
    li.querySelector(".q-remove").click();
    expect(li.classList.contains("leaving")).toBe(true);
    expect($("#queue-n").textContent).toBe("0");
    expect($("#queue").classList.contains("has-links")).toBe(false);
    li.querySelector(".q-remove").click();
    await tick(300);
    expect(li.isConnected).toBe(false);
  });

  test("recolher a fila mostra a pilha de miniaturas", async () => {
    await boot();
    await enter("https://vimeo.com/1");
    $("#queue-toggle").click();
    expect($("#queue").classList.contains("collapsed")).toBe(true);
    expect($("#queue-toggle").getAttribute("aria-expanded")).toBe("false");
    expect($("#queue-stack").style.width).toBe("0px");
    $("#queue-toggle").click();
    await enter("https://youtu.be/aaaaaaaaaaa https://youtu.be/bbbbbbbbbbb");
    $("#queue-toggle").click();
    expect($("#queue-stack").style.width).toBe("47px");
    $("#queue-toggle").click();
    expect($("#queue-toggle").getAttribute("aria-expanded")).toBe("true");
    expect($("#queue-stack").style.width).toBe("0px");
  });
});

describe("área de transferência", () => {
  const focus = async () => {
    window.dispatchEvent(new Event("focus"));
    await tick();
  };

  test("ignora quando já há texto ou a leitura falha", async () => {
    let paste = async () => {
      throw new Error("x");
    };
    const { api } = await boot({ paste: () => paste() });
    $("#link-input").value = "algo";
    await focus();
    expect(api.paste).not.toHaveBeenCalled();
    $("#link-input").value = "";
    await focus();
    expect(api.paste).toHaveBeenCalledTimes(1);
    paste = async () => null;
    await focus();
    expect(api.check_url).not.toHaveBeenCalled();
    paste = async () => {
      $("#link-input").value = "digitado";
      return YT;
    };
    await focus();
    expect(api.check_url).not.toHaveBeenCalled();
  });

  test("sugere link válido e não repete links vistos", async () => {
    let paste = async () => YT;
    let check = async () => false;
    const { api } = await boot({ paste: () => paste(), check_url: (u) => check(u) });
    await focus();
    expect(api.check_url).toHaveBeenCalledWith(YT);
    expect($("#link-input").value).toBe("");
    check = async () => {
      $("#link-input").value = "digitado";
      return true;
    };
    await focus();
    expect($("#link-input").value).toBe("digitado");
    expect($("#link-box").classList.contains("suggested")).toBe(false);
    $("#link-input").value = "";
    check = async () => true;
    await focus();
    expect($("#link-input").value).toBe(YT);
    expect($("#link-box").classList.contains("suggested")).toBe(true);
    $("#link-input").value = "";
    api.check_url.mockClear();
    await focus();
    expect(api.check_url).not.toHaveBeenCalled();
    $("#link-input").dispatchEvent(new Event("input"));
    expect($("#link-box").classList.contains("suggested")).toBe(false);
  });

  test("colar no campo adiciona links e respeita sugestão", async () => {
    await boot();
    const input = $("#link-input");
    expect(pasteInto(input, "sem link").defaultPrevented).toBe(false);
    input.value = "https://vimeo.com/1";
    expect(pasteInto(input, "https://vimeo.com/2").defaultPrevented).toBe(true);
    expect(items().length).toBe(2);
    expect(input.value).toBe("");
    input.value = "https://vimeo.com/3";
    $("#link-box").classList.add("suggested");
    pasteInto(input, "https://vimeo.com/4");
    expect(items().length).toBe(3);
    expect($("#link-box").classList.contains("suggested")).toBe(false);
    expect(items()[2].querySelector(".q-sub").textContent).toBe("vimeo.com/4");
  });

  test("botão colar trata vazio, texto comum e links", async () => {
    let text = "   ";
    await boot({ paste: async () => text });
    $("#paste").click();
    await tick();
    expect(msg().textContent).toBe("A área de transferência está vazia");
    text = "olá";
    $("#paste").click();
    await tick();
    expect(msg().textContent).toBe("O que está copiado não é um link");
    expect($("#link-box").classList.contains("shake")).toBe(true);
    text = YT;
    $("#paste").click();
    await tick();
    expect(items().length).toBe(1);
    expect(document.activeElement).toBe($("#link-input"));
  });
});

describe("teclado e botões", () => {
  test("Enter adiciona, outras teclas não", async () => {
    await boot();
    const input = $("#link-input");
    input.value = YT;
    expect(key(input, "a").defaultPrevented).toBe(false);
    expect(items().length).toBe(0);
    expect(key(document.body, "Enter").defaultPrevented).toBe(false);
    expect(key(input, "Enter").defaultPrevented).toBe(true);
    expect(items().length).toBe(1);
  });

  test("Ctrl+Enter inicia o download com a configuração de cada link", async () => {
    const { api } = await boot({ add_items: async () => true });
    $("#link-input").value = YT;
    const e = key($("#link-input"), "Enter", { ctrlKey: true });
    expect(e.defaultPrevented).toBe(true);
    await tick();
    expect(api.add_items).toHaveBeenCalledWith([{ url: YT, fmt: "MP4", quality: "Máxima" }]);
    expect($("#queue-n").textContent).toBe("0");
  });

  test("baixar sem links avisa e falha mantém a lista", async () => {
    const { api } = await boot({ add_items: async () => false });
    $("#download").click();
    await tick();
    expect(msg().textContent).toBe("Adicione pelo menos um link");
    expect(api.add_items).not.toHaveBeenCalled();
    await enter(YT);
    $("#download").click();
    await tick();
    expect(api.add_items).toHaveBeenCalled();
    expect($("#queue-n").textContent).toBe("1");
  });

  test("botão adicionar trata vazio e conteúdo", async () => {
    await boot();
    $("#add").click();
    expect(msg().textContent).toBe("Cole um link primeiro");
    $("#link-input").value = "abc";
    $("#add").click();
    expect($("#link-input").value).toBe("abc");
    $("#link-input").value = YT;
    $("#add").click();
    expect(items().length).toBe(1);
    expect(document.activeElement).toBe($("#link-input"));
  });

  test("limpar lista remove tudo", async () => {
    await boot();
    await enter("https://vimeo.com/1 https://vimeo.com/2");
    $("#link-input").value = "x";
    $("#link-box").classList.add("suggested");
    $("#clear").click();
    expect($("#queue-n").textContent).toBe("0");
    expect($("#link-input").value).toBe("");
    expect($("#link-box").classList.contains("suggested")).toBe(false);
  });

  test("escolher pasta atualiza o caminho só quando há resposta", async () => {
    let path = "D:/Vídeos";
    await boot({ choose_folder: async () => path });
    $("#folder").click();
    await tick();
    expect($("#folder-path").textContent).toBe("D:/Vídeos");
    path = null;
    $("#folder").click();
    await tick();
    expect($("#folder-path").textContent).toBe("D:/Vídeos");
  });

  test("tema alterna com e sem transição de visualização", async () => {
    const { api } = await boot();
    const root = document.documentElement;
    root.dataset.theme = "dark";
    $("#theme").click();
    expect(root.dataset.theme).toBe("light");
    expect(api.set_theme).toHaveBeenCalledWith("light");
    const animate = vi.fn();
    root.animate = animate;
    document.startViewTransition = vi.fn((cb) => {
      cb();
      return { ready: Promise.resolve() };
    });
    $("#theme").click();
    await tick();
    expect(root.dataset.theme).toBe("dark");
    expect(api.set_theme).toHaveBeenLastCalledWith("dark");
    expect(animate).toHaveBeenCalledWith(
      expect.objectContaining({ clipPath: expect.any(Array) }),
      expect.objectContaining({ duration: 550, pseudoElement: "::view-transition-new(root)" }),
    );
    delete root.animate;
  });
});

describe("cards de download", () => {
  const status = (it) => {
    window.app.update({ id: "s", fmt: "MP4", url: "u", ...it });
    return $('[data-id="s"] .status').textContent;
  };

  test("textos de status cobrem todos os estados", async () => {
    await boot();
    expect(status({ status: "queued", quality: "720p" })).toBe("Na fila · 720p");
    expect(status({ status: "setup" })).toBe("Preparando o app (só na 1ª vez)…");
    expect(status({ status: "fetching" })).toBe("Obtendo informações…");
    expect(status({ status: "downloading" })).toBe("Baixando · 0%");
    expect(status({ status: "downloading", progress: 0.456, speed: 2097152, eta: 125 })).toBe(
      "Baixando · 45% · 2.0 MB/s · 2:05 restante",
    );
    expect(status({ status: "processing", fmt: "MP3" })).toBe("Convertendo para MP3…");
    expect(status({ status: "processing" })).toBe("Finalizando…");
    expect(status({ status: "paused", progress: 0.5 })).toBe("Pausado · 50%");
    expect(status({ status: "done", quality: "1080p" })).toBe("Salvo! · 1080p");
    expect(status({ status: "error", error: "Falhou feio" })).toBe("Falhou feio");
    expect($('[data-id="s"] .status').title).toBe("Falhou feio");
    expect(status({ status: "error" })).toBe("Não deu certo");
    expect($('[data-id="s"] .status').title).toBe("");
    expect(status({ status: "outro" })).toBe("");
    expect($$("#grid .card").length).toBe(1);
  });

  test("atualização preenche card com tags, overlay e progresso", async () => {
    await boot();
    window.app.update({
      id: "a",
      fmt: "MP3",
      status: "processing",
      title: "Música",
      url: "https://x",
      duration: 3725.4,
      site: "Instagram",
      folder: `C:/a/<b>&"'`,
      source: "claude",
      thumb: "https://t/1.jpg",
      progress: 0.5,
    });
    const el = $('[data-id="a"]');
    expect(el.className).toBe("card processing busy");
    expect(el.dataset.fmt).toBe("MP3");
    expect(el.querySelector(".badge").textContent).toBe("MP3");
    expect(el.querySelector(".title").textContent).toBe("Música");
    expect(el.querySelector(".title").title).toBe("Música");
    expect(el.querySelector(".dur").textContent).toBe("1:02:05");
    expect(el.querySelector(".site").textContent).toBe("Instagram");
    const folder = el.querySelector(".tag-folder");
    expect(folder.title).toBe(`Salvo em C:/a/<b>&"'`);
    expect(el.querySelector(".card-tags").innerHTML).toContain("&lt;b&gt;&amp;\"'");
    expect(el.querySelector(".tag-claude")).not.toBe(null);
    expect(el.querySelector(".overlay span").textContent).toBe("Falhou · clique em ↻");
    expect(el.querySelector(".card-login").hidden).toBe(true);
    expect(el.querySelector("img").src).toBe("https://t/1.jpg");
    expect(Number(el.querySelector(".bar").style.strokeDashoffset)).toBeCloseTo(Math.PI * 21);
    el.querySelector("img").src = "https://t/outra.jpg";
    window.app.update({
      id: "a",
      fmt: "MP3",
      status: "paused",
      url: "https://x",
      site: "YouTube",
      source: "phone",
      thumb: "https://t/1.jpg",
      duration: 65,
    });
    expect(el.className).toBe("card paused");
    expect(el.querySelector("img").src).toBe("https://t/outra.jpg");
    expect(el.querySelector(".title").textContent).toBe("https://x");
    expect(el.querySelector(".title").title).toBe("https://x");
    expect(el.querySelector(".dur").textContent).toBe("1:05");
    expect(el.querySelector(".site").textContent).toBe("");
    expect(el.querySelector(".tag-phone")).not.toBe(null);
    expect(el.querySelector(".tag-folder")).toBe(null);
    expect(el.querySelector(".overlay span").textContent).toBe("❚❚  Pausado");
    expect(el.querySelector(".bar").style.strokeDashoffset).toBe(String(2 * Math.PI * 21));
    window.app.update({
      id: "a",
      fmt: "MP3",
      status: "error",
      url: "u",
      error_kind: "login",
      login_site: "x",
      thumb: "https://t/2.jpg",
    });
    expect(el.querySelector(".overlay span").textContent).toBe("🔒  Precisa de login");
    expect(el.querySelector(".card-login").hidden).toBe(false);
    expect(el.querySelector(".card-login").dataset.site).toBe("x");
    expect(el.querySelector("img").src).toBe("https://t/2.jpg");
    expect(el.querySelector(".dur").textContent).toBe("");
    window.app.update({ id: "a", fmt: "MP3", status: "error", url: "u", error_kind: "noaccess" });
    expect(el.querySelector(".overlay span").textContent).toBe("🔒  Precisa de login");
    expect(el.querySelector(".card-login").hidden).toBe(true);
    expect(el.querySelector(".card-login").dataset.site).toBe("");
    window.app.update({ id: "a", fmt: "MP3", status: "done", url: "u" });
    expect(el.querySelector(".bar").style.strokeDashoffset).toBe("0");
  });

  test("posição na fila e contador acompanham os cards", async () => {
    await boot();
    window.app.update({ id: "1", fmt: "MP4", status: "downloading", url: "u" });
    window.app.update({ id: "2", fmt: "MP4", status: "done", url: "u" });
    window.app.update({ id: "3", fmt: "MP4", status: "queued", url: "u" });
    expect($$("#grid .pos").map((p) => p.textContent)).toEqual(["#1", "", "#2"]);
    expect($("#count").textContent).toBe("3");
    expect($(".downloads").classList.contains("has-items")).toBe(true);
  });

  test("botões do card removem, abrem, tentam de novo e conectam", async () => {
    const { api } = await boot({ accounts: async () => ({ sites: [], browsers: [] }) });
    window.app.update({ id: "a", fmt: "MP4", status: "done", url: "u" });
    window.app.update({ id: "b", fmt: "MP4", status: "error", url: "u", login_site: "tiktok" });
    const a = $('[data-id="a"]');
    const b = $('[data-id="b"]');
    a.querySelector("img").dispatchEvent(new Event("load"));
    expect(a.querySelector("img").classList.contains("loaded")).toBe(true);
    a.querySelector(".action").click();
    expect(api.open_item).toHaveBeenCalledWith("a");
    b.querySelector(".action").click();
    expect(api.retry).toHaveBeenCalledWith("b");
    b.querySelector(".card-login").click();
    await tick();
    expect(api.accounts).toHaveBeenCalled();
    expect($("#accounts-modal").classList.contains("open")).toBe(true);
    a.querySelector(".remove").click();
    expect(api.remove).toHaveBeenCalledWith("a");
    expect(animations.length).toBe(1);
    animations[0].onfinish();
    expect(a.isConnected).toBe(false);
    expect($("#count").textContent).toBe("1");
    a.querySelector(".remove").click();
    expect(animations.length).toBe(1);
    b.querySelector(".remove").click();
    animations[1].onfinish();
    expect($("#count").textContent).toBe("");
    expect($(".downloads").classList.contains("has-items")).toBe(false);
  });

  test("limpar concluídos remove os cards devolvidos", async () => {
    const { api } = await boot({ clear_done: async () => ["a", "zz"] });
    window.app.update({ id: "a", fmt: "MP4", status: "done", url: "u" });
    $("#clear-done").click();
    await tick();
    expect(api.clear_done).toHaveBeenCalled();
    expect(animations.length).toBe(1);
  });

  test("arrastar reordena e avisa a API", async () => {
    const { api, sortables } = await boot();
    window.app.update({ id: "a", fmt: "MP4", status: "queued", url: "u" });
    window.app.update({ id: "b", fmt: "MP4", status: "queued", url: "u" });
    const { el, opts } = sortables[0];
    expect(el).toBe($("#grid"));
    expect(opts).toMatchObject({
      animation: 220,
      delay: 150,
      forceFallback: true,
      filter: ".remove, .action, .card-login",
    });
    el.prepend($('[data-id="b"]'));
    opts.onEnd();
    expect(api.reorder).toHaveBeenCalledWith(["b", "a"]);
    expect($('[data-id="b"] .pos').textContent).toBe("#1");
  });
});

describe("inicialização", () => {
  test("pywebviewready aplica estado inicial", async () => {
    const { api } = await boot({
      init: async () => ({
        theme: "light",
        version: "2.3.4",
        engine_version: "2026.1.1",
        out_dir: "E:/Saída",
        items: [{ id: "x", fmt: "MP4", status: "queued", url: "u", quality: "720p" }],
      }),
      paste: async () => "",
    });
    window.dispatchEvent(new Event("pywebviewready"));
    await tick();
    expect(document.documentElement.dataset.theme).toBe("light");
    expect($("#version").textContent).toBe("v2.3.4");
    expect($("#st-version").textContent).toBe("Salvaí 2.3.4 · motor 2026.1.1");
    expect(api.ready).toHaveBeenCalled();
    expect($("#folder-path").textContent).toBe("E:/Saída");
    expect($$("#grid .card").length).toBe(1);
    expect($("#count").textContent).toBe("1");
    expect(document.activeElement).toBe($("#link-input"));
    expect(api.paste).toHaveBeenCalled();
    expect(document.body.classList.contains("ready")).toBe(false);
    await tick(30);
    expect(document.body.classList.contains("ready")).toBe(true);
  });
});

describe("configuração por link", () => {
  test("aplicar a todos aparece quando formato ou qualidade diferem", async () => {
    await boot();
    expect($("#apply-all").classList.contains("show")).toBe(false);
    await enter(YT);
    expect($("#apply-all").classList.contains("show")).toBe(false);
    $$("#format button")[1].click();
    await tick();
    expect($("#apply-all").classList.contains("show")).toBe(true);
    $("#apply-all").click();
    const li = items()[0];
    expect(li.dataset.fmt).toBe("MP3");
    expect(li.querySelector(".q-cfg").textContent).toBe("MP3 · Máx");
    expect(li.querySelector(".q-cfg").classList.contains("pop")).toBe(true);
    expect($("#apply-all").classList.contains("show")).toBe(false);
    expect(msg().textContent).toBe("Todos os links agora vão em MP3 · Máxima");
    $("#quality .dd-trigger").click();
    $$("#quality .dd-option")[1].click();
    expect($("#apply-all").classList.contains("show")).toBe(true);
    expect($("#apply-all b").textContent).toBe("MP3 · 320k");
    expect($("#apply-all").dataset.fmt).toBe("MP3");
    $$("#format button")[0].click();
    $("#quality .dd-trigger").click();
    $$("#quality .dd-option")[1].click();
    expect($("#apply-all b").textContent).toBe("MP4 · 4K");
    $("#quality .dd-trigger").click();
    $$("#quality .dd-option")[3].click();
    expect($("#apply-all b").textContent).toBe("MP4 · 1080p");
  });

  test("sem botão aplicar a todos nada quebra", async () => {
    await boot();
    $("#apply-all").remove();
    $$("#format button")[1].click();
    await tick();
    expect($("#format").dataset.value).toBe("MP3");
  });

  test("popover abre, troca formato e qualidade do link", async () => {
    await boot();
    await enter(YT);
    const li = items()[0];
    const cfg = li.querySelector(".q-cfg");
    const pop = $("#cfg-pop");
    cfg.click();
    expect(pop.classList.contains("open")).toBe(true);
    expect(pop.dataset.fmt).toBe("MP4");
    expect(pop.querySelector(".segmented").dataset.value).toBe("MP4");
    expect(pop.querySelector('.segmented [data-value="MP4"]').classList.contains("active")).toBe(true);
    expect(pop.querySelectorAll(".cfg-list .dd-option").length).toBe(7);
    expect(pop.querySelector(".cfg-list .selected").dataset.q).toBe("Máxima");
    expect(pop.style.top).toBe("8px");
    expect(pop.style.left).toBe("8px");
    expect(pop.style.transformOrigin).toBe("top right");
    cfg.click();
    expect(pop.classList.contains("open")).toBe(false);
    cfg.click();
    pop.querySelector('.segmented [data-value="MP4"]').click();
    expect(li.dataset.fmt).toBe("MP4");
    pop.querySelector('.segmented [data-value="MP3"]').click();
    expect(li.dataset.fmt).toBe("MP3");
    expect(li.dataset.quality).toBe("Máxima");
    expect(pop.querySelectorAll(".cfg-list .dd-option").length).toBe(5);
    expect($("#apply-all").classList.contains("show")).toBe(true);
    pop.querySelector(".cfg-list").click();
    expect(pop.classList.contains("open")).toBe(true);
    pop.querySelector('.cfg-list [data-q="320 kbps"] .label').click();
    expect(li.dataset.quality).toBe("320 kbps");
    expect(cfg.textContent).toBe("MP3 · 320k");
    expect(cfg.dataset.fmt).toBe("MP3");
    expect(pop.classList.contains("open")).toBe(false);
  });

  test("popover abre para cima perto da borda inferior", async () => {
    await boot();
    await enter(YT);
    const cfg = items()[0].querySelector(".q-cfg");
    const pop = $("#cfg-pop");
    Object.defineProperty(pop, "offsetHeight", { value: 200, configurable: true });
    Object.defineProperty(pop, "offsetWidth", { value: 240, configurable: true });
    cfg.getBoundingClientRect = () => ({ top: innerHeight - 28, bottom: innerHeight - 8, right: 500 });
    cfg.click();
    expect(pop.style.top).toBe(`${innerHeight - 28 - 206}px`);
    expect(pop.style.left).toBe("260px");
    expect(pop.style.transformOrigin).toBe("bottom right");
  });

  test("popover fecha com clique fora, Esc, rolagem e redimensionamento", async () => {
    await boot();
    await enter(YT);
    const cfg = items()[0].querySelector(".q-cfg");
    const pop = $("#cfg-pop");
    const isOpen = () => pop.classList.contains("open");
    mouse(document.body, "mousedown");
    cfg.click();
    mouse(pop.querySelector(".cfg-list"), "mousedown");
    expect(isOpen()).toBe(true);
    mouse(cfg, "mousedown");
    expect(isOpen()).toBe(true);
    mouse(document.body, "mousedown");
    expect(isOpen()).toBe(false);
    cfg.click();
    key(document.body, "a");
    expect(isOpen()).toBe(true);
    key(document.body, "Escape");
    expect(isOpen()).toBe(false);
    cfg.click();
    $("#queue-list").dispatchEvent(new Event("scroll"));
    expect(isOpen()).toBe(false);
    cfg.click();
    window.dispatchEvent(new Event("resize"));
    expect(isOpen()).toBe(false);
  });
});
