import type { SupabaseClient } from "@supabase/supabase-js";

export interface MonthlySnapshot {
  restaurantId: string;
  year: number;
  month: number;
  coversThrough: string;
  netSales: number;
  laborCost: number;
}

export interface MonthlySource {
  readMonth(year: number, month: number): Promise<MonthlySnapshot[]>;
}

interface MonthlySnapshotRow {
  restaurant_id: string;
  year: number;
  month: number;
  covers_through: string;
  net_sales: number;
  labor_cost: number;
}

export function createSupabaseMonthlySource(client: SupabaseClient): MonthlySource {
  return {
    async readMonth(year, month) {
      const { data, error } = await client
        .from("monthly_snapshots")
        .select("restaurant_id,year,month,covers_through,net_sales,labor_cost")
        .eq("year", year)
        .eq("month", month)
        .order("covers_through", { ascending: false });

      if (error) throw new Error(error.message);

      return ((data ?? []) as MonthlySnapshotRow[]).map((row) => ({
        restaurantId: row.restaurant_id,
        year: row.year,
        month: row.month,
        coversThrough: row.covers_through,
        netSales: row.net_sales,
        laborCost: row.labor_cost,
      }));
    },
  };
}
