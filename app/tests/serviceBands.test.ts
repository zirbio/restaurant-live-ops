import { describe, expect, it } from "vitest";

import {
  cumulativeServiceTrend,
  objectivesByMonth,
  officialTimesByMonth,
  officialTrend,
  serviceBands,
  trendSegments,
  visibleTrendMonths,
} from "../src/lib/serviceBands";
import type { TrendPoint } from "../src/lib/monthly";
import type { Objectives } from "../src/lib/types";

function punto(month: string, kvs: number | null, r2p: number | null, oepe: number | null): TrendPoint {
  return { month, kvs, r2p, oepe };
}

function objetivo(kvs: number, r2p: number, oepe: number | null): Objectives {
  return { restaurant_id: "R001", kvs, r2p, oepe };
}

describe("serviceBands", () => {
  it("da una franja por métrica, en orden KVS, R2P, OEPE", () => {
    const bandas = serviceBands([punto("2026-07", 107, 127, 165)], new Map());
    expect(bandas.map((b) => b.key)).toEqual(["kvs", "r2p", "oepe"]);
  });

  it("omite la métrica que no tiene ni un solo valor", () => {
    // Sin servicio en vehículo, OEPE no existe y su franja tampoco.
    const bandas = serviceBands(
      [punto("2026-06", 80, 120, null), punto("2026-07", 85, 126, null)],
      new Map(),
    );
    expect(bandas.map((b) => b.key)).toEqual(["kvs", "r2p"]);
  });

  it("empareja cada mes con el objetivo de ESE mes, no con el último", () => {
    // Los objetivos bajan a lo largo del año: 81 en julio y 75 en octubre.
    const bandas = serviceBands(
      [punto("2026-07", 78, 120, 160), punto("2026-10", 78, 120, 160)],
      new Map([
        ["2026-07", objetivo(81, 139, 162)],
        ["2026-10", objetivo(75, 130, 155)],
      ]),
    );
    const kvs = bandas.find((b) => b.key === "kvs");
    expect(kvs?.values.map((v) => v.objective)).toEqual([81, 75]);
    // El mismo 78" cumple en julio y falla en octubre.
    expect(kvs?.values.map((v) => v.light)).toEqual(["ok", "warn"]);
  });

  it("deja sin luz el mes cuyo objetivo no existe", () => {
    // De 2025 no hay objetivos guardados: ahí no se juzga nada.
    const bandas = serviceBands(
      [punto("2025-11", 94, 146, 184), punto("2026-07", 107, 127, 165)],
      new Map([["2026-07", objetivo(81, 139, 162)]]),
    );
    const kvs = bandas.find((b) => b.key === "kvs");
    expect(kvs?.values.map((v) => v.objective)).toEqual([null, 81]);
    expect(kvs?.values.map((v) => v.light)).toEqual(["none", "bad"]);
  });

  it("redondea el valor antes de juzgarlo, para que la cifra y su color digan lo mismo", () => {
    // Una media de 81,3 se imprime "81" y con el valor crudo salía en ámbar
    // bajo una cabecera que dice «obj ≤ 81"». Lo que se ve es lo que se juzga.
    const bandas = serviceBands(
      [punto("2026-07", 81.3, 120, 160)],
      new Map([["2026-07", objetivo(81, 139, 162)]]),
    );
    const kvs = bandas.find((b) => b.key === "kvs");
    expect(kvs?.values[0]?.value).toBe(81);
    expect(kvs?.values[0]?.light).toBe("ok");
  });

  it("mete el objetivo dentro de la escala aunque quede por debajo de los valores", () => {
    // Sin esto, la línea de objetivo se saldría de su franja y no se vería.
    const bandas = serviceBands(
      [punto("2026-07", 130, 120, 160), punto("2026-08", 134, 120, 160)],
      new Map([["2026-07", objetivo(120, 139, 162)]]),
    );
    const kvs = bandas.find((b) => b.key === "kvs");
    expect(kvs!.min).toBeLessThanOrEqual(120);
    expect(kvs!.objectiveOffScale).toBe(false);
  });

  it("mete el objetivo dentro de la escala aunque quede por encima de los valores", () => {
    // Si solo se cuidara el lado inferior, un objetivo por encima de la serie
    // saldría por el techo de la franja.
    const bandas = serviceBands(
      [punto("2026-07", 100, 120, 160), punto("2026-08", 100, 135, 160)],
      new Map([["2026-07", objetivo(90, 150, 162)]]),
    );
    const r2p = bandas.find((b) => b.key === "r2p");
    expect(r2p!.max).toBeGreaterThanOrEqual(150);
    expect(r2p!.objectiveOffScale).toBe(false);
  });

  it("no deja que un objetivo lejano aplaste la serie: lo deja fuera de escala", () => {
    // Estirar la escala hasta un objetivo muy lejos devuelve el defecto que
    // este gráfico venía a corregir. Valores 120–135 (recorrido 15) con un
    // objetivo en 200 pedirían un recorrido de 80: la serie quedaría en una
    // quinta parte de su franja.
    const bandas = serviceBands(
      [punto("2026-07", 120, 120, 160), punto("2026-08", 135, 120, 160)],
      new Map([
        ["2026-07", objetivo(200, 139, 162)],
        ["2026-08", objetivo(200, 139, 162)],
      ]),
    );
    const kvs = bandas.find((b) => b.key === "kvs");
    expect(kvs!.objectiveOffScale).toBe(true);
    expect(kvs!.max).toBeLessThan(200);
    // El juicio de cada mes NO se pierde: sigue saliendo del objetivo.
    expect(kvs?.values[0]?.light).toBe("ok");
  });

  it("reserva el aire que el dibujo le pide para la cifra", () => {
    // El hueco lo manda el componente en píxeles, que es donde se conocen el
    // tamaño de la letra y el alto de la franja.
    const bandas = serviceBands([punto("2026-07", 100, 120, 160), punto("2026-08", 140, 120, 160)], new Map(), {
      areaPx: 46,
      headroomPx: 11.5,
    });
    const kvs = bandas.find((b) => b.key === "kvs");
    const porUnidad = (kvs!.max - kvs!.min) / 46;
    expect(kvs!.max - 140).toBeCloseTo(11.5 * porUnidad, 6);
  });

  it("no degenera la escala de una serie plana", () => {
    // Trece meses clavados en 100 no pueden dar una escala de altura cero.
    const bandas = serviceBands(
      [punto("2026-06", 100, 120, 160), punto("2026-07", 100, 120, 160)],
      new Map(),
    );
    const kvs = bandas.find((b) => b.key === "kvs");
    expect(kvs!.max).toBeGreaterThan(kvs!.min);
  });
});

