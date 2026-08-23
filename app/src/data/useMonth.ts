/** Carga mensual desde las tablas neutrales protegidas por RLS. */

import { useCallback, useEffect, useRef, useState } from "react";

import {
  addMonths,
  daysBetween,
  firstDayOfMonth,
  monthRange,
  monthWindowEndFor,
  priorYearDay,
  type MonthKey,
} from "../lib/month";
import type {
  CostParamsRow,
  HoursRow,
  MonthDayRow,
  MonthProjectionRow,
  NationalComparable,
  PctTargetRow,
  PlLaborActualRow,
  PriorDayRow,
  ProjectionRow,
} from "../lib/monthly";
import {
  createSupabaseMonthlySource,
  type MonthlySnapshot,
} from "../lib/monthlySource";
import { pageAll } from "../lib/pageAll";
import { withRetry } from "../lib/retry";
import type { OfficialMonthlyTime } from "../lib/serviceBands";
import { supabase } from "../lib/supabase";
import type {
  DaySource,
  Objectives,
  Restaurant,
  DailyQuality,
} from "../lib/types";
import { latestWorkforceCohort } from "./workforceCohort";

export const TREND_MONTHS = 13;

export interface MonthDayWithSource extends MonthDayRow {
  source: DaySource;
}

export interface MonthData {
  month: MonthKey;
  restaurants: Restaurant[];
  windowDays: MonthDayWithSource[];
  trendDays: MonthDayRow[];
  trendMonths: MonthKey[];
  prior: Map<string, PriorDayRow>;
  targets: Map<string, ProjectionRow>;
  hours: Map<string, HoursRow>;
  costParams: CostParamsRow[];
  pctTargets: PctTargetRow[];
  plActuals: PlLaborActualRow[];
  closingProjections: MonthProjectionRow[];
  national: Map<MonthKey, NationalComparable>;
  objectives: Map<string, Map<MonthKey, Objectives>>;
  officialTimes: Map<string, Map<MonthKey, OfficialMonthlyTime>>;
  officialTimeSnapshots: Map<
    string,
    Map<string, { r2p: number | null; oepe: number | null }>
  >;
  windowEnd: string | null;
  earliestMonth: MonthKey | null;
  importedAt: string | null;
}

export interface MonthState {
  data: MonthData | null;
  loading: boolean;
  error: string | null;
}

interface RestaurantRow {
  id: string;
  name: string;
  sort_order: number;
  has_drive_through: boolean;
}

interface DailyRow {
  restaurant_id: string;
  sales_date: string;
  hourly_net_sum: number;
  gc: number | null;
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
  source: DaySource;
  quality: DailyQuality;
}

interface ProjectionHourlyRow {
  restaurant_id: string;
  sales_date: string;
  hour: number;
  sales: number;
  guest_counts: number;
  fetched_at: string;
  expected_hours: number[];
}

interface StaffingHourlyRow {
  restaurant_id: string;
  sales_date: string;
  hour: number;
  crew_clocked_minutes: number | null;
  fetched_at: string;
  expected_hours: number[];
}

export function discardOtherMonth(prev: MonthState, month: MonthKey): MonthState {
  if (prev.data === null && prev.error === null) return prev;
  if (prev.data?.month === month && prev.error === null) return prev;
  return { data: null, loading: true, error: null };
}

function restaurant(row: RestaurantRow): Restaurant {
  return {
    id: row.id,
    name: row.name,
    sort_order: row.sort_order,
    has_drive_through: row.has_drive_through,
  };
}

function aggregateProjections(rows: ProjectionHourlyRow[]): Map<string, ProjectionRow> {
  const totals = new Map<string, ProjectionRow>();
  for (const row of rows) {
    const key = `${row.restaurant_id}|${row.sales_date}`;
    const current = totals.get(key) ?? {
      restaurant_id: row.restaurant_id,
      sales_date: row.sales_date,
      projected_net: 0,
      projected_gc: 0,
    };
    current.projected_net = (current.projected_net ?? 0) + row.sales;
    current.projected_gc = (current.projected_gc ?? 0) + row.guest_counts;
    totals.set(key, current);
  }
  return totals;
}

