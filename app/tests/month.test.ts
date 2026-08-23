import { describe, expect, it } from "vitest";

import {
  addMonths,
  daysBetween,
  daysInMonth,
  firstDayOfMonth,
  isValidMonthKey,
  lastClosedDayMadrid,
  lastDayOfMonth,
  monthAxisLabel,
  monthKeyOf,
  monthLabel,
  monthRange,
  monthShortLabel,
  monthWindowEndFor,
  priorYearDay,
  resolveMonth,
} from "../src/lib/month";

/** Un instante concreto, para no depender del reloj de quien ejecute esto. */
const en = (iso: string) => new Date(iso);

describe("claves de mes", () => {
  it("acepta solo meses del calendario", () => {
    expect(isValidMonthKey("2026-07")).toBe(true);
    expect(isValidMonthKey("2026-13")).toBe(false);
    expect(isValidMonthKey("2026-00")).toBe(false);
    expect(isValidMonthKey("2026-7")).toBe(false);
  });

  it("saca el mes de un día", () => {
    expect(monthKeyOf("2026-07-31")).toBe("2026-07");
  });

  it("conoce el primero y el último día, también en febrero bisiesto", () => {
    expect(firstDayOfMonth("2026-07")).toBe("2026-07-01");
    expect(lastDayOfMonth("2026-07")).toBe("2026-07-31");
    expect(lastDayOfMonth("2026-02")).toBe("2026-02-28");
    expect(lastDayOfMonth("2024-02")).toBe("2024-02-29");
    expect(daysInMonth("2026-06")).toBe(30);
  });

  it("suma y resta meses cruzando el año", () => {
    expect(addMonths("2026-07", 1)).toBe("2026-08");
    expect(addMonths("2026-12", 1)).toBe("2027-01");
    expect(addMonths("2026-01", -1)).toBe("2025-12");
    expect(addMonths("2026-07", -12)).toBe("2025-07");
  });

  it("enumera un rango de meses en orden", () => {
    expect(monthRange("2025-11", "2026-02")).toEqual([
      "2025-11",
      "2025-12",
      "2026-01",
      "2026-02",
    ]);
    expect(monthRange("2026-07", "2026-07")).toEqual(["2026-07"]);
  });
});

describe("nombres de mes", () => {
  it("los escribe como la cabecera del diseño", () => {
    expect(monthLabel("2026-07")).toBe("Julio 2026");
    expect(monthLabel("2026-01")).toBe("Enero 2026");
  });

  it("abrevia para el eje y para el rango de la tendencia", () => {
    expect(monthAxisLabel("2026-07")).toBe("JUL");
    expect(monthShortLabel("2025-07")).toBe("jul 25");
  });
});

describe("día de negocio y ventana del mes", () => {
  it("el último día cerrado es el anterior al día de negocio vivo", () => {
    // A las 20:00 de Madrid del 1 de agosto, el día vivo es el 1 y el último
    // cerrado el 31 de julio.
    expect(lastClosedDayMadrid(en("2026-08-01T18:00:00Z"))).toBe("2026-07-31");
  });

  it("de madrugada el día vivo sigue siendo el de ayer", () => {
    // A las 03:00 de Madrid del 1 de agosto, julio TODAVÍA está facturando: su
    // último día cerrado es el 30, no el 31.
    expect(lastClosedDayMadrid(en("2026-08-01T01:00:00Z"))).toBe("2026-07-30");
  });

  it("el mes que se abre es el del último día cerrado", () => {
    // A las 20:00 del 1 de agosto se abre julio; el día 3, agosto.
    expect(monthKeyOf(lastClosedDayMadrid(en("2026-08-01T18:00:00Z")))).toBe("2026-07");
    expect(monthKeyOf(lastClosedDayMadrid(en("2026-08-03T18:00:00Z")))).toBe("2026-08");
  });

  it("recorta la ventana del mes vivo al último día cerrado", () => {
    expect(monthWindowEndFor("2026-08", "2026-08-14")).toBe("2026-08-14");
    // Un mes ya cerrado llega hasta su último día, no hasta hoy.
    expect(monthWindowEndFor("2026-07", "2026-08-14")).toBe("2026-07-31");
  });

  it("un mes sin ningún día cerrado no tiene ventana", () => {
    // El día 1 no hay nada de agosto que enseñar: no es agosto con cero euros.
    expect(monthWindowEndFor("2026-08", "2026-07-31")).toBeNull();
  });
});

describe("emparejamiento interanual", () => {
  it("resta 364 días, que son 52 semanas exactas", () => {
    // El 31 de julio de 2026 es viernes; 364 días antes, el 1 de agosto de
    // 2025, también lo es. Con 365 caería en sábado y compararía un viernes
    // con un sábado.
    expect(priorYearDay("2026-07-31")).toBe("2025-08-01");
    expect(new Date("2026-07-31T12:00:00Z").getUTCDay()).toBe(
      new Date("2025-08-01T12:00:00Z").getUTCDay(),
    );
  });

  it("cruza el cambio de hora sin saltarse ni repetir un día", () => {
    expect(priorYearDay("2026-03-29")).toBe("2025-03-30");
  });
});

describe("rango de días", () => {
  it("incluye los dos extremos", () => {
    expect(daysBetween("2026-07-30", "2026-08-01")).toEqual([
      "2026-07-30",
      "2026-07-31",
      "2026-08-01",
    ]);
  });

  it("un rango al revés no devuelve nada", () => {
    expect(daysBetween("2026-08-01", "2026-07-30")).toEqual([]);
  });
});

describe("resolveMonth", () => {
  it("ajusta a los extremos en vez de dejar la pantalla vacía", () => {
    const limites = { latest: "2026-07", earliest: "2026-01" };
    expect(resolveMonth("2026-09", limites)).toBe("2026-07");
    expect(resolveMonth("2024-05", limites)).toBe("2026-01");
    expect(resolveMonth("2026-04", limites)).toBe("2026-04");
  });

  it("una clave ilegible cae en el mes más reciente", () => {
    expect(resolveMonth("julio", { latest: "2026-07", earliest: "2026-01" })).toBe("2026-07");
    expect(resolveMonth(null, { latest: "2026-07", earliest: "2026-01" })).toBe("2026-07");
  });

  it("el tope y el mes de apertura son cosas distintas", () => {
    // Sin parámetro se entra por julio; con `?m=2026-08` se llega a agosto,
    // que es el mes vivo y sigue estando dentro del tope.
    const limites = { latest: "2026-08", earliest: "2026-01", fallback: "2026-07" };
    expect(resolveMonth(null, limites)).toBe("2026-07");
    expect(resolveMonth("2026-08", limites)).toBe("2026-08");
    expect(resolveMonth("2026-09", limites)).toBe("2026-08");
  });
});