describe("cumulativeServiceTrend", () => {
  const dia = (
    sales_date: string,
    gc: number,
    kvs: number | null,
    r2p: number | null,
    oepe: number | null,
  ) => ({
    restaurant_id: "R001",
    sales_date,
    hourly_net_sum: null,
    gc,
    service_time_gc: gc,
    kvs,
    r2p,
    oepe,
    quality: "clean" as const,
  });

  const withSnapshots = cumulativeServiceTrend as unknown as (
    days: Parameters<typeof cumulativeServiceTrend>[0],
    axisDays: string[],
    officialSnapshots: ReadonlyMap<string, { r2p: number | null; oepe: number | null }>,
  ) => ReturnType<typeof cumulativeServiceTrend>;

  it("conserva KVS ponderado y copia R2P/OEPE oficiales sin promediarlos", () => {
    // Si R2P/OEPE volviesen a salir de los cierres, el segundo punto sería
    // 150/150 y no la fotografía oficial publicada por la fuente de ventas.
    const puntos = withSnapshots(
      [dia("2026-08-01", 100, 100, 120, 140), dia("2026-08-02", 300, 120, 180, 160)],
      ["2026-08-01", "2026-08-02"],
      new Map([
        ["2026-08-01", { r2p: 123, oepe: 169 }],
        ["2026-08-02", { r2p: 119, oepe: 166 }],
      ]),
    );

    expect(puntos).toEqual([
      { month: "2026-08-01", kvs: 100, r2p: 123, oepe: 169 },
      { month: "2026-08-02", kvs: 115, r2p: 119, oepe: 166 },
    ]);
  });

  it("ordena los días antes de acumularlos", () => {
    const puntos = cumulativeServiceTrend([
      dia("2026-08-02", 100, 120, 140, 160),
      dia("2026-08-01", 100, 100, 120, 140),
    ]);

    expect(puntos.map((p) => p.month)).toEqual(["2026-08-01", "2026-08-02"]);
    expect(puntos[1]?.kvs).toBe(110);
  });

  it("deja R2P/OEPE en raya sin fotografía aunque el cierre diario tenga cifras", () => {
    // Un cierre diario no es una fotografía oficial mensual: recuperarlo
    // cambiaría silenciosamente de método dentro de la misma curva.
    const puntos = withSnapshots(
      [dia("2026-08-01", 100, 100, 120, 140), dia("2026-08-02", 100, 110, 180, 160)],
      ["2026-08-01", "2026-08-02"],
      new Map(),
    );

    expect(puntos.map((p) => p.r2p)).toEqual([null, null]);
    expect(puntos.map((p) => p.oepe)).toEqual([null, null]);
    expect(puntos.map((p) => p.kvs)).toEqual([100, 105]);
  });

  it("corta también el KVS acumulado ante un cierre diario imposible", () => {
    const puntos = cumulativeServiceTrend([
      dia("2026-08-01", 100, 100, 120, 140),
      dia("2026-08-02", 100, 1, 130, 150),
      dia("2026-08-03", 100, 120, 140, 160),
    ]);

    expect(puntos.map((p) => p.kvs)).toEqual([100, null, null]);
  });

  it("conserva el corte de KVS pero vuelve a dibujar R2P/OEPE tras un hueco oficial", () => {
    const puntos = withSnapshots(
      [
        dia("2026-08-01", 100, 100, 120, 140),
        dia("2026-08-03", 100, 120, 180, 160),
      ],
      ["2026-08-01", "2026-08-02", "2026-08-03"],
      new Map([
        ["2026-08-01", { r2p: 123, oepe: 169 }],
        ["2026-08-03", { r2p: 119, oepe: 166 }],
      ]),
    );

    expect(puntos).toEqual([
      { month: "2026-08-01", kvs: 100, r2p: 123, oepe: 169 },
      { month: "2026-08-02", kvs: null, r2p: null, oepe: null },
      { month: "2026-08-03", kvs: null, r2p: 119, oepe: 166 },
    ]);
  });

  it("conserva un OEPE nulo oficial", () => {
    const puntos = withSnapshots(
      [dia("2026-08-01", 100, 100, 120, 140)],
      ["2026-08-01"],
      new Map([["2026-08-01", { r2p: 119, oepe: null }]]),
    );

    expect(puntos[0]).toEqual({ month: "2026-08-01", kvs: 100, r2p: 119, oepe: null });
  });
});

