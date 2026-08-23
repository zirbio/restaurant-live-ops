import { describe, expect, it } from "vitest";

import {
  addTotals,
  blendedLaborCost,
  blendedLaborTarget,
  closingDaysBreakdown,
  closingFor,
  closingOldestComputedAt,
  closingTotal,
  costParamsFor,
  differencePp,
  estimatedLaborCost,
  growthPct,
  implausibleDays,
  laborPct,
  MIN_PLAUSIBLE_SECONDS,
  missingTargetDays,
  monthTotals,
  nationalYoy,
  publishableTarget,
  publishableTargetGc,
  publishableLaborCost,
  publishablePriorVphh,
  publishableVphh,
  publishedLaborCost,
  serviceTrend,
  vphh,
  weightedServiceTime,
  type CostParamsRow,
  type HoursRow,
  type MonthDayRow,
  type MonthProjectionRow,
  type MonthSources,
  type PlLaborActualRow,
  type PriorDayRow,
  type ProjectionRow,
  type PublishedLaborCost,
} from "../src/lib/monthly";

function dia(
  sales_date: string,
  net: number | null,
  extra: Partial<MonthDayRow> = {},
): MonthDayRow {
  return {
    restaurant_id: "R001",
    sales_date,
    hourly_net_sum: net,
    gc: 100,
    kvs: null,
    r2p: null,
    oepe: null,
    ...extra,
  };
}

function mapa<T extends { restaurant_id: string; sales_date: string }>(rows: T[]) {
  return new Map(rows.map((r) => [`${r.restaurant_id}|${r.sales_date}`, r]));
}

const SIN_FUENTES = {
  restaurantId: "R001",
  prior: new Map<string, PriorDayRow>(),
  targets: new Map<string, ProjectionRow>(),
  hours: new Map<string, HoursRow>(),
};

/** Arma las fuentes a partir de unos días sueltos, como hace la pantalla. */
function fuentes(rows: MonthDayRow[], extra: Partial<MonthSources> = {}) {
  return {
    ...SIN_FUENTES,
    calendarDays: rows.map((r) => r.sales_date),
    real: new Map(rows.map((r) => [`${r.restaurant_id}|${r.sales_date}`, r])),
    ...extra,
  };
}

describe("totales del mes", () => {
  it("suma la venta de los días que la tienen", () => {
    const t = monthTotals(
      fuentes([dia("2026-07-01", 1000), dia("2026-07-02", 1500), dia("2026-07-03", null)]),
    );
    expect(t.net).toBe(2500);
    expect(t.days).toBe(2);
  });

  it("suma el objetivo de TODOS los días de la ventana, tengan venta o no", () => {
    // Un día que la fuente de ventas no llegó a capturar sigue teniendo objetivo. Quitárselo
    // maquillaría la desviación del mes.
    const t = monthTotals(
      fuentes([dia("2026-07-01", 1000), dia("2026-07-02", null)], {
        targets: mapa<ProjectionRow>([
          { restaurant_id: "R001", sales_date: "2026-07-01", projected_net: 900, projected_gc: 80 },
          { restaurant_id: "R001", sales_date: "2026-07-02", projected_net: 1100, projected_gc: 90 },
        ]),
      }),
    );
    expect(t.target).toBe(2000);
    expect(t.net).toBe(1000);
  });

  it("el interanual solo cuenta los días con dato en los dos años", () => {
    const t = monthTotals(
      fuentes([dia("2026-07-01", 1000), dia("2026-07-02", 1500)], {
        // 364 días antes del 1 de julio de 2026 es el 2 de julio de 2025.
        prior: mapa<PriorDayRow>([
          { restaurant_id: "R001", sales_date: "2025-07-02", net: 800, gc: 90 },
        ]),
      }),
    );
    expect(t.comparableDays).toBe(1);
    expect(t.comparableNet).toBe(1000);
    expect(t.priorNet).toBe(800);
    // El segundo día no tiene pareja: no entra en NINGUNO de los dos lados.
    expect(growthPct(t.comparableNet, t.priorNet)).toBeCloseTo(25, 6);
  });

  it("empareja los guest counts aparte de la venta", () => {
    // Un día puede traer venta en los dos años y guest counts en uno solo.
    // Mezclar las dos poblaciones daría un crecimiento de clientes no medido.
    const t = monthTotals(
      fuentes([dia("2026-07-01", 1000, { gc: 100 })], {
        prior: mapa<PriorDayRow>([
          { restaurant_id: "R001", sales_date: "2025-07-02", net: 800, gc: null },
        ]),
      }),
    );
    expect(t.comparableDays).toBe(1);
    expect(t.comparableGcDays).toBe(0);
    expect(t.comparableGc).toBeNull();
  });

  it("el objetivo cuenta también los días que la fuente de ventas no capturó", () => {
    // Un día sin captura NO deja fila en sales_daily_totals. Si el objetivo se
    // sumara sobre las filas existentes, encogería hasta hacer cuadrar el mes
    // solo: la desviación saldría mejor cuanto peor fuera la captura.
    const t = monthTotals({
      ...SIN_FUENTES,
      calendarDays: ["2026-07-01", "2026-07-02", "2026-07-03"],
      real: new Map([
        ["R001|2026-07-01", dia("2026-07-01", 1000)],
        ["R001|2026-07-03", dia("2026-07-03", 1200)],
      ]),
      targets: mapa<ProjectionRow>([
        { restaurant_id: "R001", sales_date: "2026-07-01", projected_net: 900, projected_gc: 80 },
        { restaurant_id: "R001", sales_date: "2026-07-02", projected_net: 1100, projected_gc: 90 },
        { restaurant_id: "R001", sales_date: "2026-07-03", projected_net: 1000, projected_gc: 85 },
      ]),
    });
    expect(t.target).toBe(3000);
    expect(t.net).toBe(2200);
    // Y se sabe que falta un día: 2 de 3.
    expect(t.days).toBe(2);
    expect(t.expectedDays).toBe(3);
  });

  it("un mes sin días devuelve huecos, no ceros", () => {
    const t = monthTotals(fuentes([]));
    expect(t.net).toBeNull();
    expect(t.target).toBeNull();
    expect(t.hours).toBeNull();
  });

  it("suma dos locales sin inventar ceros", () => {
    const a = monthTotals(fuentes([dia("2026-07-01", 1000)]));
    const b = monthTotals(fuentes([dia("2026-07-01", null)]));
    expect(addTotals(a, b).net).toBe(1000);
    expect(addTotals(b, b).net).toBeNull();
  });
});