function aggregateHours(rows: StaffingHourlyRow[]): Map<string, HoursRow> {
  const totals = new Map<
    string,
    { restaurant_id: string; sales_date: string; minutes: number; incomplete: boolean }
  >();
  for (const row of rows) {
    const key = `${row.restaurant_id}|${row.sales_date}`;
    const current = totals.get(key) ?? {
      restaurant_id: row.restaurant_id,
      sales_date: row.sales_date,
      minutes: 0,
      incomplete: false,
    };
    if (row.crew_clocked_minutes === null) current.incomplete = true;
    else current.minutes += row.crew_clocked_minutes;
    totals.set(key, current);
  }
  return new Map(
    [...totals].map(([key, row]) => [
      key,
      {
        restaurant_id: row.restaurant_id,
        sales_date: row.sales_date,
        clocked_hours: row.incomplete ? null : row.minutes / 60,
      },
    ]),
  );
}

function latestSnapshots(rows: MonthlySnapshot[]): MonthlySnapshot[] {
  const latest = new Map<string, MonthlySnapshot>();
  for (const row of rows) {
    const current = latest.get(row.restaurantId);
    if (!current || row.coversThrough > current.coversThrough) {
      latest.set(row.restaurantId, row);
    }
  }
  return [...latest.values()];
}

