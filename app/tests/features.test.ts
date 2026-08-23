import { describe, expect, it } from "vitest";

import { monthlyFeature } from "../src/lib/features";

describe("monthlyFeature", () => {
  it("is disabled by default", () => {
    expect(monthlyFeature({})).toEqual({ enabled: false, configured: false });
  });

  it("reports missing source when enabled", () => {
    expect(monthlyFeature({ VITE_MONTHLY_ENABLED: "true" })).toEqual({
      enabled: true,
      configured: false,
    });
  });

  it("is ready only with the Supabase contract", () => {
    expect(
      monthlyFeature({
        VITE_MONTHLY_ENABLED: "true",
        VITE_MONTHLY_SOURCE: "supabase",
      }),
    ).toEqual({ enabled: true, configured: true });
  });

  it.each<{
    label: string;
    env: Record<string, string | boolean>;
    expectedEnabled: boolean;
  }>([
    { label: "a boolean flag", env: { VITE_MONTHLY_ENABLED: true }, expectedEnabled: false },
    { label: "an uppercase flag", env: { VITE_MONTHLY_ENABLED: "TRUE" }, expectedEnabled: false },
    { label: "a padded flag", env: { VITE_MONTHLY_ENABLED: " true " }, expectedEnabled: false },
    {
      label: "an unsupported source",
      env: { VITE_MONTHLY_ENABLED: "true", VITE_MONTHLY_SOURCE: "private" },
      expectedEnabled: true,
    },
  ])("fails closed with $label", ({ env, expectedEnabled }) => {
    expect(monthlyFeature(env)).toEqual({
      enabled: expectedEnabled,
      configured: false,
    });
  });
});