describe("VPHH: numerador y denominador sobre los mismos días", () => {
  const horas = (fechas: [string, number][]) =>
    mapa<HoursRow>(
      fechas.map(([sales_date, clocked_hours]) => ({
        restaurant_id: "R001",
        sales_date,
        clocked_hours,
      })),
    );

  it("solo empareja los días que traen venta Y horas", () => {
    const t = monthTotals({
      ...SIN_FUENTES,
      calendarDays: ["2026-07-01", "2026-07-02"],
      real: new Map([
        ["R001|2026-07-01", dia("2026-07-01", 1000)],
        ["R001|2026-07-02", dia("2026-07-02", 1500)],
      ]),
      hours: horas([["2026-07-01", 20]]),
    });
    // La venta del mes son 2.500 €, pero el VPHH solo puede salir del día que
    // tiene las dos cosas: 1.000 / 20 = 50, no 2.500 / 20 = 125.
    expect(t.net).toBe(2500);
    expect(t.pairedNet).toBe(1000);
    expect(t.pairedHours).toBe(20);
    expect(t.pairedDays).toBe(1);
    expect(vphh(t.pairedNet, t.pairedHours)).toBe(50);
  });

  it("las horas del año anterior salen SOLO de los días comparables", () => {
    // Si las horas del año anterior cubrieran días cuya venta no se compara,
    // el VPHH interanual dividiría la venta de unos días entre las horas de
    // otros y fabricaría una mejora de productividad que no ha ocurrido.
    const t = monthTotals({
      ...SIN_FUENTES,
      calendarDays: ["2026-07-01", "2026-07-02"],
      real: new Map([
        ["R001|2026-07-01", dia("2026-07-01", 1000)],
        ["R001|2026-07-02", dia("2026-07-02", 1000)],
      ]),
      // Solo el 2 de julio de 2025 (pareja del 1 de julio de 2026) tiene venta.
      prior: mapa<PriorDayRow>([
        { restaurant_id: "R001", sales_date: "2025-07-02", net: 900, gc: 80 },
      ]),
      hours: horas([
        ["2025-07-02", 10],
        ["2025-07-03", 10],
      ]),
    });
    expect(t.priorPairedNet).toBe(900);
    expect(t.priorPairedHours).toBe(10);
    expect(t.priorPairedDays).toBe(1);
  });

  it("el conjunto suma los recuentos, para poder exigir cobertura completa", () => {
    const conHoras = monthTotals({
      ...SIN_FUENTES,
      calendarDays: ["2026-07-01"],
      real: new Map([["R001|2026-07-01", dia("2026-07-01", 1000)]]),
      hours: horas([["2026-07-01", 20]]),
    });
    const sinHoras = monthTotals({
      ...SIN_FUENTES,
      restaurantId: "R002",
      calendarDays: ["2026-07-01"],
      real: new Map([
        ["R002|2026-07-01", { ...dia("2026-07-01", 800), restaurant_id: "R002" }],
      ]),
    });
    const total = addTotals(conHoras, sinHoras);
    // Dos restaurantes, un día cada uno: se esperan 2 días-restaurante y solo
    // uno está emparejado. Es lo que permite a la pantalla no publicar un VPHH
    // con la venta de dos locales sobre las horas de uno.
    expect(total.expectedDays).toBe(2);
    expect(total.pairedDays).toBe(1);
    expect(total.net).toBe(1800);
  });
});

