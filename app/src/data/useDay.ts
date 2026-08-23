/** Carga de un día desde el contrato público neutral de Supabase. */

import { useCallback, useEffect, useState } from "react";
import type { SupabaseClient } from "@supabase/supabase-js";

import { sortByBusinessDay } from "../lib/businessDay";
import { priorYearDay } from "../lib/month";
import { pageAll } from "../lib/pageAll";
import { dayProvenance } from "../lib/provenance";
import { withRetry } from "../lib/retry";
import { supabase } from "../lib/supabase";
import { businessTodayMadrid } from "../lib/tz";
import type {
  DayProvenance,
  DaySource,
  HourRow,
  IngestRun,
  Objectives,
  Restaurant,
  ServiceTimes,
  DailyQuality,
  DailyStatus,
} from "../lib/types";
import { latestWorkforceCohort } from "./workforceCohort";

const REFRESH_MS = 60_000;

export interface PriorDay {
  net: number | null;
  gc: number | null;
}

export interface LiveDay {
  restaurants: Restaurant[];
  hoursByRestaurant: Map<string, HourRow[]>;
  objectivesByRestaurant: Map<string, Objectives>;
  serviceTimesByRestaurant: Map<string, ServiceTimes>;
  dailyStatusByRestaurant: Map<string, DailyStatus>;
  priorByRestaurant: Map<string, PriorDay>;
  runs: IngestRun[];
  salesDate: string;
  provenance: DayProvenance | null;
  earliestDate: string | null;
  nationalYoy: number | null;
}

export interface State {
  data: LiveDay | null;
  loading: boolean;
  error: string | null;
}

export function discardOtherDay(prev: State, salesDate: string): State {
  if (prev.data === null || prev.data.salesDate === salesDate) return prev;
  return { data: null, loading: true, error: null };
}

interface RestaurantRow {
  id: string;
  name: string;
  sort_order: number;
  has_drive_through: boolean;
}

export interface SalesRow {
  restaurant_id: string;
  source_date: string;
  calendar_date: string;
  hour: number;
  fold: number;
  captured_at: string;
  net: number | null;
  gc: number | null;
  drive_through_net: number | null;
  drive_through_cars: number | null;
  delivery_net: number | null;
  delivery_count: number | null;
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
}

const SALES_ROW_COLUMNS =
  "restaurant_id,source_date,calendar_date,hour,fold,captured_at,net,gc,drive_through_net,drive_through_cars,delivery_net,delivery_count,kvs,r2p,oepe";

/** Consulta compartida por el hook y la integración local DB→frontend. */
export function salesRowsQuery(client: SupabaseClient, salesDate: string) {
  return client.from("sales_hourly").select(SALES_ROW_COLUMNS).eq("sales_date", salesDate);
}

function completeSum(
  rows: SalesRow[],
  value: (row: SalesRow) => number | null,
): number | null {
  const values = rows.map(value);
  return values.some((item) => item === null)
    ? null
    : values.reduce<number>((total, item) => total + (item ?? 0), 0);
}

function effectiveSalesRows(rows: SalesRow[]): SalesRow[] {
  const physical = new Map<string, SalesRow>();
  for (const row of rows) {
    const key = `${row.restaurant_id}|${row.calendar_date}|${row.hour}|${row.fold}`;
    const current = physical.get(key);
    if (
      !current ||
      row.captured_at > current.captured_at ||
      (row.captured_at === current.captured_at && row.source_date > current.source_date)
    ) {
      physical.set(key, row);
    }
  }
  return [...physical.values()];
}

export interface ProjRow {
  restaurant_id: string;
  hour: number;
  sales: number | null;
  guest_counts: number | null;
  fetched_at: string;
  expected_hours: number[];
}

export interface StaffRow {
  restaurant_id: string;
  hour: number;
  crew_clocked_count: number | null;
  crew_assigned_count: number | null;
  crew_open_anomalies: number | null;
  fetched_at: string;
  expected_hours: number[];
}

export interface DailyTotalsRow {
  restaurant_id: string;
  sales_date: string;
  hourly_net_sum: number;
  gc: number | null;
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
  source: DaySource;
  quality: DailyQuality;
  captured_at: string;
}

