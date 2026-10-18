import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { vi } from "vitest";

const root = resolve(import.meta.dirname, "../../src/ui");

export function loadHtml(file) {
  const html = readFileSync(resolve(root, file), "utf8");
  const doc = new DOMParser().parseFromString(html, "text/html");
  doc.querySelectorAll("script").forEach((s) => s.remove());
  document.documentElement.innerHTML = doc.documentElement.innerHTML;
}

export function mockApi(overrides = {}) {
  const defaults = {
    init: async () => ({
      theme: "dark",
      version: "1.0.0",
      engine_version: "2026.8.19",
      out_dir: "C:/Downloads",
      items: [],
    }),
    ready: async () => true,
  };
  const fns = {};
  const api = new Proxy(fns, {
    get(target, name) {
      if (typeof name !== "string") return undefined;
      if (!target[name]) target[name] = vi.fn(overrides[name] ?? defaults[name] ?? (async () => null));
      return target[name];
    },
  });
  window.pywebview = { api };
  return api;
}

export async function loadApp(overrides = {}) {
  vi.resetModules();
  loadHtml("index.html");
  const sortables = [];
  window.Sortable = { create: vi.fn((el, opts) => sortables.push({ el, opts })) };
  window.requestAnimationFrame = (cb) => setTimeout(() => cb(performance.now()), 0);
  const api = mockApi(overrides);
  await import("../../src/ui/app.js");
  return { api, sortables };
}

export async function ready() {
  window.dispatchEvent(new Event("pywebviewready"));
  await flush();
}

export async function flush(times = 5) {
  for (let i = 0; i < times; i++) await new Promise((r) => setTimeout(r, 0));
}

export async function loadMobile(responses = {}) {
  vi.resetModules();
  loadHtml("mobile/index.html");
  const calls = [];
  window.fetch = globalThis.fetch = vi.fn(async (path, options = {}) => {
    calls.push({ path, options });
    const key = String(path).split("?")[0];
    const handler = responses[key];
    const value = typeof handler === "function" ? await handler(path, options) : handler;
    const { status = 200, body = {} } = value && "status" in value ? value : { body: value ?? {} };
    return {
      ok: status >= 200 && status < 300,
      status,
      json: async () => body,
    };
  });
  await import("../../src/ui/mobile/mobile.js");
  return { calls };
}
