import { describe, expect, it } from "vitest";

import {
  canGoBack,
  canGoForward,
  defaultSalesDate,
  HISTORY_START,
  resolveSalesDate,
} from "../src/lib/salesDate";

const HOY = "2026-07-27";

describe("defaultSalesDate", () => {
  // El primer argumento es el día de NEGOCIO vivo (ver businessTodayMadrid):
  // de madrugada ya es el de ayer por sí solo.

  it("de madrugada abre en el día vivo, que aún no ha cerrado", () => {
    // A la 01:00 el día de negocio 27 sigue facturando: es lo que se mira.
    expect(defaultSalesDate(HOY, 0)).toBe(HOY);
    expect(defaultSalesDate(HOY, 5)).toBe(HOY);
  });

  it("por la mañana abre en el día recién cerrado", () => {
    // A las 08:00 el día nuevo no ha vendido nada y lo que se mira es el
    // cierre completo de ayer.
    expect(defaultSalesDate(HOY, 6)).toBe("2026-07-26");
    expect(defaultSalesDate(HOY, 8)).toBe("2026-07-26");
    expect(defaultSalesDate(HOY, 11)).toBe("2026-07-26");
  });

  it("desde las 12 abre en el día en curso", () => {
    expect(defaultSalesDate(HOY, 12)).toBe(HOY);
    expect(defaultSalesDate(HOY, 15)).toBe(HOY);
    expect(defaultSalesDate(HOY, 23)).toBe(HOY);
  });

  it("cruza el mes sin salirse del calendario", () => {
    expect(defaultSalesDate("2026-08-01", 9)).toBe("2026-07-31");
    expect(defaultSalesDate("2026-03-01", 9)).toBe("2026-02-28");
  });
});

describe("resolveSalesDate", () => {
  it("sin parámetro devuelve hoy", () => {
    expect(resolveSalesDate(null, { today: HOY })).toBe(HOY);
  });

  it("sin parámetro devuelve el día por defecto que se le pase", () => {
    // Por la mañana ese día es ayer, y una recarga no debe saltar a hoy.
    expect(resolveSalesDate(null, { today: HOY, fallback: "2026-07-26" })).toBe("2026-07-26");
  });

  it("una fecha ilegible cae en el día por defecto, no en hoy", () => {
    expect(resolveSalesDate("ayer", { today: HOY, fallback: "2026-07-26" })).toBe("2026-07-26");
  });

  it("el día por defecto también respeta los extremos", () => {
    // Blindaje: un día por defecto anterior al histórico dejaría la app
    // pidiendo un día que no existe.
    expect(resolveSalesDate(null, { today: HOY, fallback: "2025-01-01" })).toBe(HISTORY_START);
    expect(resolveSalesDate(null, { today: HOY, fallback: "2026-12-31" })).toBe(HOY);
  });

  it("acepta una fecha válida dentro del rango", () => {
    expect(resolveSalesDate("2026-03-20", { today: HOY })).toBe("2026-03-20");
  });

  it("cae a hoy si la fecha es ilegible", () => {
    // Un enlace roto no debe dejar la pantalla en blanco.
    expect(resolveSalesDate("ayer", { today: HOY })).toBe(HOY);
    expect(resolveSalesDate("2026-02-30", { today: HOY })).toBe(HOY);
  });

  it("no deja ir al futuro", () => {
    expect(resolveSalesDate("2026-12-31", { today: HOY })).toBe(HOY);
  });

  it("no deja ir antes del primer día con datos", () => {
    expect(resolveSalesDate("2025-06-01", { today: HOY })).toBe(HISTORY_START);
  });

  it("respeta un primer día distinto del de por defecto", () => {
    // El límite sale de la base, no de una constante: el día que se importe
    // 2025, el selector se abre solo.
    expect(resolveSalesDate("2025-06-01", { today: HOY, earliest: "2025-01-01" })).toBe(
      "2025-06-01",
    );
  });
});

describe("canGoBack / canGoForward", () => {
  it("bloquea las flechas en los extremos", () => {
    expect(canGoBack(HISTORY_START, HISTORY_START)).toBe(false);
    expect(canGoBack("2026-01-02", HISTORY_START)).toBe(true);
    expect(canGoForward(HOY, HOY)).toBe(false);
    expect(canGoForward("2026-07-26", HOY)).toBe(true);
  });
});
