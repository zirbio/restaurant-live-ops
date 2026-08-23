import type { SupabaseClient } from "@supabase/supabase-js";
import { describe, expect, it, vi } from "vitest";

import { createSupabaseMonthlySource } from "../src/lib/monthlySource";

interface Response {
  data: unknown[] | null;
  error: { message: string } | null;
}

function clientFor(response: Response) {
  const filters: Array<[string, string, unknown]> = [];
  const select = vi.fn();
  const query = {
    select: (columns: string) => {
      select(columns);
      return query;
    },
    eq: (column: string, value: unknown) => {
      filters.push(["eq", column, value]);
      return query;
    },
    order: () => query,
    then: <T>(resolve: (value: Response) => T, reject?: (reason: unknown) => T) =>
      Promise.resolve(response).then(resolve, reject),
  };
  const from = vi.fn(() => query);
  const client = { from } as unknown as SupabaseClient;
  return { client, filters, from, select };
}

describe("SupabaseMonthlySource", () => {
  it("maps the public monthly snapshot contract", async () => {
    const fake = clientFor({
      data: [
        {
          restaurant_id: "R001",
          year: 2030,
          month: 1,
          covers_through: "2030-01-31",
          net_sales: 10_000,
          labor_cost: 2_500,
        },
      ],
      error: null,
    });

    const snapshots = await createSupabaseMonthlySource(fake.client).readMonth(2030, 1);

    expect(fake.from).toHaveBeenCalledOnce();
    expect(fake.from).toHaveBeenCalledWith("monthly_snapshots");
    expect(fake.select).toHaveBeenCalledWith(
      "restaurant_id,year,month,covers_through,net_sales,labor_cost",
    );
    expect(fake.filters).toEqual([
      ["eq", "year", 2030],
      ["eq", "month", 1],
    ]);
    expect(snapshots).toEqual([
      {
        restaurantId: "R001",
        year: 2030,
        month: 1,
        coversThrough: "2030-01-31",
        netSales: 10_000,
        laborCost: 2_500,
      },
    ]);
  });

  it("surfaces source errors instead of returning missing data", async () => {
    const fake = clientFor({ data: null, error: { message: "monthly source unavailable" } });

    await expect(createSupabaseMonthlySource(fake.client).readMonth(2030, 1)).rejects.toThrow(
      "monthly source unavailable",
    );
  });
});
