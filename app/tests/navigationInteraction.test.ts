// @vitest-environment happy-dom

import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const useMonth = vi.hoisted(() =>
  vi.fn(() => ({ data: null, loading: true, error: null, refresh: vi.fn() })),
);

vi.mock("../src/data/useDay", () => ({
  useDay: () => ({ data: null, loading: true, error: null, refresh: vi.fn() }),
}));

vi.mock("../src/data/useMonth", () => ({ useMonth }));

import { Dashboard } from "../src/App";

let root: Root | null = null;
let container: HTMLDivElement | null = null;

function button(label: string): HTMLButtonElement {
  const found = [...document.querySelectorAll("button")].find(
    (candidate) => candidate.textContent?.trim() === label,
  );
  if (!(found instanceof HTMLButtonElement)) throw new Error(`no existe el botón ${label}`);
  return found;
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.history.replaceState({}, "", "/");
  useMonth.mockClear();
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
});

afterEach(() => {
  if (root) act(() => root?.unmount());
  container?.remove();
  root = null;
  container = null;
});

describe("interacción de la navegación mensual", () => {
  it("cambia día/mes y vuelve con el historial y popstate", async () => {
    await act(async () => {
      root?.render(createElement(Dashboard, { monthly: { enabled: true, configured: true } }));
    });

    expect(document.body.textContent).toContain("Cargando el día");
    expect(window.location.search).toBe("");

    await act(async () => button("MES").click());
    expect(document.body.textContent).toContain("Cargando el mes");
    expect(window.location.search).toBe("?v=month");
    expect(useMonth).toHaveBeenCalledOnce();

    await act(async () => button("DÍA").click());
    expect(document.body.textContent).toContain("Cargando el día");
    expect(window.location.search).toBe("");

    await act(async () => {
      window.history.back();
      await Promise.resolve();
    });
    expect(document.body.textContent).toContain("Cargando el mes");
    expect(window.location.search).toBe("?v=month");
    expect(useMonth).toHaveBeenCalledTimes(2);
  });
});