describe("reglas de publicación: una cifra sale o no sale", () => {
  const horas = (fechas: [string, number][]) =>
    mapa<HoursRow>(
      fechas.map(([sales_date, clocked_hours]) => ({
        restaurant_id: "R001",
        sales_date,
        clocked_hours,
      })),
    );

  /** Un mes de dos días con venta, y las horas que se le quieran poner. */
  const mes = (conHoras: [string, number][], prior: [string, number][] = []) =>
    monthTotals({
      ...SIN_FUENTES,
      calendarDays: ["2026-07-01", "2026-07-02"],
      real: new Map([
        ["R001|2026-07-01", dia("2026-07-01", 1000)],
        ["R001|2026-07-02", dia("2026-07-02", 1000)],
      ]),
      prior: mapa<PriorDayRow>(
        prior.map(([sales_date, net]) => ({ restaurant_id: "R001", sales_date, net, gc: 90 })),
      ),
      hours: horas(conHoras),
    });

  it("el VPHH no se publica si las horas no cubren la ventana entera", () => {
    // Es la guarda que impide dividir la venta de dos días entre las horas de
    // uno: sin ella el VPHH sale inflado y nada en pantalla lo delata.
    const incompleto = mes([["2026-07-01", 20]]);
    expect(incompleto.pairedDays).toBe(1);
    expect(publishableVphh(incompleto)).toBeNull();

    const completo = mes([
      ["2026-07-01", 20],
      ["2026-07-02", 20],
    ]);
    expect(publishableVphh(completo)).toBe(50);
  });

  it("el VPHH del año anterior exige la misma cobertura", () => {
    // 364 días antes del 1 y el 2 de julio de 2026: el 2 y el 3 de julio de 2025.
    const soloUno = mes(
      [
        ["2026-07-01", 20],
        ["2026-07-02", 20],
        ["2025-07-02", 10],
      ],
      [
        ["2025-07-02", 900],
        ["2025-07-03", 900],
      ],
    );
    expect(soloUno.priorPairedDays).toBe(1);
    expect(publishablePriorVphh(soloUno)).toBeNull();
  });

  it("el coste de mano de obra tampoco se estima con horas a medias", () => {
    const params = {
      restaurant_id: "R001",
      fixed_cost_month: 3100,
      variable_cost_hour: 10,
      calibrated_at: "x",
      valid_from: "2026-01-01",
      valid_to: null,
    };
    expect(publishableLaborCost(mes([["2026-07-01", 20]]), params, "2026-07")).toBeNull();
    const completo = mes([
      ["2026-07-01", 20],
      ["2026-07-02", 20],
    ]);
    // 2 de 31 días de julio: el fijo entra prorrateado.
    expect(publishableLaborCost(completo, params, "2026-07")).toBeCloseTo(
      3100 * (2 / 31) + 400,
      6,
    );
  });

  it("sin parámetros de coste no se inventa nada", () => {
    const completo = mes([
      ["2026-07-01", 20],
      ["2026-07-02", 20],
    ]);
    expect(publishableLaborCost(completo, undefined, "2026-07")).toBeNull();
  });
});

