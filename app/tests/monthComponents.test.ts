import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { MonthPerformance } from "../src/components/MonthPerformance";
import { MonthStatus } from "../src/components/MonthStatus";
import { MonthTimes } from "../src/components/MonthTimes";
import { MonthView } from "../src/components/MonthView";
import { ServiceTrendChart } from "../src/components/ServiceTrendChart";
import type { MonthData } from "../src/data/useMonth";
import { closedLaborNote } from "../src/lib/monthClosing";
import type { Restaurant } from "../src/lib/types";

const restaurantA: Restaurant = {
  id: "R001",
  name: "Restaurante A",
  sort_order: 1,
  has_drive_through: true,
};

type SnapshotMonthData = MonthData & {
  officialTimeSnapshots: Map<string, Map<string, { r2p: number | null; oepe: number | null }>>;
};

function monthWithTimes({
  month,
  windowEnd,
  official,
  snapshots,
}: {
  month: string;
  windowEnd: string;
  official: { r2p: number | null; oepe: number | null };
  snapshots: Map<string, Map<string, { r2p: number | null; oepe: number | null }>>;
}): SnapshotMonthData {
  const day = {
    restaurant_id: "R001",
    sales_date: windowEnd,
    hourly_net_sum: 10_000,
    gc: 1_000,
    kvs: 80,
    r2p: 120,
    oepe: 150,
    service_time_gc: 1_000,
    source: "pos" as const,
    quality: "clean" as const,
  };
  return {
    month,
    restaurants: [restaurantA],
    windowDays: [day],
    trendDays: [day],
    trendMonths: [month],
    prior: new Map(),
    targets: new Map(),
    hours: new Map(),
    costParams: [],
    pctTargets: [],
    plActuals: [],
    closingProjections: [],
    national: new Map(),
    objectives: new Map(),
    officialTimes: new Map([["R001", new Map([[month, official]])]]),
    officialTimeSnapshots: snapshots,
    windowEnd,
    earliestMonth: month,
    importedAt: null,
  };
}

describe("MonthStatus", () => {
  it("no contradice la fuente de mano de obra que declara el bloque de cierre", () => {
    const html = renderToStaticMarkup(
      createElement(MonthStatus, {
        month: "2026-07",
        windowEnd: "2026-07-31",
      }),
    );

    expect(html).toContain("Mes cerrado · 31 días completos");
    expect(html).not.toContain("MO estimada");
    expect(html).not.toContain("sin datos");
  });
});

describe("MonthPerformance", () => {
  it("muestra solo productividad y deja la mano de obra para el cierre de la fuente mensual", () => {
    const rows = [
      {
        restaurant: restaurantA,
        vphh: 67.3,
        vphhYoy: 1.7,
        laborPct: 25.2,
        laborDiff: -0.3,
      },
    ];
    const total = {
      vphh: 67.3,
      vphhYoy: 1.7,
      laborPct: 25.2,
      laborDiff: -0.3,
    };

    const html = renderToStaticMarkup(
      createElement(MonthPerformance, {
        rows: rows.map((row) => ({
          ...row,
          laborPct: null,
          laborDiff: null,
        })),
        total: { ...total, laborPct: null, laborDiff: null },
        productivityNote: "9.842 h",
        closingTitle: null,
        closingNote: null,
      }),
    );

    expect(html).toContain("VPHH €");
    expect(html).toContain("YoY");
    expect(html).not.toContain("% MO");
    expect(html).not.toContain("Δ OBJ");
    expect(html).not.toContain("25,2");
  });
});