export function dailyStatuses(rows: DailyTotalsRow[]): Map<string, DailyStatus> {
  return new Map(
    rows.map((row) => [
      row.restaurant_id,
      {
        restaurantId: row.restaurant_id,
        capturedAt: row.captured_at,
        source: row.source,
        quality: row.quality,
        contributingCaptures: 1,
      },
    ]),
  );
}

export function serviceTimes(rows: DailyTotalsRow[]): Map<string, ServiceTimes> {
  const result = new Map<string, ServiceTimes>();
  for (const row of rows) {
    if (result.has(row.restaurant_id)) continue;
    result.set(row.restaurant_id, { kvs: row.kvs, r2p: row.r2p, oepe: row.oepe });
  }
  return result;
}

/** Cruza venta, previsión y personal en una fila por hora y restaurante. */
export function combine(
  sales: SalesRow[],
  projections: ProjRow[],
  staffing: StaffRow[],
): Map<string, HourRow[]> {
  const byRestaurant = new Map<string, Map<number, HourRow>>();

  const ensure = (id: string, hour: number): HourRow => {
    let hours = byRestaurant.get(id);
    if (!hours) {
      hours = new Map();
      byRestaurant.set(id, hours);
    }
    let row = hours.get(hour);
    if (!row) {
      row = {
        hour,
        net: null,
        gc: null,
        drive_through_net: null,
        drive_through_cars: null,
        delivery_net: null,
        delivery_count: null,
        kvs: null,
        r2p: null,
        oepe: null,
        proj_sales: null,
        proj_gc: null,
        clocked: null,
        assigned: null,
        clipped: null,
      };
      hours.set(hour, row);
    }
    return row;
  };

  const visualSales = new Map<string, SalesRow[]>();
  for (const sale of effectiveSalesRows(sales)) {
    const key = `${sale.restaurant_id}|${sale.hour}`;
    const grouped = visualSales.get(key);
    if (grouped) grouped.push(sale);
    else visualSales.set(key, [sale]);
  }
  for (const grouped of visualSales.values()) {
    const first = grouped[0];
    if (!first) continue;
    const row = ensure(first.restaurant_id, first.hour);
    row.net = completeSum(grouped, (sale) => sale.net);
    row.gc = completeSum(grouped, (sale) => sale.gc);
    row.drive_through_net = completeSum(grouped, (sale) => sale.drive_through_net);
    row.drive_through_cars = completeSum(grouped, (sale) => sale.drive_through_cars);
    row.delivery_net = completeSum(grouped, (sale) => sale.delivery_net);
    row.delivery_count = completeSum(grouped, (sale) => sale.delivery_count);
    // Los tiempos no son aditivos y la fuente no publica sus pesos por fold.
    // Una hora visual repetida conserva venta/canales, pero no inventa media.
    row.kvs = grouped.length === 1 ? first.kvs : null;
    row.r2p = grouped.length === 1 ? first.r2p : null;
    row.oepe = grouped.length === 1 ? first.oepe : null;
  }
  for (const projection of projections) {
    const row = ensure(projection.restaurant_id, projection.hour);
    row.proj_sales = projection.sales;
    row.proj_gc = projection.guest_counts;
  }
  for (const staff of staffing) {
    const row = ensure(staff.restaurant_id, staff.hour);
    row.clocked = staff.crew_clocked_count;
    row.assigned = staff.crew_assigned_count;
    row.clipped = staff.crew_open_anomalies;
  }

  return new Map(
    [...byRestaurant].map(([id, hours]) => [
      id,
      sortByBusinessDay([...hours.values()]),
    ]),
  );
}

function restaurant(row: RestaurantRow): Restaurant {
  return {
    id: row.id,
    name: row.name,
    sort_order: row.sort_order,
    has_drive_through: row.has_drive_through,
  };
}