describe("días con un tiempo imposible", () => {
  it("cuenta días distintos, no exclusiones por métrica", () => {
    // Un día con el KVS roto y otro con el R2P roto son DOS días fuera. El
    // aviso existe para que nadie tome la media por completa: quedarse corto
    // lo vacía de sentido.
    const dias = [
      dia("2026-07-04", 1000, { kvs: 2, r2p: 120, oepe: 160 }),
      dia("2026-07-19", 1000, { kvs: 90, r2p: 1, oepe: 160 }),
      dia("2026-07-20", 1000, { kvs: 90, r2p: 120, oepe: 160 }),
    ];
    expect(implausibleDays(dias)).toBe(2);
  });

  it("un solo día con dos métricas rotas sigue siendo un día", () => {
    expect(implausibleDays([dia("2026-07-20", 1000, { kvs: 2, r2p: 1, oepe: 160 })])).toBe(1);
  });

  it("sin nada imposible, cero", () => {
    expect(implausibleDays([dia("2026-07-20", 1000, { kvs: 90, r2p: 120, oepe: 160 })])).toBe(0);
  });

  it("cuenta solo las métricas que se le pidan", () => {
    // R2P y OEPE mensuales conservan la cifra publicada, no una media diaria.
    // KVS sí se deriva y, por tanto, solo sus valores imposibles cuentan aquí.
    const dias = [
      dia("2026-07-19", 1000, { kvs: 90, r2p: 1, oepe: 160 }),
      dia("2026-07-20", 1000, { kvs: 2, r2p: 120, oepe: 160 }),
    ];
    expect(implausibleDays(dias, ["kvs"])).toBe(1);
    expect(implausibleDays(dias)).toBe(2);
  });
});

describe("la previsión tiene que cubrir la ventana entera", () => {
  const tres = ["2026-07-01", "2026-07-02", "2026-07-03"];
  const conDias = (dias: { d: string; net: number; gc: number }[]) =>
    monthTotals({
      restaurantId: "R001",
      calendarDays: tres,
      real: mapa<MonthDayRow>([
        { restaurant_id: "R001", sales_date: "2026-07-01", hourly_net_sum: 1000, gc: 90, kvs: null, r2p: null, oepe: null },
      ]),
      prior: new Map(),
      targets: mapa<ProjectionRow>(
        dias.map((x) => ({
          restaurant_id: "R001",
          sales_date: x.d,
          projected_net: x.net,
          projected_gc: x.gc,
        })),
      ),
      hours: new Map(),
    });

  it("con los tres días, publica la suma", () => {
    const t = conDias(tres.map((d) => ({ d, net: 1000, gc: 85 })));
    expect(publishableTarget(t)).toBe(3000);
    expect(publishableTargetGc(t)).toBe(255);
    expect(missingTargetDays(t)).toBe(0);
  });

  it("si falta un día NO publica una meta corta: la desviación saldría mejor", () => {
    // Sumar dos días de previsión contra la venta de tres inventa un
    // cumplimiento que no existe. Antes no podía pasar —el plan base trae los 365
    // días— pero la previsión de la fuente de personal solo existe donde el worker capturó.
    const t = conDias(tres.slice(0, 2).map((d) => ({ d, net: 1000, gc: 85 })));
    expect(t.target).toBe(2000); // la suma cruda sigue ahí, para diagnóstico
    expect(publishableTarget(t)).toBeNull();
    expect(publishableTargetGc(t)).toBeNull();
    expect(missingTargetDays(t)).toBe(1);
  });

  it("venta y clientes se cuentan por separado", () => {
    const t = monthTotals({
      restaurantId: "R001",
      calendarDays: tres,
      real: new Map(),
      prior: new Map(),
      targets: mapa<ProjectionRow>(
        tres.map((d, i) => ({
          restaurant_id: "R001",
          sales_date: d,
          projected_net: 1000,
          // Al tercer día le falta el de clientes, no el de venta.
          projected_gc: i === 2 ? null : 85,
        })),
      ),
      hours: new Map(),
    });
    expect(publishableTarget(t)).toBe(3000);
    expect(publishableTargetGc(t)).toBeNull();
  });

  it("los locales se suman y basta con que a uno le falte un día", () => {
    const completo = conDias(tres.map((d) => ({ d, net: 1000, gc: 85 })));
    const corto = conDias(tres.slice(0, 2).map((d) => ({ d, net: 1000, gc: 85 })));
    expect(publishableTarget(addTotals(completo, corto))).toBeNull();
    expect(missingTargetDays(addTotals(completo, corto))).toBe(1);
  });
});