describe("MonthView", () => {
  it("unifica productividad y cierre sin repetir la venta del mes", () => {
    const base = monthWithTimes({
      month: "2026-08",
      windowEnd: "2026-08-19",
      official: { r2p: 116, oepe: 163 },
      snapshots: new Map([
        ["R001", new Map([["2026-08-19", { r2p: 116, oepe: 163 }]])],
      ]),
    });
    const data: MonthData = {
      ...base,
      hours: new Map([
        [
          "R001|2026-08-19",
          { restaurant_id: "R001", sales_date: "2026-08-19", clocked_hours: 100 },
        ],
      ]),
      pctTargets: [
        {
          restaurant_id: "R001",
          year: 2026,
          month: 8,
          target_pct: 26,
          target_mo_eur: 109_520.58,
          target_sales_eur: 421_233,
        },
      ],
      closingProjections: [
        {
          restaurant_id: "R001",
          year: 2026,
          month: 8,
          computed_at: "2026-08-20T16:48:00+02:00",
          days_in_month: 31,
          days_actual: 19,
          days_scheduled: 11,
          days_reference: 1,
          sales_projected: 421_233,
          hours_projected: 6_800,
          labor_cost_projected: 105_729.483,
        },
      ],
    };

    const html = renderToStaticMarkup(createElement(MonthView, { data, selected: "all" }));
    const tablaRendimiento = html.match(
      /<section class="monthTables"><div class="monthTable monthTable--performance[\s\S]*?<\/section>/,
    )?.[0];

    expect(html.match(/monthTable--performance/g)).toHaveLength(1);
    expect(html).not.toContain("monthTable--kpi");
    expect(html).not.toContain("monthTable--closing");
    expect(tablaRendimiento).toBeDefined();
    expect(tablaRendimiento).toContain("PRODUCTIVIDAD");
    expect(tablaRendimiento).toContain("CIERRE PROYECTADO");
    expect(tablaRendimiento).toContain("VPHH €");
    expect(tablaRendimiento).not.toContain("VENTA €");
    expect(tablaRendimiento).not.toContain("421.233");
    expect(tablaRendimiento).toContain("25,1");
    expect(tablaRendimiento).toContain("VPHH venta / horas fichadas");
    expect(tablaRendimiento).toContain("proyección de la fuente mensual");
  });

  it("distingue estimaciones y locales sin datos en el pie de un cierre mixto", () => {
    const note = closedLaborNote({ actual: 1, estimated: 1, unavailable: 1, restaurants: 3 });

    expect(note).toContain("P&L real en 1 de 3 locales");
    expect(note).toContain("1 local estimado por horas fichadas");
    expect(note).toContain("1 local sin P&L ni estimación completa");
    expect(note).not.toContain("resto estimado");
  });

  it("en un mes cerrado conserva la mano de obra real sin repetir la venta del P&L", () => {
    const day = {
      restaurant_id: "R001",
      sales_date: "2026-07-01",
      hourly_net_sum: 10_000,
      gc: 1_000,
      kvs: 80,
      r2p: 120,
      oepe: 150,
      service_time_gc: 1_000,
      source: "pos" as const,
      quality: "clean" as const,
    };
    const data: MonthData = {
      month: "2026-07",
      restaurants: [restaurantA],
      windowDays: [day],
      trendDays: [day],
      trendMonths: ["2026-07"],
      prior: new Map(),
      targets: new Map(),
      hours: new Map(),
      costParams: [],
      pctTargets: [
        {
          restaurant_id: "R001",
          year: 2026,
          month: 7,
          target_pct: 26,
          target_mo_eur: 26_000,
          target_sales_eur: 100_000,
        },
      ],
      plActuals: [
        {
          restaurant_id: "R001",
          year: 2026,
          month: 7,
          total_labor_eur: 25_000,
          net_sales_eur: 100_000,
        },
      ],
      closingProjections: [],
      national: new Map(),
      objectives: new Map([
        [
          "R001",
          new Map([
            ["2026-07", { restaurant_id: "R001", kvs: 81, r2p: 139, oepe: 162 }],
          ]),
        ],
      ]),
      officialTimes: new Map([
        ["R001", new Map([["2026-07", { r2p: 120, oepe: 150 }]])],
      ]),
      officialTimeSnapshots: new Map(),
      windowEnd: "2026-07-31",
      earliestMonth: "2026-07",
      importedAt: null,
    };

    const html = renderToStaticMarkup(createElement(MonthView, { data, selected: "all" }));

    expect(html).toContain("CIERRE REAL");
    expect(html).not.toContain("100.000");
    expect(html).toContain("25,0");
    expect(html).not.toContain("CIERRE PROYECTADO");
  });

  it("en el mes vivo usa la fotografía oficial exacta del último cierre", () => {
    // El mensual vigente puede ser anterior: si se usara para el chip, la
    // pantalla diría que hoy termina en un valor que la fuente de ventas no publicó hoy.
    const html = renderToStaticMarkup(
      createElement(MonthView, {
        data: monthWithTimes({
          month: "2026-08",
          windowEnd: "2026-08-19",
          official: { r2p: 150, oepe: 170 },
          snapshots: new Map([
            ["R001", new Map([["2026-08-19", { r2p: 123, oepe: 169 }]])],
          ]),
        }),
        selected: "R001",
      }),
    );

    expect(html).toContain('time__label">R2P</span><span class="time__value">123&quot;</span>');
    expect(html).toContain('time__label">OEPE</span><span class="time__value">169&quot;</span>');
  });

  it("en un mes cerrado usa la fotografía exacta, incluidos sus nulos explícitos", () => {
    const html = renderToStaticMarkup(
      createElement(MonthView, {
        data: monthWithTimes({
          month: "2026-08",
          windowEnd: "2026-08-31",
          official: { r2p: 124, oepe: 169 },
          snapshots: new Map([
            ["R001", new Map([["2026-08-31", { r2p: 123, oepe: null }]])],
          ]),
        }),
        selected: "R001",
      }),
    );

    expect(html).toContain('time__label">R2P</span><span class="time__value">123&quot;</span>');
    expect(html).toContain('time__label">OEPE</span><span class="time__value">—</span>');
    expect(html).not.toContain('time__label">R2P</span><span class="time__value">124&quot;</span>');
  });

  it("en el mes vivo deja R2P/OEPE en raya si falta la fotografía del último cierre", () => {
    const html = renderToStaticMarkup(
      createElement(MonthView, {
        data: monthWithTimes({
          month: "2026-08",
          windowEnd: "2026-08-19",
          official: { r2p: 150, oepe: 170 },
          snapshots: new Map(),
        }),
        selected: "R001",
      }),
    );

    expect(html).toContain('time__label">R2P</span><span class="time__value">—</span>');
    expect(html).toContain('time__label">OEPE</span><span class="time__value">—</span>');
  });

  it("en el mes cerrado conserva el mensual oficial si aún no hay fotografías históricas", () => {
    const html = renderToStaticMarkup(
      createElement(MonthView, {
        data: monthWithTimes({
          month: "2026-07",
          windowEnd: "2026-07-31",
          official: { r2p: 120, oepe: 150 },
          snapshots: new Map(),
        }),
        selected: "R001",
      }),
    );

    expect(html).toContain('time__label">R2P</span><span class="time__value">120&quot;</span>');
    expect(html).toContain('time__label">OEPE</span><span class="time__value">150&quot;</span>');
    expect(html).toContain("12 MESES");
  });
});