export function useMonth(
  month: MonthKey,
  lastClosedDay: string,
): MonthState & { refresh: () => void } {
  const [state, setState] = useState<MonthState>({ data: null, loading: true, error: null });
  const currentRequest = useRef(`${month}|${lastClosedDay}`);

  const load = useCallback(async () => {
    const request = `${month}|${lastClosedDay}`;
    currentRequest.current = request;
    setState((prev) => discardOtherMonth(prev, month));

    const start = firstDayOfMonth(month);
    const end = monthWindowEndFor(month, lastClosedDay);
    const queryEnd = end ?? start;
    const firstTrendMonth = addMonths(month, -(TREND_MONTHS - 1));
    const trendStart = firstDayOfMonth(firstTrendMonth);
    const priorStart = priorYearDay(start);
    const priorEnd = priorYearDay(queryEnd);
    const dailyStart = trendStart < priorStart ? trendStart : priorStart;
    const year = Number(month.slice(0, 4));
    const monthNumber = Number(month.slice(5, 7));

    try {
      const monthlySource = createSupabaseMonthlySource(supabase);
      const [restaurants, days, projections, staffing, snapshots, earliest] =
        await Promise.all([
          withRetry(() =>
            supabase
              .from("restaurants")
              .select("id,name,sort_order,has_drive_through")
              .order("sort_order"),
          ),
          pageAll((from, to) =>
            supabase
              .from("sales_daily_totals")
              .select(
                "restaurant_id,sales_date,hourly_net_sum,gc,kvs,r2p,oepe,source,quality",
              )
              .gte("sales_date", dailyStart)
              .lte("sales_date", queryEnd)
              .order("sales_date")
              .order("restaurant_id")
              .range(from, to),
          ),
          pageAll((from, to) =>
            supabase
              .from("workforce_projection_hourly")
              .select(
                "restaurant_id,sales_date,hour,sales,guest_counts,fetched_at,expected_hours",
              )
              .gte("sales_date", start)
              .lte("sales_date", queryEnd)
              .order("sales_date")
              .order("restaurant_id")
              .order("hour")
              .range(from, to),
          ),
          pageAll((from, to) =>
            supabase
              .from("workforce_staffing_hourly")
              .select(
                "restaurant_id,sales_date,hour,crew_clocked_minutes,fetched_at,expected_hours",
              )
              .gte("sales_date", priorStart)
              .lte("sales_date", queryEnd)
              .order("sales_date")
              .order("restaurant_id")
              .order("hour")
              .range(from, to),
          ),
          monthlySource.readMonth(year, monthNumber),
          withRetry(() =>
            supabase
              .from("sales_daily_totals")
              .select("sales_date")
              .order("sales_date", { ascending: true })
              .limit(1),
          ),
        ]);

      const failed = [restaurants, days, projections, staffing, earliest].find(
        (response) => response.error,
      );
      if (failed?.error) throw new Error(failed.error.message ?? "error al leer el mes");
      if (currentRequest.current !== request) return;

      const allDays = (days.data ?? []) as DailyRow[];
      const monthDays: MonthDayWithSource[] = allDays.map((row) => ({
        restaurant_id: row.restaurant_id,
        sales_date: row.sales_date,
        hourly_net_sum: row.hourly_net_sum,
        gc: row.gc,
        kvs: row.kvs,
        r2p: row.r2p,
        oepe: row.oepe,
        service_time_gc: row.gc,
        source: row.source,
        quality: row.quality,
      }));
      const window = end === null ? new Set<string>() : new Set(daysBetween(start, end));
      const windowDays = monthDays.filter((row) => window.has(row.sales_date));
      const trendDays = monthDays.filter((row) => row.sales_date >= trendStart);
      const prior = new Map<string, PriorDayRow>();
      for (const row of allDays) {
        if (row.sales_date < priorStart || row.sales_date > priorEnd) continue;
        prior.set(`${row.restaurant_id}|${row.sales_date}`, {
          restaurant_id: row.restaurant_id,
          sales_date: row.sales_date,
          net: row.hourly_net_sum,
          gc: row.gc,
        });
      }

      const snapshotRows = latestSnapshots(
        snapshots.filter(
          (snapshot) =>
            snapshot.coversThrough >= start && snapshot.coversThrough <= queryEnd,
        ),
      );
      // La interfaz actual trata `plActuals` como un cierre completo. Un
      // snapshot anterior al corte no puede ocupar ese hueco: sería publicar
      // un acumulado parcial como si fuera todo el periodo.
      const plActuals: PlLaborActualRow[] = snapshotRows
        .filter((row) => row.coversThrough === queryEnd)
        .map((row) => ({
          restaurant_id: row.restaurantId,
          year: row.year,
          month: row.month,
          total_labor_eur: row.laborCost,
          net_sales_eur: row.netSales,
        }));
      const firstDay = ((earliest.data ?? [])[0] as { sales_date: string } | undefined)
        ?.sales_date;

      setState({
        data: {
          month,
          restaurants: ((restaurants.data ?? []) as RestaurantRow[]).map(restaurant),
          windowDays,
          trendDays,
          trendMonths: monthRange(firstTrendMonth, month),
          prior,
          targets: aggregateProjections(
            latestWorkforceCohort((projections.data ?? []) as ProjectionHourlyRow[]),
          ),
          hours: aggregateHours(
            latestWorkforceCohort((staffing.data ?? []) as StaffingHourlyRow[]),
          ),
          costParams: [],
          pctTargets: [],
          plActuals,
          closingProjections: [],
          national: new Map(),
          objectives: new Map(),
          officialTimes: new Map(),
          officialTimeSnapshots: new Map(),
          windowEnd: end,
          earliestMonth: firstDay ? firstDay.slice(0, 7) : null,
          importedAt: null,
        },
        loading: false,
        error: null,
      });
    } catch {
      if (currentRequest.current !== request) return;
      setState((prev) => ({
        data: prev.data,
        loading: false,
        error: "no se pudieron cargar los datos del mes",
      }));
    }
  }, [month, lastClosedDay]);

  useEffect(() => {
    void load();
  }, [load]);

  return { ...state, refresh: () => void load() };
}