describe("comparable de España", () => {
  const agosto = { yoyPct: 5.8, coversThrough: "2026-08-01", closed: false };

  it("vale cuando cubre los mismos días que la ventana", () => {
    expect(nationalYoy(agosto, "2026-08-01")).toBe(5.8);
  });

  it("no vale si llega a otro día: serían dos periodos distintos", () => {
    // La lectura de esta mañana cubre hasta ayer. Si la ventana propia ya
    // llega a hoy —o se quedó en anteayer—, enfrentarlas mentiría.
    expect(nationalYoy(agosto, "2026-08-02")).toBeNull();
    expect(nationalYoy(agosto, "2026-07-31")).toBeNull();
  });

  it("un mes cerrado cubre hasta su último día", () => {
    const julio = { yoyPct: 2.5, coversThrough: "2026-07-31", closed: true };
    expect(nationalYoy(julio, "2026-07-31")).toBe(2.5);
  });

  it("sin lectura o sin ventana, no hay comparable", () => {
    expect(nationalYoy(undefined, "2026-08-01")).toBeNull();
    expect(nationalYoy(null, "2026-08-01")).toBeNull();
    expect(nationalYoy(agosto, null)).toBeNull();
  });
});

describe("crecimientos y diferenciales", () => {
  it("no calcula un porcentaje sin los dos lados", () => {
    expect(growthPct(100, null)).toBeNull();
    expect(growthPct(null, 100)).toBeNull();
    expect(growthPct(100, 0)).toBeNull();
  });

  it("el diferencial son puntos, no un cociente", () => {
    expect(differencePp(-5, -1.6)).toBeCloseTo(-3.4, 6);
    expect(differencePp(-5, null)).toBeNull();
  });
});

describe("productividad y mano de obra", () => {
  it("sin horas no hay VPHH: nunca es cero", () => {
    expect(vphh(1000, null)).toBeNull();
    expect(vphh(1000, 0)).toBeNull();
    expect(vphh(1000, 20)).toBe(50);
  });

  it("un mes completo aplica el fijo entero", () => {
    const p: CostParamsRow = {
      restaurant_id: "R001",
      fixed_cost_month: 3000,
      variable_cost_hour: 10,
      calibrated_at: "2026-07-26T00:00:00Z",
      valid_from: "2026-01-01",
      valid_to: null,
    };
    const coste = estimatedLaborCost(p, { hours: 100, coveredDays: 31, month: "2026-07" });
    expect(coste).toBe(4000);
    expect(laborPct(coste, 10_000)).toBe(40);
  });

  it("media docena de días del mes en curso NO carga el fijo entero", () => {
    const p: CostParamsRow = {
      restaurant_id: "R001",
      fixed_cost_month: 31000,
      variable_cost_hour: 10,
      calibrated_at: "2026-07-26T00:00:00Z",
      valid_from: "2026-01-01",
      valid_to: null,
    };
    // 10 de 31 días: el fijo entra prorrateado, no completo.
    const coste = estimatedLaborCost(p, { hours: 100, coveredDays: 10, month: "2026-07" });
    expect(coste).toBeCloseTo(31000 * (10 / 31) + 1000, 6);
  });

  it("sin parámetros o sin horas no se estima nada", () => {
    expect(estimatedLaborCost(undefined, { hours: 100, coveredDays: 31, month: "2026-07" })).toBeNull();
    const p: CostParamsRow = {
      restaurant_id: "R001",
      fixed_cost_month: 1,
      variable_cost_hour: 1,
      calibrated_at: "x",
      valid_from: "2026-01-01",
      valid_to: null,
    };
    expect(estimatedLaborCost(p, { hours: null, coveredDays: 31, month: "2026-07" })).toBeNull();
  });

  const OBJETIVOS_SINTETICOS = [
      {
        restaurant_id: "R001",
        year: 2026,
        month: 7,
        target_pct: 20,
        target_mo_eur: 20,
        target_sales_eur: 100,
      },
      {
        restaurant_id: "R002",
        year: 2026,
        month: 7,
        target_pct: 30,
        target_mo_eur: 60,
        target_sales_eur: 200,
      },
      {
        restaurant_id: "R003",
        year: 2026,
        month: 7,
        target_pct: 25,
        target_mo_eur: 75,
        target_sales_eur: 300,
      },
  ];

  it("el objetivo del conjunto es la suma partida, no la media de porcentajes", () => {
    // El agregado se calcula desde los importes, no promediando porcentajes.
    expect(blendedLaborTarget(OBJETIVOS_SINTETICOS, 3)).toBeCloseTo(25.83, 2);
  });

  it("con dos objetivos de tres no hay objetivo del conjunto", () => {
    // Sería el porcentaje de una plantilla que no es la del titular.
    expect(blendedLaborTarget(OBJETIVOS_SINTETICOS.slice(0, 2), 3)).toBeNull();
  });

  it("coge el parámetro vigente ese mes", () => {
    const params: CostParamsRow[] = [
      {
        restaurant_id: "R001",
        fixed_cost_month: 1,
        variable_cost_hour: 1,
        calibrated_at: "x",
        valid_from: "2025-01-01",
        valid_to: "2025-12-31",
      },
      {
        restaurant_id: "R001",
        fixed_cost_month: 2,
        variable_cost_hour: 2,
        calibrated_at: "x",
        valid_from: "2026-01-01",
        valid_to: null,
      },
    ];
    expect(costParamsFor(params, "R001", "2026-07-31")?.fixed_cost_month).toBe(2);
    expect(costParamsFor(params, "R001", "2025-07-31")?.fixed_cost_month).toBe(1);
    expect(costParamsFor(params, "R002", "2026-07-31")).toBeUndefined();
  });
});