describe("objectivesByMonth", () => {
  it("indexa por restaurante y mes con el mes a dos cifras", () => {
    const indice = objectivesByMonth([
      { restaurant_id: "R001", year: 2026, month: 7, kvs: 81, r2p: 139, oepe: 162 },
    ]);
    expect(indice.get("R001")?.get("2026-07")?.kvs).toBe(81);
  });

  it("conserva el OEPE nulo del local sin servicio en vehículo", () => {
    // Un centinela de "no aplica" se guarda como nulo: convertirlo en cero
    // pintaría un objetivo imposible de cumplir.
    const indice = objectivesByMonth([
      { restaurant_id: "R002", year: 2026, month: 7, kvs: 70, r2p: 123, oepe: null },
    ]);
    expect(indice.get("R002")?.get("2026-07")?.oepe).toBeNull();
  });

  it("guarda TODOS los meses de un mismo restaurante", () => {
    // La consulta trae años enteros, así que cada restaurante llega con doce
    // filas o más. Quedarse con la última dejaría doce de las trece cifras en
    // gris y la escalera en un solo peldaño.
    const indice = objectivesByMonth([
      { restaurant_id: "R001", year: 2026, month: 1, kvs: 97, r2p: 156, oepe: 178 },
      { restaurant_id: "R001", year: 2026, month: 7, kvs: 81, r2p: 139, oepe: 162 },
      { restaurant_id: "R001", year: 2026, month: 12, kvs: 70, r2p: 123, oepe: 145 },
    ]);
    expect(indice.get("R001")?.size).toBe(3);
    expect(indice.get("R001")?.get("2026-01")?.kvs).toBe(97);
    expect(indice.get("R001")?.get("2026-12")?.kvs).toBe(70);
  });

  it("no mezcla dos años del mismo restaurante", () => {
    const indice = objectivesByMonth([
      { restaurant_id: "R001", year: 2025, month: 7, kvs: 110, r2p: 170, oepe: 190 },
      { restaurant_id: "R001", year: 2026, month: 7, kvs: 81, r2p: 139, oepe: 162 },
    ]);
    expect(indice.get("R001")?.get("2025-07")?.kvs).toBe(110);
    expect(indice.get("R001")?.get("2026-07")?.kvs).toBe(81);
  });

  it("no mezcla los objetivos de dos restaurantes", () => {
    const indice = objectivesByMonth([
      { restaurant_id: "R001", year: 2026, month: 7, kvs: 81, r2p: 139, oepe: 162 },
      { restaurant_id: "R003", year: 2026, month: 7, kvs: 81, r2p: 127, oepe: 145 },
    ]);
    expect(indice.get("R003")?.get("2026-07")?.r2p).toBe(127);
    expect(indice.get("R001")?.get("2026-07")?.r2p).toBe(139);
  });
});

