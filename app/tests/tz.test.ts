import { describe, expect, it } from "vitest";

import {
  addDaysMadrid,
  businessTodayMadrid,
  freshnessLabel,
  hourMadrid,
  isValidIsoDate,
  longDateFromIso,
  longDateMadrid,
  minutesAgo,
  todayMadrid,
} from "../src/lib/tz";

describe("addDaysMadrid", () => {
  it("suma y resta un día normal", () => {
    expect(addDaysMadrid("2026-07-20", -1)).toBe("2026-07-19");
    expect(addDaysMadrid("2026-07-20", 1)).toBe("2026-07-21");
  });

  it("cruza el cambio de mes y de año", () => {
    expect(addDaysMadrid("2026-03-01", -1)).toBe("2026-02-28");
    expect(addDaysMadrid("2026-01-01", -1)).toBe("2025-12-31");
  });

  // Los dos que se rompen en silencio: restar 24 h a un Date se salta o
  // repite un día en los cambios de hora.
  it("no se salta un día en el cambio de hora de marzo", () => {
    expect(addDaysMadrid("2026-03-30", -1)).toBe("2026-03-29");
    expect(addDaysMadrid("2026-03-29", -1)).toBe("2026-03-28");
  });

  it("no repite un día en el cambio de hora de octubre", () => {
    expect(addDaysMadrid("2026-10-26", -1)).toBe("2026-10-25");
    expect(addDaysMadrid("2026-10-25", -1)).toBe("2026-10-24");
  });
});

describe("longDateFromIso", () => {
  it("escribe la fecha en español, sin puntos", () => {
    expect(longDateFromIso("2026-07-20")).toBe("lun 20 jul");
  });
});

describe("isValidIsoDate", () => {
  it("acepta una fecha real", () => {
    expect(isValidIsoDate("2026-07-20")).toBe(true);
  });

  it("rechaza basura y fechas imposibles", () => {
    expect(isValidIsoDate("ayer")).toBe(false);
    expect(isValidIsoDate("2026-13-01")).toBe(false);
    expect(isValidIsoDate("2026-02-30")).toBe(false);
    expect(isValidIsoDate("")).toBe(false);
  });
});

describe("fechas en Madrid", () => {
  it("no usa UTC para saber qué día es hoy", () => {
    // 23:30 UTC del 25 de julio ya es el día 26 en Madrid (verano, UTC+2).
    expect(todayMadrid(new Date("2026-07-25T23:30:00Z"))).toBe("2026-07-26");
  });

  it("acierta también en invierno", () => {
    // 23:30 UTC del 25 de enero sigue siendo el día 26 en Madrid (UTC+1).
    expect(todayMadrid(new Date("2026-01-25T23:30:00Z"))).toBe("2026-01-26");
  });

  it("da la hora de Madrid, no la del navegador", () => {
    expect(hourMadrid(new Date("2026-07-26T12:00:00Z"))).toBe(14); // verano
    expect(hourMadrid(new Date("2026-01-26T12:00:00Z"))).toBe(13); // invierno
  });

  it("el día de negocio vivo es ayer hasta las 06:00", () => {
    // A las 03:00 de Madrid del 28, la venta sigue entrando en el día 27:
    // la grid de la fuente de ventas corre de 06:00 a 06:00.
    expect(businessTodayMadrid(new Date("2026-07-28T01:00:00Z"))).toBe("2026-07-27");
    expect(businessTodayMadrid(new Date("2026-07-28T03:59:00Z"))).toBe("2026-07-27");
    expect(businessTodayMadrid(new Date("2026-07-28T04:00:00Z"))).toBe("2026-07-28");
    expect(businessTodayMadrid(new Date("2026-07-28T10:00:00Z"))).toBe("2026-07-28");
  });

  it("el corte de las 06:00 también acierta en invierno", () => {
    // 05:00Z de enero = 06:00 de Madrid: el día nuevo ya ha empezado.
    expect(businessTodayMadrid(new Date("2026-01-28T04:59:00Z"))).toBe("2026-01-27");
    expect(businessTodayMadrid(new Date("2026-01-28T05:00:00Z"))).toBe("2026-01-28");
  });

  it("la madrugada sigue perteneciendo al día civil", () => {
    // Las 03:00 de Madrid del día 26 son el día 26, no el 25: las ventas van
    // por día civil, como las entrega la fuente de ventas.
    expect(todayMadrid(new Date("2026-07-26T01:00:00Z"))).toBe("2026-07-26");
    expect(hourMadrid(new Date("2026-07-26T01:00:00Z"))).toBe(3);
  });

  it("calcula los minutos transcurridos", () => {
    const ahora = new Date("2026-07-26T18:00:00Z");
    expect(minutesAgo("2026-07-26T17:54:00Z", ahora)).toBe(6);
  });

  it("describe la frescura en lenguaje llano", () => {
    const ahora = new Date("2026-07-26T18:00:00Z");
    expect(freshnessLabel("2026-07-26T17:59:30Z", ahora)).toBe("hace menos de 1 min");
    expect(freshnessLabel("2026-07-26T17:54:00Z", ahora)).toBe("hace 6 min");
    expect(freshnessLabel("2026-07-26T16:00:00Z", ahora)).toBe("hace 2 h");
  });

  it("pasado un día habla en días, no en horas sueltas", () => {
    // "hace 51 h" obliga a echar cuentas para saber si el worker lleva caído
    // desde ayer o desde anteayer. Es justo el dato que hay que leer de un
    // vistazo.
    const ahora = new Date("2026-07-26T18:00:00Z");
    expect(freshnessLabel("2026-07-25T18:00:00Z", ahora)).toBe("hace 1 día");
    expect(freshnessLabel("2026-07-24T15:00:00Z", ahora)).toBe("hace 2 días");
    // Justo por debajo de las 24 h sigue hablando en horas.
    expect(freshnessLabel("2026-07-25T19:00:00Z", ahora)).toBe("hace 23 h");
  });

  it("una marca por delante del reloj del móvil no sale en negativo", () => {
    // El reloj del teléfono puede ir unos segundos por detrás del servidor, así
    // que el ciclo parece del futuro. "hace -2 min" no significa nada para un
    // gerente: es tan reciente como puede ser.
    const ahora = new Date("2026-07-26T18:00:00Z");
    expect(freshnessLabel("2026-07-26T18:02:00Z", ahora)).toBe("hace menos de 1 min");
  });

  it("sin marca de tiempo no inventa una frescura", () => {
    expect(freshnessLabel(null)).toBe("sin datos");
    expect(minutesAgo(null)).toBeNull();
  });

  it("escribe la fecha larga en español", () => {
    expect(longDateMadrid(new Date("2026-07-26T12:00:00Z"))).toBe("dom 26 jul");
  });
});
