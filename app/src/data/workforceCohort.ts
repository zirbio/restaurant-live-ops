/** Descarta un grupo completo si contiene filas de capturas distintas. */

export interface WorkforceSnapshotRow {
  restaurant_id: string;
  sales_date?: string;
  hour: number;
  fetched_at: string;
  expected_hours: number[];
}

export function latestWorkforceCohort<T extends WorkforceSnapshotRow>(rows: T[]): T[] {
  const cohorts = new Map<
    string,
    {
      timestamps: Set<string>;
      expectationSignatures: Set<string>;
      expected: Set<number> | null;
      actual: Set<number>;
      invalid: boolean;
    }
  >();
  for (const row of rows) {
    const key = `${row.restaurant_id}|${row.sales_date ?? ""}`;
    const cohort = cohorts.get(key) ?? {
      timestamps: new Set<string>(),
      expectationSignatures: new Set<string>(),
      expected: null,
      actual: new Set<number>(),
      invalid: false,
    };
    const expected = row.expected_hours;
    const validExpected =
      Array.isArray(expected) &&
      expected.length > 0 &&
      expected.every((hour) => Number.isInteger(hour) && hour >= 0 && hour <= 23) &&
      new Set(expected).size === expected.length;

    cohort.timestamps.add(row.fetched_at);
    cohort.actual.add(row.hour);
    if (!validExpected) {
      cohort.invalid = true;
    } else {
      const normalized = [...expected].sort((left, right) => left - right);
      cohort.expectationSignatures.add(normalized.join(","));
      cohort.expected = new Set(normalized);
    }
    cohorts.set(key, cohort);
  }
  return rows.filter((row) => {
    const key = `${row.restaurant_id}|${row.sales_date ?? ""}`;
    const cohort = cohorts.get(key);
    return Boolean(
      cohort &&
        !cohort.invalid &&
        cohort.timestamps.size === 1 &&
        cohort.expectationSignatures.size === 1 &&
        cohort.expected &&
        cohort.actual.size === cohort.expected.size &&
        [...cohort.expected].every((hour) => cohort.actual.has(hour)),
    );
  });
}
