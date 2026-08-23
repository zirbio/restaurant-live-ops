import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { env as processEnv } from "node:process";
import { fileURLToPath } from "node:url";

import { createClient } from "@supabase/supabase-js";
import { expect, it } from "vitest";

import { combine, salesRowsQuery, type SalesRow } from "../src/data/useDay";

const TARGET_SALES_DATE = "2036-10-25";
const projectRoot = fileURLToPath(new URL("../..", import.meta.url));
const fixturePath = fileURLToPath(
  new URL("../../worker/tests/support/local_frontend_fixture.py", import.meta.url),
);
const requiredVariables = [
  "LOCAL_SUPABASE_URL",
  "LOCAL_SUPABASE_ANON_KEY",
  "LOCAL_SUPABASE_SERVICE_ROLE_KEY",
  "LOCAL_SUPABASE_DB_URL",
] as const;
const integrationEnabled = requiredVariables.every((name) => Boolean(processEnv[name]));
const localIntegration = integrationEnabled ? it : it.skip;

function requiredEnv(name: (typeof requiredVariables)[number]): string {
  const value = processEnv[name];
  if (!value) throw new Error(`falta ${name} para la integración local`);
  return value;
}

function runFixture(action: "prepare" | "cleanup", userId: string, dbUrl: string): void {
  execFileSync(
    "uv",
    [
      "run",
      "--project",
      `${projectRoot}/worker`,
      "python",
      fixturePath,
      action,
      "--user-id",
      userId,
    ],
    {
      cwd: projectRoot,
      env: { ...processEnv, LOCAL_SUPABASE_DB_URL: dbUrl },
      stdio: "pipe",
    },
  );
}

localIntegration(
  "cruza worker, PostgreSQL, PostgREST/RLS y el agregador real de useDay",
  async () => {
    const url = requiredEnv("LOCAL_SUPABASE_URL");
    const anonKey = requiredEnv("LOCAL_SUPABASE_ANON_KEY");
    const serviceRoleKey = requiredEnv("LOCAL_SUPABASE_SERVICE_ROLE_KEY");
    const dbUrl = requiredEnv("LOCAL_SUPABASE_DB_URL");
    const suffix = randomUUID();
    const email = `task4-${suffix}@example.test`;
    const generatedCredential = `Local-${suffix}-Aa1!`;
    const authOptions = {
      persistSession: false,
      autoRefreshToken: false,
      detectSessionInUrl: false,
    };
    const admin = createClient(url, serviceRoleKey, { auth: authOptions });
    const authenticated = createClient(url, anonKey, { auth: authOptions });
    let userId: string | null = null;

    let executionError: unknown = null;
    try {
      const created = await admin.auth.admin.createUser({
        email,
        password: generatedCredential,
        email_confirm: true,
      });
      if (created.error || !created.data.user) {
        throw new Error(`no se pudo crear el usuario local: ${created.error?.message ?? "sin fila"}`);
      }
      userId = created.data.user.id;
      runFixture("prepare", userId, dbUrl);

      const signedIn = await authenticated.auth.signInWithPassword({
        email,
        password: generatedCredential,
      });
      if (signedIn.error) {
        throw new Error(`no se pudo autenticar el usuario local: ${signedIn.error.message}`);
      }

      const visibleRestaurants = await authenticated
        .from("restaurants")
        .select("id")
        .order("id");
      if (visibleRestaurants.error) throw new Error(visibleRestaurants.error.message);
      expect(visibleRestaurants.data).toEqual([{ id: "R001" }]);

      const salesResponse = await salesRowsQuery(authenticated, TARGET_SALES_DATE);
      if (salesResponse.error) throw new Error(salesResponse.error.message);
      const sales = salesResponse.data as SalesRow[];
      expect(sales).toHaveLength(6);
      expect([...new Set(sales.map((row) => row.source_date))].sort()).toEqual([
        "2036-10-25",
        "2036-10-26",
      ]);
      expect(
        sales
          .filter((row) => row.calendar_date === "2036-10-26" && row.hour === 2)
          .map((row) => row.fold)
          .sort(),
      ).toEqual([0, 0, 1, 1]);

      const visual = combine(sales, [], []).get("R001");
      expect(visual).toEqual([
        expect.objectContaining({
          hour: 22,
          net: 50,
          gc: 5,
          drive_through_net: 20,
          drive_through_cars: 2,
          delivery_net: 10,
          delivery_count: 1,
        }),
        expect.objectContaining({
          hour: 2,
          net: 300,
          gc: 30,
          drive_through_net: 120,
          drive_through_cars: 12,
          delivery_net: 60,
          delivery_count: 6,
          kvs: null,
        }),
      ]);
      expect(visual?.reduce((sum, row) => sum + (row.net ?? 0), 0)).toBe(350);

      const totals = await authenticated
        .from("sales_daily_totals")
        .select(
          "net,hourly_net_sum,gc,drive_through_net,drive_through_cars," +
            "delivery_net,delivery_count,quality",
        )
        .eq("sales_date", TARGET_SALES_DATE)
        .single();
      if (totals.error) throw new Error(totals.error.message);
      expect(totals.data).toEqual({
        net: 350,
        hourly_net_sum: 350,
        gc: 35,
        drive_through_net: 140,
        drive_through_cars: 14,
        delivery_net: 70,
        delivery_count: 7,
        quality: "rebucketed",
      });
    } catch (error) {
      executionError = error;
    }

    const cleanupErrors: unknown[] = [];
    if (userId) {
      try {
        runFixture("cleanup", userId, dbUrl);
      } catch (error) {
        cleanupErrors.push(error);
      }
      const signedOut = await authenticated.auth.signOut();
      if (signedOut.error) cleanupErrors.push(signedOut.error);
      const deleted = await admin.auth.admin.deleteUser(userId);
      if (deleted.error) cleanupErrors.push(deleted.error);
    }

    if (executionError && cleanupErrors.length > 0) {
      throw new AggregateError(
        [executionError, ...cleanupErrors],
        "fallaron la integración local y su limpieza",
      );
    }
    if (executionError) throw executionError;
    if (cleanupErrors.length > 0) {
      throw new AggregateError(cleanupErrors, "falló la limpieza de la integración local");
    }
  },
  120_000,
);
