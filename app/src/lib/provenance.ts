import type {
  DayProvenance,
  DayProvenanceSource,
  DaySource,
  Restaurant,
  DailyStatus,
} from "./types";

const PROVENANCE_LABELS: Record<DayProvenanceSource, string> = {
  live: "capturado en vivo",
  import: "importado de la fuente mensual",
  backfill: "recuperado por backfill",
  pos: "cerrado con POS",
  mixed: "fuentes de cierre mixtas",
};

export function provenanceLabel(source: DayProvenanceSource): string {
  return PROVENANCE_LABELS[source];
}

export function provenanceTimestampLead(source: DayProvenanceSource): string {
  if (source === "pos") return "cerrado el";
  return source === "mixed" ? "revisado el" : "capturado el";
}

export function isProvisionalSalesSource(source: DaySource): boolean {
  return source === "live" || source === "backfill";
}

/** Procedencia conjunta sin convertir un cierre parcial en un cierre POS total. */
export function dayProvenance(
  restaurants: Restaurant[],
  statuses: Map<string, DailyStatus>,
): DayProvenance | null {
  const available: DailyStatus[] = [];
  const pendingRestaurantNames: string[] = [];
  for (const restaurant of restaurants) {
    const status = statuses.get(restaurant.id);
    if (status === undefined) {
      pendingRestaurantNames.push(restaurant.name);
      continue;
    }
    available.push(status);
    if (isProvisionalSalesSource(status.source)) pendingRestaurantNames.push(restaurant.name);
  }
  if (available.length === 0) return null;

  const sources = new Set(available.map((status) => status.source));
  const completeCoverage = available.length === restaurants.length;
  const source =
    completeCoverage && sources.size === 1 ? (available[0]?.source ?? "mixed") : "mixed";
  const capturedAt = available.map((status) => status.capturedAt).sort()[0]!;

  return { source, capturedAt, pendingRestaurantNames };
}
