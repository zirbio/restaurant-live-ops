type FeatureEnv = Record<string, string | boolean | undefined>;

export interface MonthlyFeature {
  enabled: boolean;
  configured: boolean;
}

export function monthlyFeature(env: FeatureEnv): MonthlyFeature {
  const enabled = env.VITE_MONTHLY_ENABLED === "true";
  return {
    enabled,
    configured: enabled && env.VITE_MONTHLY_SOURCE === "supabase",
  };
}
