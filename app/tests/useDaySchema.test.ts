import { afterEach, describe, expect, it, vi } from "vitest";

const mockedDayLoad = vi.hoisted(() => {
  type Response = { data: unknown[] | null; error: { message: string } | null };
  type Query = {
    table: string;
    selects: string[];
    filters: Array<[string, string, unknown]>;
    orders: Array<[string, { ascending?: boolean } | undefined]>;
  };

  const queries: Query[] = [];
  const responses = new Map<string, Response>();
  const states: unknown[] = [];
  let runEffects = false;

  const from = vi.fn((table: string) => {
    const query: Query = { table, selects: [], filters: [], orders: [] };
    queries.push(query);
    const response = (): Response => responses.get(table) ?? { data: [], error: null };
    const chain = {
      select: (columns: string) => {
        query.selects.push(columns);
        return chain;
      },
      eq: (column: string, value: unknown) => {
        query.filters.push(["eq", column, value]);
        return chain;
      },
      order: (column: string, options?: { ascending?: boolean }) => {
        query.orders.push([column, options]);
        return chain;
      },
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
    if (mockedDayLoad.runEffects) void effect();
  },
  useState: <T,>(initial: T) => [
    initial,
    (next: T | ((previous: T) => T)) => {
      const previous = (mockedDayLoad.states.at(-1) as T | undefined) ?? initial;
      mockedDayLoad.states.push(
        typeof next === "function" ? (next as (previous: T) => T)(previous) : next,
      );
    },
  ],
}));

vi.mock("../src/lib/supabase", () => ({
  supabase: { from: mockedDayLoad.from },
}));

import { useDay, type LiveDay } from "../src/data/useDay";
import { buildIngestRunFreshness } from "../src/lib/sourceFreshness";

async function waitForDayLoad(): Promise<void> {
  await new Promise((resolve) => setTimeout(resolve, 0));
}

afterEach(() => {
  mockedDayLoad.runEffects = false;
  mockedDayLoad.queries.length = 0;
  mockedDayLoad.responses.clear();
  mockedDayLoad.states.length = 0;
  mockedDayLoad.from.mockClear();
});

describe("contrato público neutral del día", () => {
  it("descarta todo el grupo workforce si mezcla cohortes", async () => {
    mockedDayLoad.responses.set("restaurants", {
      data: [
        { id: "R001", name: "Restaurante A", sort_order: 1, has_drive_through: true },
      ],
      error: null,
    });
    mockedDayLoad.responses.set("workforce_projection_hourly", {
      data: [
        {
          restaurant_id: "R001",
          hour: 8,
          sales: 80,
          guest_counts: 8,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
        {
          restaurant_id: "R001",
          hour: 9,
          sales: 90,
          guest_counts: 9,
          fetched_at: "2035-01-02T09:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedDayLoad.responses.set("workforce_staffing_hourly", {
      data: [
        {
          restaurant_id: "R001",
          hour: 8,
          crew_clocked_count: 2,
          crew_assigned_count: 3,
          crew_open_anomalies: 0,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
        {
          restaurant_id: "R001",
          hour: 9,
          crew_clocked_count: 4,
          crew_assigned_count: 5,
          crew_open_anomalies: 0,
          fetched_at: "2035-01-02T09:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedDayLoad.runEffects = true;

    useDay("2035-01-02");
    await waitForDayLoad();

    const workforceQueries = mockedDayLoad.queries.filter((query) =>
      query.table.startsWith("workforce_"),
    );
    expect(workforceQueries.every((query) => query.selects[0]?.includes("fetched_at"))).toBe(true);
    const final = mockedDayLoad.states.at(-1) as { data: LiveDay | null };
    expect(final.data?.hoursByRestaurant.get("R001") ?? []).toEqual([]);
  });

  it("no publica una cohorte workforce única que omite una hora esperada", async () => {
    mockedDayLoad.responses.set("restaurants", {
      data: [
        { id: "R001", name: "Restaurante A", sort_order: 1, has_drive_through: true },
      ],
      error: null,
    });
    mockedDayLoad.responses.set("workforce_projection_hourly", {
      data: [
        {
          restaurant_id: "R001",
          hour: 8,
          sales: 80,
          guest_counts: 8,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedDayLoad.responses.set("workforce_staffing_hourly", {
      data: [
        {
          restaurant_id: "R001",
          hour: 8,
          crew_clocked_count: 2,
          crew_assigned_count: 3,
          crew_open_anomalies: 0,
          fetched_at: "2035-01-02T08:00:00Z",
          expected_hours: [8, 9],
        },
      ],
      error: null,
    });
    mockedDayLoad.runEffects = true;

    useDay("2035-01-02");
    await waitForDayLoad();

    const workforceQueries = mockedDayLoad.queries.filter((query) =>
      query.table.startsWith("workforce_"),
    );
    expect(workforceQueries.every((query) => query.selects[0]?.includes("expected_hours"))).toBe(
      true,
    );
    const final = mockedDayLoad.states.at(-1) as { data: LiveDay | null };
    expect(final.data?.hoursByRestaurant.get("R001") ?? []).toEqual([]);
  });

  it("consulta solo tablas del esquema limpio y adapta drive-through a la UI actual", async () => {
    mockedDayLoad.responses.set("restaurants", {
      data: [
        {
          id: "R001",
          name: "Restaurante A",
          sort_order: 1,
          has_drive_through: true,
        },
      ],
      error: null,
    });
    mockedDayLoad.responses.set("sales_hourly", {
      data: [
        {
          restaurant_id: "R001",
          hour: 14,
          net: 100,
          gc: 10,
          drive_through_net: 40,
          drive_through_cars: 4,
          delivery_net: 15,
          delivery_count: 2,
          kvs: 80,
          r2p: 110,
          oepe: 150,
        },
      ],
      error: null,
    });
    mockedDayLoad.runEffects = true;

    useDay("2026-08-19");
    await waitForDayLoad();

    const tables = new Set(mockedDayLoad.queries.map((query) => query.table));
    expect(tables).toEqual(
      new Set([
        "restaurants",
        "sales_hourly",
        "sales_daily_totals",
        "workforce_projection_hourly",
        "workforce_staffing_hourly",
        "ingest_runs",
      ]),
    );
    const final = mockedDayLoad.states.at(-1) as { data: LiveDay | null };
    expect(final.data?.restaurants[0]?.has_drive_through).toBe(true);
    expect(final.data?.hoursByRestaurant.get("R001")?.[0]?.drive_through_net).toBe(40);
  });

  it("propaga un error de lectura sin publicar una pantalla vacía como válida", async () => {
    mockedDayLoad.responses.set("sales_hourly", {
      data: null,
      error: {
        message: ["https:/", "/private.example?", "to", "ken=SECRET\n", "PERSON-ID-123"].join(""),
      },
    });
    mockedDayLoad.runEffects = true;

    useDay("2026-08-19");
    await waitForDayLoad();

    expect((mockedDayLoad.states.at(-1) as { error: string }).error).toBe(
      "no se pudieron cargar los datos del día",
    );
  });

  it("lleva carryover 06→06 y ambos folds desde Supabase hasta la hora visual", async () => {
    mockedDayLoad.responses.set("restaurants", {
      data: [
        {
          id: "R001",
          name: "Restaurante A",
          sort_order: 1,
          has_drive_through: true,
        },
      ],
      error: null,
    });
    mockedDayLoad.responses.set("sales_hourly", {
      data: [
        {
          restaurant_id: "R001",
          source_date: "2026-10-25",
          calendar_date: "2026-10-25",
          hour: 2,
          fold: 0,
          captured_at: "2026-10-25T01:05:00Z",
          net: 20,
          gc: 2,
          drive_through_net: 8,
          drive_through_cars: 1,
          delivery_net: 4,
          delivery_count: 1,
          kvs: 80,
          r2p: 110,
          oepe: 150,
        },
        {
          restaurant_id: "R001",
          source_date: "2026-10-25",
          calendar_date: "2026-10-25",
          hour: 2,
          fold: 1,
          captured_at: "2026-10-25T02:05:00Z",
          net: 30,
          gc: 3,
          drive_through_net: 12,
          drive_through_cars: 2,
          delivery_net: 6,
          delivery_count: 2,
          kvs: 90,
          r2p: 120,
          oepe: 160,
        },
        {
          restaurant_id: "R001",
          source_date: "2026-10-25",
          calendar_date: "2026-10-26",
          hour: 5,
          fold: 0,
          captured_at: "2026-10-26T04:05:00Z",
          net: 10,
          gc: 1,
          drive_through_net: 0,
          drive_through_cars: 0,
          delivery_net: 0,
          delivery_count: 0,
          kvs: null,
          r2p: null,
          oepe: null,
        },
      ],
      error: null,
    });
    mockedDayLoad.runEffects = true;

    useDay("2026-10-25");
    await waitForDayLoad();

    const salesQuery = mockedDayLoad.queries.find((query) => query.table === "sales_hourly");
    expect(salesQuery?.selects[0]).toContain(
      "source_date,calendar_date,hour,fold,captured_at",
    );
    const final = mockedDayLoad.states.at(-1) as { data: LiveDay | null };
    expect(final.data?.hoursByRestaurant.get("R001")?.map((row) => [row.hour, row.net])).toEqual([
      [2, 50],
      [5, 10],
    ]);
  });

  it("lleva runs ordenados al modelo por local sin ocultar un fallo simultáneo", async () => {
    mockedDayLoad.responses.set("restaurants", {
      data: [
        { id: "R001", name: "Restaurante A", sort_order: 1, has_drive_through: true },
        { id: "R002", name: "Restaurante B", sort_order: 2, has_drive_through: true },
        { id: "R003", name: "Restaurante C", sort_order: 3, has_drive_through: true },
      ],
      error: null,
    });
    mockedDayLoad.responses.set("ingest_runs", {
      data: [
        {
          id: 10,
          restaurant_id: "R001",
          source: "sales",
          started_at: "2026-08-19T10:00:00Z",
          finished_at: "2026-08-19T10:01:00Z",
          status: "ok",
          rows_written: 1,
          error: null,
        },
        {
          id: 11,
          restaurant_id: "R001",
          source: "sales",
          started_at: "2026-08-19T10:00:00Z",
          finished_at: "2026-08-19T10:02:00Z",
          status: "error",
          rows_written: 0,
          error: "captura incompleta",
        },
        {
          id: 20,
          restaurant_id: "R002",
          source: "sales",
          started_at: "2026-08-19T09:58:00Z",
          finished_at: "2026-08-19T09:59:00Z",
          status: "ok",
          rows_written: 1,
          error: null,
        },
        {
          id: 31,
          restaurant_id: "R003",
          source: "sales",
          started_at: "2026-08-19T10:03:00Z",
          finished_at: null,
          status: "running",
          rows_written: 0,
          error: null,
        },
        {
          id: 30,
          restaurant_id: "R003",
          source: "sales",
          started_at: "2026-08-19T09:50:00Z",
          finished_at: "2026-08-19T09:51:00Z",
          status: "ok",
          rows_written: 1,
          error: null,
        },
      ],
      error: null,
    });
    mockedDayLoad.runEffects = true;

    useDay("2026-08-19");
    await waitForDayLoad();

    const runQuery = mockedDayLoad.queries.find((query) => query.table === "ingest_runs");
    expect(runQuery?.selects[0]).toContain("id,");
    expect(runQuery?.selects[0]).not.toContain("error");
    expect(runQuery?.orders).toEqual([
      ["started_at", { ascending: false }],
      ["id", { ascending: false }],
    ]);
    expect(runQuery?.filters).toContainEqual(["eq", "source", "sales"]);
    const final = mockedDayLoad.states.at(-1) as { data: LiveDay | null };
    const model = buildIngestRunFreshness(
      final.data?.restaurants ?? [],
      final.data?.runs ?? [],
      final.data?.dailyStatusByRestaurant ?? new Map(),
    );
    expect(model).toMatchObject({
      bad: true,
      updatedAt: "2026-08-19T09:51:00Z",
      capturingRestaurantNames: ["Restaurante C"],
      issues: [
        {
          restaurantName: "Restaurante A",
          status: "failed",
          reason: "actualización no disponible",
          lastGoodAt: "2026-08-19T10:01:00Z",
        },
      ],
    });
  });
});