describe("coste real del P&L", () => {
  const real: PlLaborActualRow[] = [
    {
      restaurant_id: "R001",
      year: 2026,
      month: 6,
      total_labor_eur: 2_500,
      net_sales_eur: 10_000,
    },
  ];

  it("manda sobre la estimación cuando el mes ha cerrado", () => {
    const publicado = publishedLaborCost(real, "R001", "2026-06", 2_600);
    expect(publicado).toEqual({ cost: 2_500, net: 10_000, source: "real" });
    // El %MO real sale entero del P&L: coste contable y venta contable.
    expect(laborPct(publicado!.cost, publicado!.net)).toBe(25);
  });

  it("conserva la estimación en un mes cuyo P&L no ha llegado", () => {
    const publicado = publishedLaborCost(real, "R001", "2026-07", 2_600);
    expect(publicado).toEqual({ cost: 2_600, net: null, source: "estimado" });
  });

  it("no publica nada si no hay ni real ni estimación", () => {
    expect(publishedLaborCost(real, "R001", "2026-07", null)).toBeNull();
  });

  it("no confunde restaurantes", () => {
    expect(publishedLaborCost(real, "R002", "2026-06", 80000)?.source).toBe("estimado");
  });
});

describe("blendedLaborCost: el Total empareja coste y venta por local", () => {
  const realCentro: PublishedLaborCost = { cost: 2_500, net: 10_000, source: "real" };
  const realNorte: PublishedLaborCost = { cost: 3_000, net: 12_000, source: "real" };
  const realSur: PublishedLaborCost = { cost: 2_000, net: 8_000, source: "real" };

  it("los tres reales: suma el coste y la venta del P&L de cada uno", () => {
    // El sourceNet de cada local es disparatado a propósito: con coste real no
    // debe pesar nada, y si pesara este test lo pondría en evidencia.
    const total = blendedLaborCost([
      { published: realCentro, sourceNet: 1 },
      { published: realNorte, sourceNet: 1 },
      { published: realSur, sourceNet: 1 },
    ]);
    expect(total.cost).toBe(7_500);
    expect(total.net).toBe(30_000);
    expect(total.realCount).toBe(3);
    expect(laborPct(total.cost, total.net)).toBe(25);
  });

  it("ninguno real: usa la estimación y la venta de la fuente de ventas de cada local", () => {
    const total = blendedLaborCost([
      { published: { cost: 30000, net: null, source: "estimado" }, sourceNet: 100000 },
      { published: { cost: 25000, net: null, source: "estimado" }, sourceNet: 90000 },
      { published: { cost: 20000, net: null, source: "estimado" }, sourceNet: 70000 },
    ]);
    expect(total.cost).toBe(75000);
    expect(total.net).toBe(260000);
    expect(total.realCount).toBe(0);
  });

  it("mixto: cada local aporta la venta de SU propio origen", () => {
    // Cada coste conserva el denominador de su propio origen.
    const total = blendedLaborCost([
      { published: realCentro, sourceNet: 11_000 },
      { published: { cost: 2_500, net: null, source: "estimado" }, sourceNet: 9_000 },
    ]);
    expect(total.cost).toBe(5_000);
    expect(total.net).toBe(19_000);
    expect(total.realCount).toBe(1);
  });

  it("cuenta los locales reales aunque a otro le falte el coste: el Total sale null, el recuento no", () => {
    // Es la propiedad que hace que el pie siga diciendo la verdad ("real en 1
    // de 3 locales") aunque la tabla no pueda sumar un Total.
    const total = blendedLaborCost([
      { published: realCentro, sourceNet: 11_000 },
      { published: null, sourceNet: 9_000 },
    ]);
    expect(total.cost).toBeNull();
    expect(total.net).toBeNull();
    expect(total.realCount).toBe(1);
  });

  it("sin venta de reserva para una estimación, no inventa un cero: el Total sale null", () => {
    // Por construcción esto no debería pasar (`hasFullHourCoverage` garantiza
    // que una estimación siempre trae su venta de la fuente de ventas), pero si pasara, la
    // función no rellena el hueco con un 0 que fabricaría un %MO falso.
    const total = blendedLaborCost([
      { published: realCentro, sourceNet: 11_000 },
      { published: { cost: 2_500, net: null, source: "estimado" }, sourceNet: null },
    ]);
    expect(total.cost).toBeNull();
    expect(total.net).toBeNull();
    expect(total.realCount).toBe(1);
  });

  it("sin locales, no hay Total", () => {
    const total = blendedLaborCost([]);
    expect(total.cost).toBeNull();
    expect(total.net).toBeNull();
    expect(total.realCount).toBe(0);
  });
});

