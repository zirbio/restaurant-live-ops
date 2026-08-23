import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { beforeEach, describe, expect, it, vi } from "vitest";

const useMonth = vi.hoisted(() =>
  vi.fn(() => ({ data: null, loading: true, error: null, refresh: vi.fn() })),
);

vi.mock("../src/data/useDay", () => ({
  useDay: () => ({ data: null, loading: true, error: null, refresh: vi.fn() }),
}));

vi.mock("../src/data/useMonth", () => ({ useMonth }));

import { Dashboard } from "../src/App";
import type { MonthlyFeature } from "../src/lib/features";

function renderDashboard(feature: MonthlyFeature, search = ""): string {
  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: {
      location: { href: `https://example.com/${search}`, search },
      history: { pushState: vi.fn() },
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    },
  });
  return renderToStaticMarkup(createElement(Dashboard, { monthly: feature }));
}

beforeEach(() => useMonth.mockClear());

describe("navegación mensual opcional", () => {
  it("no monta el selector ni useMonth cuando la función está desactivada", () => {
    const html = renderDashboard({ enabled: false, configured: false }, "?v=month");

    expect(html).not.toContain(">MES<");
    expect(html).toContain("Cargando el día");
    expect(useMonth).not.toHaveBeenCalled();
  });

  it("degrada una URL mensual al día y avisa sin montar el selector ni useMonth", () => {
    const html = renderDashboard({ enabled: true, configured: false }, "?v=month");

    expect(html).toContain("Cargando el día");
    expect(html).toContain("Vista mensual no configurada");
    expect(html).not.toContain(">MES<");
    expect(useMonth).not.toHaveBeenCalled();
  });

  it("ofrece y carga el mes solo con la fuente Supabase configurada", () => {
    const html = renderDashboard({ enabled: true, configured: true }, "?v=month");

    expect(html).toContain(">MES<");
    expect(html).toContain("Cargando el mes");
    expect(useMonth).toHaveBeenCalledOnce();
  });
});
