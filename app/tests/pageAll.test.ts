import { describe, expect, it } from "vitest";

import { PAGE_SIZE, pageAll } from "../src/lib/pageAll";

/** Una tabla falsa de `total` filas que responde por páginas. */
function tabla(total: number) {
  const filas = Array.from({ length: total }, (_, i) => ({ i }));
  const rangos: [number, number][] = [];
  return {
    rangos,
    page: (from: number, to: number) => {
      rangos.push([from, to]);
      return Promise.resolve({ data: filas.slice(from, to + 1), error: null });
    },
  };
}

describe("lectura por páginas", () => {
  it("devuelve todas las filas cuando caben en una página", async () => {
    const t = tabla(93);
    const r = await pageAll(t.page);
    expect(r.data).toHaveLength(93);
    expect(t.rangos).toEqual([[0, PAGE_SIZE - 1]]);
  });

  it("sigue pidiendo mientras las páginas vengan llenas", async () => {
    // Esto es lo que la vista mensual hace de verdad: un año de días por
    // restaurante pasa del corte de PostgREST, y una tabla truncada daría una
    // venta corta sin que nada avisara.
    const t = tabla(PAGE_SIZE * 2 + 7);
    const r = await pageAll(t.page);
    expect(r.data).toHaveLength(PAGE_SIZE * 2 + 7);
    expect(t.rangos).toHaveLength(3);
  });

  it("una página exacta obliga a pedir la siguiente", async () => {
    // Con exactamente 1000 filas no se sabe si hay más: hay que preguntar.
    const t = tabla(PAGE_SIZE);
    const r = await pageAll(t.page);
    expect(r.data).toHaveLength(PAGE_SIZE);
    expect(t.rangos).toHaveLength(2);
  });

  it("un error corta la lectura y sube tal cual", async () => {
    const r = await pageAll(() =>
      Promise.resolve({ data: null, error: { message: "sin permisos" } }),
    );
    expect(r.data).toBeNull();
    expect(r.error?.message).toBe("sin permisos");
  });
});
