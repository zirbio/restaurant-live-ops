import { afterEach, describe, expect, it, vi } from "vitest";

const mockedMonthLoad = vi.hoisted(() => {
  type Response = { data: unknown[] | null; error: { message: string } | null };
  type Query = {
    table: string;
    selects: string[];
    filters: Array<[string, string, unknown]>;
  };

  const queries: Query[] = [];
  const responses = new Map<string, Response>();
  const states: unknown[] = [];
  let runEffects = false;

  const from = vi.fn((table: string) => {
    const query: Query = { table, selects: [], filters: [] };
    queries.push(query);
    const response = (): Response => responses.get(table) ?? { data: [], error: null };
    const chain = {
      select: (columns: string) => {
        query.selects.push(columns);
        return chain;
      },
      gte: (column: string, value: unknown) => {
        query.filters.push(["gte", column, value]);
        return chain;
      },
      lte: (column: string, value: unknown) => {
        query.filters.push(["lte", column, value]);
        return chain;
      },
      lt: (column: string, value: unknown) => {
        query.filters.push(["lt", column, value]);
        return chain;
      },
      eq: (column: string, value: unknown) => {
        query.filters.push(["eq", column, value]);
        return chain;
      },
      order: () => chain,
      range: () => chain,
      limit: () => chain,
      then: <T>(resolve: (value: Response) => T, reject?: (reason: unknown) => T) =>
        Promise.resolve(response()).then(resolve, reject),
    };
    return chain;
  });

  return {
    from,
    queries,
    responses,
    states,
    get runEffects() {
      return runEffects;
    },
    set runEffects(value: boolean) {
      runEffects = value;
    },
  };
});

vi.mock("react", () => ({
  useCallback: <T,>(callback: T) => callback,
  useEffect: (effect: () => void | (() => void)) => {
    if (mockedMonthLoad.runEffects) void effect();
  },
  useRef: <T,>(current: T) => ({ current }),
  useState: <T,>(initial: T) => [
    initial,
    (next: T | ((previous: T) => T)) => {
      const previous = (mockedMonthLoad.states.at(-1) as T | undefined) ?? initial;
      mockedMonthLoad.states.push(
        typeof next === "function" ? (next as (previous: T) => T)(previous) : next,
      );
    },
  ],
}));

vi.mock("../src/lib/supabase", () => ({
  supabase: { from: mockedMonthLoad.from },
}));

import {
  discardOtherMonth,
  useMonth,
  type MonthData,
  type MonthState,
} from "../src/data/useMonth";
import { weightedServiceTime } from "../src/lib/monthly";

async function waitForMonthLoad(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  mockedMonthLoad.runEffects = false;
  mockedMonthLoad.queries.length = 0;
  mockedMonthLoad.responses.clear();
  mockedMonthLoad.states.length = 0;
  mockedMonthLoad.from.mockClear();
});

function conMes(month: string): MonthData {
  return {
    month,
    restaurants: [],
    windowDays: [],
    trendDays: [],
    trendMonths: [],
    prior: new Map(),
    targets: new Map(),
    hours: new Map(),
    costParams: [],
    pctTargets: [],
    plActuals: [],
    closingProjections: [],
    national: new Map(),
    objectives: new Map(),
    officialTimes: new Map(),
    officialTimeSnapshots: new Map(),
    windowEnd: null,
    earliestMonth: null,
    importedAt: null,
  };
}

describe("discardOtherMonth", () => {
  it("tira lo cargado cuando es de otro mes", () => {
    // Si no, al pulsar la flecha se verían las cifras de julio bajo la cabecera
    // de junio hasta que llegase la respuesta.
    const previo: MonthState = { data: conMes("2026-07"), loading: false, error: null };
    const siguiente = discardOtherMonth(previo, "2026-06");
    expect(siguiente.data).toBeNull();
    expect(siguiente.loading).toBe(true);
  });

  it("conserva lo cargado si es del mes pedido", () => {
    const previo: MonthState = { data: conMes("2026-07"), loading: false, error: null };
    expect(discardOtherMonth(previo, "2026-07")).toBe(previo);
  });

  it("limpia el error del mes anterior aunque no hubiera datos", () => {
    // Un fallo de red en junio dejaba su mensaje clavado en pantalla mientras
    // julio cargaba bien: se leía "no se han podido cargar los datos" de un mes
    // que sí estaba cargando.
    const previo: MonthState = { data: null, loading: false, error: "sin red" };
    const siguiente = discardOtherMonth(previo, "2026-07");
    expect(siguiente.error).toBeNull();
    expect(siguiente.loading).toBe(true);
  });

  it("no toca un estado inicial limpio", () => {
    const previo: MonthState = { data: null, loading: true, error: null };
    expect(discardOtherMonth(previo, "2026-07")).toBe(previo);
  });
});