describe("tiempos de servicio del mes", () => {
  const conTiempo = (fecha: string, r2p: number, gc: number) =>
    dia(fecha, 1000, { r2p, gc });

  it("pondera por guest counts, no hace media simple", () => {
    // Un día flojo y lento no puede pesar lo mismo que uno lleno y rápido.
    const r = weightedServiceTime(
      [conTiempo("2026-07-01", 200, 100), conTiempo("2026-07-02", 100, 900)],
      "r2p",
    );
    expect(r.value).toBeCloseTo((200 * 100 + 100 * 900) / 1000, 6);
    expect(r.value).not.toBeCloseTo(150, 1);
    expect(r.days).toBe(2);
  });

  it("pondera el tiempo con los clientes de la misma fecha de caja la fuente de ventas", () => {
    // La venta usa 06→06, pero el tiempo oficial usa su fecha de caja. Pesarlo
    // con clientes de otra ventana volvería a mezclar periodos.
    const r = weightedServiceTime(
      [
        dia("2026-07-01", 1000, { r2p: 200, gc: 900, service_time_gc: 100 }),
        dia("2026-07-02", 1000, { r2p: 100, gc: 100, service_time_gc: 900 }),
      ],
      "r2p",
    );
    expect(r.value).toBeCloseTo((200 * 100 + 100 * 900) / 1000, 6);
  });

  it("descarta los valores imposibles y los cuenta", () => {
    // Un valor físicamente imposible no puede alterar el juicio del mes.
    const r = weightedServiceTime(
      [conTiempo("2026-07-01", 120, 100), conTiempo("2026-07-20", 1, 800)],
      "r2p",
    );
    expect(r.value).toBe(120);
    expect(r.excluded).toBe(1);
    expect(r.days).toBe(1);
    expect(MIN_PLAUSIBLE_SECONDS).toBe(30);
  });

  it("un día sin esa métrica no cuenta como cero", () => {
    const r = weightedServiceTime(
      [conTiempo("2026-07-01", 120, 100), dia("2026-07-02", 1000, { r2p: null, gc: 900 })],
      "r2p",
    );
    expect(r.value).toBe(120);
  });

  it("no publica una media parcial si una jornada efectiva perdió el tiempo exacto", () => {
    // Al recomponer 06→06 con dos días de caja, la fuente de ventas no da los pesos para
    // partir KVS. Usar solo el resto del mes parecería una cifra completa.
    const r = weightedServiceTime(
      [
        dia("2026-07-01", 1000, { kvs: 80, gc: 100, quality: "clean" }),
        dia("2026-07-02", 1000, { kvs: null, gc: 900, quality: "rebucketed" }),
      ],
      "kvs",
    );
    expect(r.value).toBeNull();
    expect(r.unavailable).toBe(1);
    expect(r.days).toBe(1);
  });

  it("un día sin guest counts no pesa: no se sabe cuánto vale", () => {
    const r = weightedServiceTime(
      [conTiempo("2026-07-01", 120, 100), dia("2026-07-02", 1000, { r2p: 500, gc: 0 })],
      "r2p",
    );
    expect(r.value).toBe(120);
  });

  it("sin ningún día con la métrica devuelve hueco, no cero", () => {
    expect(weightedServiceTime([dia("2026-07-01", 1000)], "oepe").value).toBeNull();
  });
});

