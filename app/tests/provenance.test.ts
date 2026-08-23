import { describe, expect, it } from "vitest";

import {
  dayProvenance,
  isProvisionalSalesSource,
  provenanceLabel,
  provenanceTimestampLead,
} from "../src/lib/provenance";
import type { Restaurant, DailyStatus } from "../src/lib/types";

const RESTAURANTS: Restaurant[] = [
  { id: "R001", name: "Restaurante A", sort_order: 1, has_drive_through: true },
  { id: "R002", name: "Restaurante B", sort_order: 2, has_drive_through: false },
  { id: "R003", name: "Restaurante C", sort_order: 3, has_drive_through: true },
];

function status(restaurantId: string, source: DailyStatus["source"]): DailyStatus {
  return {
    restaurantId,
    capturedAt: "2026-08-08T18:00:00Z",
    source,
    quality: "clean",
    contributingCaptures: 1,
  };
}

describe("provenance", () => {
  it("identifica un cierre definitivo procedente del POS", () => {
    expect(provenanceLabel("pos")).toBe("cerrado con POS");
    expect(provenanceTimestampLead("pos")).toBe("cerrado el");
    expect(isProvisionalSalesSource("pos")).toBe(false);
  });

  it("conserva el lenguaje de las capturas la fuente de ventas", () => {
    expect(provenanceLabel("live")).toBe("capturado en vivo");
    expect(provenanceLabel("import")).toBe("importado de la fuente mensual");
    expect(provenanceLabel("backfill")).toBe("recuperado por backfill");
    expect(provenanceTimestampLead("live")).toBe("capturado el");
    expect(isProvisionalSalesSource("live")).toBe(true);
    expect(isProvisionalSalesSource("backfill")).toBe(true);
    expect(isProvisionalSalesSource("import")).toBe(false);
  });

  it("no llama cierre POS al agregado si aún faltan dos locales", () => {
    const statuses = new Map<string, DailyStatus>([
      ["R001", status("R001", "backfill")],
      ["R002", status("R002", "backfill")],
      ["R003", status("R003", "pos")],
    ]);

    expect(dayProvenance(RESTAURANTS, statuses)).toEqual({
      source: "mixed",
      capturedAt: "2026-08-08T18:00:00Z",
      pendingRestaurantNames: ["Restaurante A", "Restaurante B"],
    });
    expect(dayProvenance([RESTAURANTS[2]!], statuses)).toEqual({
      source: "pos",
      capturedAt: "2026-08-08T18:00:00Z",
      pendingRestaurantNames: [],
    });
  });

  it("certifica POS solo cuando todos los locales visibles están cerrados", () => {
    const statuses = new Map(
      RESTAURANTS.map((restaurant) => [restaurant.id, status(restaurant.id, "pos")]),
    );

    expect(dayProvenance(RESTAURANTS, statuses)?.source).toBe("pos");
    expect(dayProvenance(RESTAURANTS, statuses)?.pendingRestaurantNames).toEqual([]);
  });

  it("un local sin estado tampoco permite certificar el conjunto", () => {
    const statuses = new Map<string, DailyStatus>([
      ["R003", status("R003", "pos")],
    ]);

    expect(dayProvenance(RESTAURANTS, statuses)?.source).toBe("mixed");
    expect(dayProvenance(RESTAURANTS, statuses)?.pendingRestaurantNames).toEqual([
      "Restaurante A",
      "Restaurante B",
    ]);
  });
});
