import type {
  IngestRun,
  Restaurant,
  DailyStatus,
} from "./types";

export interface RestaurantFreshnessIssue {
  restaurantName: string;
  status: "failed" | "missing";
  reason: string;
  lastGoodAt: string | null;
}

export interface RestaurantFreshnessModel {
  bad: boolean;
  /** Captura buena más antigua: la hora a la que están actualizados TODOS. */
  updatedAt: string | null;
  issues: RestaurantFreshnessIssue[];
  notes: string[];
}

export interface IngestRunFreshnessModel extends RestaurantFreshnessModel {
  capturingRestaurantNames: string[];
}

export interface RestaurantIngestRunState {
  restaurantId: string;
  latestFinished: IngestRun | null;
  latestGood: IngestRun | null;
  running: IngestRun | null;
}

/** Última terminada, última buena y ejecución en curso, con desempate estable. */
export function ingestRunStates(
  restaurants: Restaurant[],
  runs: IngestRun[],
): RestaurantIngestRunState[] {
  const salesRuns = runs.filter((run) => run.source === "sales");
  return restaurants.map((restaurant) => {
    const ordered = salesRuns
      .filter((run) => run.restaurant_id === restaurant.id)
      .sort(
        (left, right) =>
          right.started_at.localeCompare(left.started_at) || right.id - left.id,
      );
    return {
      restaurantId: restaurant.id,
      latestFinished: ordered.find((run) => run.status !== "running") ?? null,
      latestGood: ordered.find((run) => run.status === "ok") ?? null,
      running: ordered.find((run) => run.status === "running") ?? null,
    };
  });
}

/**
 * Frescura del contrato neutral: ningún local puede quedar representado por
 * el ciclo de otro y un ciclo en curso no oculta la última terminada.
 */
export function buildIngestRunFreshness(
  restaurants: Restaurant[],
  runs: IngestRun[],
  dailyStatuses: Map<string, DailyStatus>,
): IngestRunFreshnessModel {
  const states = ingestRunStates(restaurants, runs);
  const issues: RestaurantFreshnessIssue[] = [];
  const goodTimes: string[] = [];

  for (const restaurant of restaurants) {
    const state = states.find((item) => item.restaurantId === restaurant.id);
    const lastGoodAt = state?.latestGood?.finished_at ?? null;
    if (lastGoodAt !== null) goodTimes.push(lastGoodAt);

    if (!state?.latestFinished) {
      issues.push({
        restaurantName: restaurant.name,
        status: "missing",
        reason: "sin ningún ciclo terminado",
        lastGoodAt,
      });
    } else if (state.latestFinished.status === "error") {
      issues.push({
        restaurantName: restaurant.name,
        status: "failed",
        reason: state.latestFinished.error ?? "motivo no registrado",
        lastGoodAt,
      });
    }
  }

  return {
    bad: issues.length > 0,
    updatedAt:
      goodTimes.length === restaurants.length && goodTimes.length > 0
        ? [...goodTimes].sort()[0] ?? null
        : null,
    issues,
    notes: rebucketedNotes(restaurants, dailyStatuses),
    capturingRestaurantNames: restaurants
      .filter((restaurant) =>
        states.some(
          (state) => state.restaurantId === restaurant.id && state.running !== null,
        ),
      )
      .map((restaurant) => restaurant.name),
  };
}

export function rebucketedNotes(
  restaurants: Restaurant[],
  statuses: Map<string, DailyStatus>,
): string[] {
  return restaurants
    .filter((restaurant) => statuses.get(restaurant.id)?.quality === "rebucketed")
    .map(
      (restaurant) =>
        `${restaurant.name}: venta 06→06 recompuesta; tiempos no combinados`,
    );
}