describe("contrato público neutral del mes", () => {
  it("descarta todo el grupo workforce si mezcla cohortes", async () => {
    mockedMonthLoad.responses.set("workforce_projection_hourly", {
      data: [
        {
          restaurant_id: "R001",
          sales_date: "2035-01-02",
          hour: 8,
          sales: 80,
          guest_counts: 8,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
        {
          restaurant_id: "R001",
          sales_date: "2035-01-02",
          hour: 9,
          sales: 90,
          guest_counts: 9,
          fetched_at: "2035-01-02T09:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedMonthLoad.responses.set("workforce_staffing_hourly", {
      data: [
        {
          restaurant_id: "R001",
          sales_date: "2035-01-02",
          hour: 8,
          crew_clocked_minutes: 120,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
        {
          restaurant_id: "R001",
          sales_date: "2035-01-02",
          hour: 9,
          crew_clocked_minutes: 240,
          fetched_at: "2035-01-02T09:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedMonthLoad.runEffects = true;

    useMonth("2035-01", "2035-01-02");
    await waitForMonthLoad();

    const workforceQueries = mockedMonthLoad.queries.filter((query) =>
      query.table.startsWith("workforce_"),
    );
    expect(workforceQueries.every((query) => query.selects[0]?.includes("fetched_at"))).toBe(true);
    const final = mockedMonthLoad.states.at(-1) as { data: MonthData | null };
    expect(final.data?.targets.has("R001|2035-01-02")).toBe(false);
    expect(final.data?.hours.has("R001|2035-01-02")).toBe(false);
  });

  it("no agrega una cohorte workforce única que omite una hora esperada", async () => {
    mockedMonthLoad.responses.set("workforce_projection_hourly", {
      data: [
        {
          restaurant_id: "R001",
          sales_date: "2035-01-02",
          hour: 8,
          sales: 80,
          guest_counts: 8,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedMonthLoad.responses.set("workforce_staffing_hourly", {
      data: [
        {
          restaurant_id: "R001",
          sales_date: "2035-01-02",
          hour: 8,
          crew_clocked_minutes: 120,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedMonthLoad.runEffects = true;

    useMonth("2035-01", "2035-01-02");
    await waitForMonthLoad();

    const workforceQueries = mockedMonthLoad.queries.filter((query) =>
      query.table.startsWith("workforce_"),
    );
    expect(workforceQueries.every((query) => query.selects[0]?.includes("expected_hours"))).toBe(
      true,
    );
    const final = mockedMonthLoad.states.at(-1) as { data: MonthData | null };
    expect(final.data?.targets.has("R001|2035-01-02")).toBe(false);
    expect(final.data?.hours.has("R001|2035-01-02")).toBe(false);
  });

  it("transporta calidad y mantiene indisponible un tiempo nulo con GC positivo", async () => {
    mockedMonthLoad.responses.set("sales_daily_totals", {
      data: [
        {
          restaurant_id: "R001",
          sales_date: "2026-08-19",
          hourly_net_sum: 100,
          gc: 10,
          kvs: null,
          r2p: null,
          oepe: null,
          source: "live",
          quality: "clean",
        },
      ],
      error: null,
    });
    mockedMonthLoad.runEffects = true;

    useMonth("2026-08", "2026-08-19");
    await waitForMonthLoad();

    const dailyQuery = mockedMonthLoad.queries.find(
      (query) =>
        query.table === "sales_daily_totals" &&
        query.selects[0]?.includes("hourly_net_sum"),
    );
    expect(dailyQuery?.selects[0]).toContain("quality");
    const final = mockedMonthLoad.states.at(-1) as { data: MonthData | null };
    expect(final.data?.windowDays[0]?.quality).toBe("clean");
    expect(weightedServiceTime(final.data?.windowDays ?? [], "kvs")).toMatchObject({
      value: null,
      unavailable: 1,
    });
  });

  it("consume el contrato mensual público sin depender de metadatos privados", async () => {
    mockedMonthLoad.responses.set("monthly_snapshots", {
      data: [
        {
          restaurant_id: "R001",
          year: 2026,
          month: 8,
          covers_through: "2026-08-19",
          net_sales: 1000,
          labor_cost: 200,
          captured_at: "2026-08-20T05:01:00Z",
        },
      ],
      error: null,
    });
    mockedMonthLoad.runEffects = true;

    useMonth("2026-08", "2026-08-19");
    await waitForMonthLoad();

    expect(mockedMonthLoad.queries.find((query) => query.table === "monthly_snapshots")).toMatchObject(
      {
        selects: [
          "restaurant_id,year,month,covers_through,net_sales,labor_cost",
        ],
        filters: [
          ["eq", "year", 2026],
          ["eq", "month", 8],
        ],
      },
    );
    const final = mockedMonthLoad.states.at(-1) as { data: MonthData | null };
    expect(final.data?.plActuals).toEqual([
      {
        restaurant_id: "R001",
        year: 2026,
        month: 8,
        net_sales_eur: 1000,
        total_labor_eur: 200,
      },
    ]);
    expect(final.data?.importedAt).toBeNull();
    expect(new Set(mockedMonthLoad.queries.map((query) => query.table))).toEqual(
      new Set([
        "restaurants",
        "sales_daily_totals",
        "workforce_projection_hourly",
        "workforce_staffing_hourly",
        "monthly_snapshots",
      ]),
    );
  });

  it("propaga el error de monthly_snapshots", async () => {
    mockedMonthLoad.responses.set("monthly_snapshots", {
      data: null,
      error: {
        message: ["https:/", "/private.example?", "to", "ken=SECRET\n", "PERSON-ID-123"].join(""),
      },
    });
    mockedMonthLoad.runEffects = true;

    useMonth("2026-08", "2026-08-19");
    await waitForMonthLoad();

    expect((mockedMonthLoad.states.at(-1) as { error: string }).error).toBe(
      "no se pudieron cargar los datos del mes",
    );
  });
});