describe("tendencia mensual", () => {
  it("da un punto por mes pedido, con hueco donde no hay dato", () => {
    const puntos = serviceTrend(
      [
        dia("2026-01-15", 1000, { r2p: 120, gc: 100 }),
        dia("2026-03-15", 1000, { r2p: 140, gc: 100 }),
      ],
      ["2026-01", "2026-02", "2026-03"],
    );
    expect(puntos.map((p) => p.month)).toEqual(["2026-01", "2026-02", "2026-03"]);
    expect(puntos[0]?.r2p).toBe(120);
    // Febrero no tiene dato: es hueco, no una interpolación entre 120 y 140.
    expect(puntos[1]?.r2p).toBeNull();
    expect(puntos[2]?.r2p).toBe(140);
  });
});

describe("cierre proyectado", () => {
  const proyecciones: MonthProjectionRow[] = [
    {
      restaurant_id: "R001",
      year: 2026,
      month: 8,
      computed_at: "2026-08-10T05:15:00Z",
      days_in_month: 31,
      days_actual: 9,
      days_scheduled: 7,
      days_reference: 15,
      sales_projected: 1000,
      hours_projected: 100,
      labor_cost_projected: 250,
    },
  ];

  it("da el %MO del cierre y su desviación contra el objetivo del mes", () => {
    const fila = closingFor(proyecciones, "R001", "2026-08");
    expect(fila).not.toBeNull();
    expect(laborPct(fila!.labor_cost_projected, fila!.sales_projected)).toBe(25);
  });

  it("no cruza meses ni restaurantes", () => {
    expect(closingFor(proyecciones, "R001", "2026-07")).toBeNull();
    expect(closingFor(proyecciones, "R002", "2026-08")).toBeNull();
  });

  it("el total solo existe con los tres locales", () => {
    expect(closingTotal(proyecciones, ["R001", "R002", "R003"], "2026-08")).toBeNull();
    const total = closingTotal(proyecciones, ["R001"], "2026-08");
    expect(total).toEqual({ sales: 1000, cost: 250 });
  });
});

describe("el pie del cierre no atribuye a todos el reparto de uno solo", () => {
  const restaurantA: MonthProjectionRow = {
    restaurant_id: "R001",
    year: 2026,
    month: 8,
    computed_at: "2026-08-11T05:20:00Z",
    days_in_month: 31,
    days_actual: 10,
    days_scheduled: 13,
    days_reference: 8,
    sales_projected: 1000,
    hours_projected: 100,
    labor_cost_projected: 250,
  };
  const restaurantB: MonthProjectionRow = {
    restaurant_id: "R002",
    year: 2026,
    month: 8,
    computed_at: "2026-08-11T06:10:00Z",
    days_in_month: 31,
    days_actual: 10,
    days_scheduled: 6,
    days_reference: 15,
    sales_projected: 800,
    hours_projected: 90,
    labor_cost_projected: 240,
  };

  describe("closingDaysBreakdown", () => {
    it("sin ninguna proyección no hay nada que resumir", () => {
      expect(closingDaysBreakdown([])).toBeNull();
    });

    it("con un solo local imprime SUS números, no un rango", () => {
      expect(closingDaysBreakdown([restaurantA])).toEqual({
        actual: "10",
        scheduled: "13",
        reference: "8",
      });
    });

    it("cuando los locales coinciden en un campo imprime un número, y el rango cuando no", () => {
      // days_actual coincide (10 en los dos); scheduled y reference no.
      expect(closingDaysBreakdown([restaurantA, restaurantB])).toEqual({
        actual: "10",
        scheduled: "6-13",
        reference: "8-15",
      });
    });
  });

  describe("closingOldestComputedAt", () => {
    it("sin proyecciones no hay fecha", () => {
      expect(closingOldestComputedAt([])).toBeNull();
    });

    it("es la más antigua, no la del primer local de la lista", () => {
      // El resultado no puede depender del orden de entrada.
      expect(closingOldestComputedAt([restaurantB, restaurantA])).toBe(restaurantA.computed_at);
      expect(closingOldestComputedAt([restaurantA, restaurantB])).toBe(restaurantA.computed_at);
    });
  });
});