describe("MonthTimes", () => {
  it("abre en la media del mes y conserva la tendencia de doce meses en el selector", () => {
    const html = renderToStaticMarkup(
      createElement(MonthTimes, {
        single: {
          restaurant: restaurantA,
          kvs: 80,
          r2p: 120,
          oepe: 150,
          objectives: { restaurant_id: "R001", kvs: 81, r2p: 139, oepe: 162 },
        },
        byLocal: [],
        trends: new Map(),
        currentTrends: new Map([
          ["R001", [{ month: "2026-08-19", kvs: 80, r2p: 120, oepe: 150 }]],
        ]),
        objectives: new Map(),
        month: "2026-08",
        partialDays: { covered: 19, total: 31 },
        trendMonths: [],
        excludedDays: 0,
        unavailableDays: 0,
        missingDailyCloses: 1,
        missingOfficialSnapshots: 1,
      }),
    );

    expect(html).toContain("MES EN CURSO");
    expect(html).toContain("12 MESES");
    expect(html).toContain('aria-selected="true"');
    expect(html).toContain("R2P y OEPE, acumulado mensual oficial capturado cada día de la fuente de ventas");
    expect(html).toContain("hueco, día sin fotografía oficial");
    expect(html).not.toContain("media de los cierres diarios");
  });
});

describe("ServiceTrendChart", () => {
  it("en la vista diaria rotula solo el primero, cada quinto día y el último", () => {
    const points = Array.from({ length: 10 }, (_, i) => ({
      month: `2026-08-${String(i + 1).padStart(2, "0")}`,
      kvs: 80 + i,
      r2p: null,
      oepe: null,
    }));
    const html = renderToStaticMarkup(
      createElement(ServiceTrendChart, {
        points,
        objectives: new Map(),
        month: "2026-08",
        partialDays: null,
        axisMode: "day",
      }),
    );

    expect(html.match(/trendChart__cifra/g)).toHaveLength(3);
  });
});