describe("visibleTrendMonths", () => {
  const trece = ["2025-08", "2025-09", "2025-10", "2025-11"];

  it("conserva el mes vacío de en medio, para que la línea se corte ahí", () => {
    // Quitarlo del eje juntaba los dos meses vecinos y la curva los unía con
    // un trazo continuo: una evolución que nadie ha medido.
    const visibles = visibleTrendMonths(trece, new Set(["2025-08", "2025-09", "2025-11"]));
    expect(visibles).toEqual(trece);
  });

  it("recorta los meses vacíos de delante", () => {
    // El eje no empieza antes de que existan datos: sin esto, un histórico
    // corto dejaría medio gráfico en blanco.
    const visibles = visibleTrendMonths(trece, new Set(["2025-10", "2025-11"]));
    expect(visibles).toEqual(["2025-10", "2025-11"]);
  });

  it("conserva el mes vacío del final: es el que se está mirando", () => {
    const visibles = visibleTrendMonths(trece, new Set(["2025-08", "2025-09"]));
    expect(visibles).toEqual(trece);
  });

  it("devuelve una lista vacía cuando no hay ni un mes con dato", () => {
    expect(visibleTrendMonths(trece, new Set())).toEqual([]);
  });
});

describe("trendSegments", () => {
  it("parte la línea en el hueco en vez de cruzarlo", () => {
    // Unir por encima de un mes sin dato dibuja una evolución que nadie midió.
    const tramos = trendSegments([
      { month: "2026-05", value: 100, objective: null, light: "none" },
      { month: "2026-06", value: null, objective: null, light: "none" },
      { month: "2026-07", value: 120, objective: null, light: "none" },
    ]);
    expect(tramos.map((t) => t.map((p) => p.i))).toEqual([[0], [2]]);
  });

  it("mantiene juntos los meses seguidos", () => {
    const tramos = trendSegments([
      { month: "2026-05", value: 100, objective: null, light: "none" },
      { month: "2026-06", value: 110, objective: null, light: "none" },
    ]);
    expect(tramos).toHaveLength(1);
    expect(tramos[0]!.map((p) => p.value)).toEqual([100, 110]);
  });
});

describe("officialTrend", () => {
  const dia = (sales_date: string, kvs: number, r2p: number, oepe: number) => ({
    restaurant_id: "R001",
    sales_date,
    hourly_net_sum: null,
    gc: 100,
    kvs,
    r2p,
    oepe,
  });

  it("toma el R2P y el OEPE de la fuente de ventas, no la media de los días", () => {
    // La cifra publicada por la fuente prevalece sobre una reconstrucción local.
    const punto = officialTrend(
      [dia("2026-02-01", 108, 126, 165)],
      ["2026-02"],
      new Map([["2026-02", { r2p: 137, oepe: 165 }]]),
    )[0]!;
    expect(punto.r2p).toBe(137);
    expect(punto.oepe).toBe(165);
  });

  it("deriva el KVS de los días, porque la fuente de ventas no lo publica mensual", () => {
    const punto = officialTrend(
      [dia("2026-02-01", 108, 126, 165)],
      ["2026-02"],
      new Map([["2026-02", { r2p: 137, oepe: 165 }]]),
    )[0]!;
    expect(punto.kvs).toBe(108);
  });

  it("deja el hueco en el mes sin cifra publicada", () => {
    // Donde no hay dato publicado no se rellena con un cálculo local: se corta
    // la línea.
    const punto = officialTrend([dia("2025-03-01", 90, 120, 150)], ["2025-03"], new Map())[0]!;
    expect(punto.r2p).toBeNull();
    expect(punto.oepe).toBeNull();
    expect(punto.kvs).toBe(90);
  });

  it("respeta el OEPE nulo del local sin servicio en vehículo", () => {
    const punto = officialTrend(
      [dia("2026-07-01", 85, 126, 0)],
      ["2026-07"],
      new Map([["2026-07", { r2p: 128, oepe: null }]]),
    )[0]!;
    expect(punto.r2p).toBe(128);
    expect(punto.oepe).toBeNull();
  });
});

describe("officialTimesByMonth", () => {
  it("indexa por restaurante y mes", () => {
    const indice = officialTimesByMonth([
      { restaurant_id: "R001", year: 2026, month: 2, r2p: 137, oepe: 165 },
      { restaurant_id: "R001", year: 2026, month: 7, r2p: 128, oepe: 169 },
    ]);
    expect(indice.get("R001")?.get("2026-02")?.r2p).toBe(137);
    expect(indice.get("R001")?.get("2026-07")?.oepe).toBe(169);
  });

  it("conserva el OEPE nulo del local sin servicio en vehículo", () => {
    // Sin servicio en vehículo, OEPE nulo significa "no existe" y la franja no
    // se dibuja; un cero sería un tiempo inventado.
    const indice = officialTimesByMonth([
      { restaurant_id: "R002", year: 2026, month: 7, r2p: 128, oepe: null },
    ]);
    expect(indice.get("R002")?.get("2026-07")?.oepe).toBeNull();
  });
});