export function useDay(salesDate: string): State & { refresh: () => void } {
  const [state, setState] = useState<State>({ data: null, loading: true, error: null });

  const load = useCallback(async () => {
    setState((prev) => discardOtherDay(prev, salesDate));
    const priorDate = priorYearDay(salesDate);

    try {
      const [restaurants, sales, projections, staffing, totals, runs, prior, earliest] =
        await Promise.all([
          withRetry(() =>
            supabase
              .from("restaurants")
              .select("id,name,sort_order,has_drive_through")
              .order("sort_order"),
          ),
          withRetry(() => salesRowsQuery(supabase, salesDate)),
          withRetry(() =>
            supabase
              .from("workforce_projection_hourly")
              .select("restaurant_id,hour,sales,guest_counts,fetched_at,expected_hours")
              .eq("sales_date", salesDate),
          ),
          withRetry(() =>
            supabase
              .from("workforce_staffing_hourly")
              .select(
                "restaurant_id,hour,crew_clocked_count,crew_assigned_count,crew_open_anomalies,fetched_at,expected_hours",
              )
              .eq("sales_date", salesDate),
          ),
          withRetry(() =>
            supabase
              .from("sales_daily_totals")
              .select(
                "restaurant_id,sales_date,hourly_net_sum,gc,kvs,r2p,oepe,source,quality,captured_at",
              )
              .eq("sales_date", salesDate),
          ),
          pageAll((from, to) =>
            supabase
              .from("ingest_runs")
              .select(
                "id,restaurant_id,source,started_at,finished_at,status,rows_written",
              )
              .eq("source", "sales")
              .order("started_at", { ascending: false })
              .order("id", { ascending: false })
              .range(from, to),
          ),
          withRetry(() =>
            supabase
              .from("sales_daily_totals")
              .select("restaurant_id,hourly_net_sum,gc")
              .eq("sales_date", priorDate),
          ),
          withRetry(() =>
            supabase
              .from("sales_daily_totals")
              .select("sales_date")
              .order("sales_date", { ascending: true })
              .limit(1),
          ),
        ]);

      const failed = [restaurants, sales, projections, staffing, totals, runs, prior, earliest].find(
        (response) => response.error,
      );
      if (failed?.error) throw new Error(failed.error.message);

      const restaurantRows = (restaurants.data ?? []) as RestaurantRow[];
      const visibleRestaurants = restaurantRows.map(restaurant);
      const totalRows = (totals.data ?? []) as DailyTotalsRow[];
      const statuses = dailyStatuses(totalRows);
      const priorByRestaurant = new Map<string, PriorDay>();
      for (const row of (prior.data ?? []) as Array<{
        restaurant_id: string;
        hourly_net_sum: number | null;
        gc: number | null;
      }>) {
        priorByRestaurant.set(row.restaurant_id, { net: row.hourly_net_sum, gc: row.gc });
      }

      setState({
        data: {
          restaurants: visibleRestaurants,
          hoursByRestaurant: combine(
            (sales.data ?? []) as SalesRow[],
            latestWorkforceCohort((projections.data ?? []) as ProjRow[]),
            latestWorkforceCohort((staffing.data ?? []) as StaffRow[]),
          ),
          objectivesByRestaurant: new Map(),
          serviceTimesByRestaurant: serviceTimes(totalRows),
          dailyStatusByRestaurant: statuses,
          priorByRestaurant,
          runs: ((runs.data ?? []) as Array<Omit<IngestRun, "error">>).map((run) => ({
            ...run,
            error: run.status === "error" ? "actualización no disponible" : null,
          })),
          salesDate,
          provenance: dayProvenance(visibleRestaurants, statuses),
          earliestDate:
            ((earliest.data ?? [])[0] as { sales_date: string } | undefined)?.sales_date ?? null,
          nationalYoy: null,
        },
        loading: false,
        error: null,
      });
    } catch {
      setState((prev) => ({
        data: prev.data,
        loading: false,
        error: "no se pudieron cargar los datos del día",
      }));
    }
  }, [salesDate]);

  useEffect(() => {
    void load();
    if (salesDate !== businessTodayMadrid()) return;

    const id = setInterval(() => void load(), REFRESH_MS);
    const onVisible = () => {
      if (document.visibilityState === "visible") void load();
    };
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [load, salesDate]);

  return { ...state, refresh: () => void load() };
}
