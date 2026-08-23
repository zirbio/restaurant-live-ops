import { describe, expect, it } from "vitest";

import {
  combine,
  discardOtherDay,
  serviceTimes,
  type State,
} from "../src/data/useDay";
import type { DailyTotalsRow, LiveDay, SalesRow } from "../src/data/useDay";
import { differencePp } from "../src/lib/monthly";

function estadoCon(salesDate: string): State {
  const data = {
    restaurants: [],
    hoursByRestaurant: new Map(),
    objectivesByRestaurant: new Map(),
    serviceTimesByRestaurant: new Map(),
    dailyStatusByRestaurant: new Map(),
    priorByRestaurant: new Map(),
    runs: [],
    salesDate,
    provenance: null,
    earliestDate: null,
    nationalYoy: null,
  } satisfies LiveDay;
  return { data, loading: false, error: null };
}

describe("discardOtherDay", () => {
  it("tira lo cargado cuando es de otro día", () => {
    // Si no, al pulsar la flecha se verían las cifras de hoy bajo la fecha de
    // ayer hasta que llegase la respuesta.
    const siguiente = discardOtherDay(estadoCon("2026-07-27"), "2026-07-26");
    expect(siguiente.data).toBeNull();
    expect(siguiente.loading).toBe(true);
  });

  it("conserva lo cargado si es del día pedido", () => {
    const previo = estadoCon("2026-07-27");
    expect(discardOtherDay(previo, "2026-07-27")).toBe(previo);
  });

  it("no toca un estado que aún no tiene datos", () => {
    const previo: State = { data: null, loading: true, error: null };
    expect(discardOtherDay(previo, "2026-07-26")).toBe(previo);
  });

  it("limpia también el error del día anterior", () => {
    // Un error del día que se abandona no debe teñir el día nuevo.
    const previo: State = { ...estadoCon("2026-07-27"), error: "fallo de red" };
    expect(discardOtherDay(previo, "2026-07-26").error).toBeNull();
  });
});

/** Fila sintética de ventas: solo importan la hora y el neto. */
function venta(hour: number, net: number | null): SalesRow {
  return {
    restaurant_id: "R001",
    source_date: "2026-07-27",
    calendar_date: hour < 6 ? "2026-07-28" : "2026-07-27",
    hour,
    fold: 0,
    captured_at: "2026-07-28T04:10:00Z",
    net,
    gc: null,
    drive_through_net: null,
    drive_through_cars: null,
    delivery_net: null,
    delivery_count: null,
    kvs: null,
    r2p: null,
    oepe: null,
  };
}

describe("combine", () => {
  it("devuelve las horas en el orden del día de restaurante", () => {
    // Aunque la fuente entregue las filas desordenadas, las horas desde las
    // 06:00 van primero y la madrugada cierra la lista.
    const filas = combine(
      [venta(0, 471), venta(14, 948), venta(8, null)],
      [
        {
          restaurant_id: "R001",
          hour: 23,
          sales: 933,
          guest_counts: 40,
          fetched_at: "2030-01-15T08:00:00Z",
          expected_hours: [23],
        },
      ],
      [],
    );
    expect(filas.get("R001")?.map((f) => f.hour)).toEqual([8, 14, 23, 0]);
  });

  it("cruza venta, previsión y personal en la misma fila", () => {
    const filas = combine(
      [venta(14, 948)],
      [
        {
          restaurant_id: "R001",
          hour: 14,
          sales: 1050,
          guest_counts: 66,
          fetched_at: "2030-01-15T08:00:00Z",
          expected_hours: [14],
        },
      ],
      [
        {
          restaurant_id: "R001",
          hour: 14,
          crew_clocked_count: 12,
          crew_assigned_count: 14,
          crew_open_anomalies: null,
          fetched_at: "2030-01-15T08:00:00Z",
          expected_hours: [14],
        },
      ],
    );
    const fila = filas.get("R001")?.[0];
    expect(fila?.net).toBe(948);
    expect(fila?.proj_sales).toBe(1050);
    expect(fila?.clocked).toBe(12);
    expect(fila?.assigned).toBe(14);
  });

  it("trae los recuentos por canal, no solo los euros", () => {
    // El desglose de la hora se enseña en clientes: los coches de servicio en vehículo y los
    // pedidos de Delivery tienen que llegar hasta la fila.
    const filas = combine(
      [{ ...venta(14, 948), gc: 66, drive_through_cars: 21, delivery_count: 9 }],
      [],
      [],
    );
    const fila = filas.get("R001")?.[0];
    expect(fila?.gc).toBe(66);
    expect(fila?.drive_through_cars).toBe(21);
    expect(fila?.delivery_count).toBe(9);
  });

  it("suma ambos folds DST en el mismo slot visual sin elegir uno", () => {
    const filas = combine(
      [
        {
          ...venta(2, 20),
          source_date: "2026-10-25",
          calendar_date: "2026-10-25",
          fold: 0,
          captured_at: "2026-10-25T01:05:00Z",
          gc: 2,
          drive_through_net: 8,
          drive_through_cars: 1,
          delivery_net: 4,
          delivery_count: 1,
          kvs: 80,
        },
        {
          ...venta(2, 30),
          source_date: "2026-10-25",
          calendar_date: "2026-10-25",
          fold: 1,
          captured_at: "2026-10-25T02:05:00Z",
          gc: 3,
          drive_through_net: 12,
          drive_through_cars: 2,
          delivery_net: 6,
          delivery_count: 2,
          kvs: 90,
        },
      ],
      [],
      [],
    );

    expect(filas.get("R001")?.[0]).toMatchObject({
      hour: 2,
      net: 50,
      gc: 5,
      drive_through_net: 20,
      drive_through_cars: 3,
      delivery_net: 10,
      delivery_count: 3,
      kvs: null,
    });
  });

  it("sin recuento de equipo la fila queda vacía, no a cero", () => {
    // Pasa en los días guardados antes de que se miraran los roles, y cuando
    // la fuente de personal no deja resolver quién es quién. La tabla enseña una raya: un 0
    // diría que no había nadie en el turno, que es otra cosa y es mentira.
    const filas = combine(
      [venta(14, 948)],
      [],
      [
        {
          restaurant_id: "R001",
          hour: 14,
          crew_clocked_count: null,
          crew_assigned_count: null,
          crew_open_anomalies: null,
          fetched_at: "2030-01-15T08:00:00Z",
          expected_hours: [14],
        },
      ],
    );
    const fila = filas.get("R001")?.[0];
    expect(fila?.clocked).toBeNull();
    expect(fila?.assigned).toBeNull();
  });

  it("lleva el aviso de fichaje sin cerrar hasta la fila de la hora", () => {
    // El aviso que se pinta es el del EQUIPO, la misma población que la cifra
    // de al lado: el total incluiría a la dirección y marcaría horas intactas.
    const filas = combine(
      [],
      [],
      [
        {
          restaurant_id: "R001",
          hour: 7,
          crew_clocked_count: 2,
          crew_assigned_count: 3,
          crew_open_anomalies: 1,
          fetched_at: "2030-01-15T08:00:00Z",
          expected_hours: [7],
        },
      ],
    );
    expect(filas.get("R001")?.[0]?.clipped).toBe(1);
  });
});

function totales(partial: Partial<DailyTotalsRow> & { restaurant_id: string }): DailyTotalsRow {
  return {
    restaurant_id: partial.restaurant_id,
    sales_date: partial.sales_date ?? "2026-07-27",
    hourly_net_sum: partial.hourly_net_sum ?? 0,
    source: partial.source ?? "live",
    quality: partial.quality ?? "clean",
    kvs: partial.kvs ?? null,
    r2p: partial.r2p ?? null,
    oepe: partial.oepe ?? null,
    gc: partial.gc ?? null,
    captured_at: partial.captured_at ?? "2026-07-27T18:00:00Z",
  };
}

describe("tiempos de servicio del día", () => {
  it("los toma de la fila de totales de la fuente de ventas, sin recalcular nada", () => {
    // La media horaria calculada localmente puede diferir del total ponderado
    // de la fuente y no debe reemplazarlo.
    const mapa = serviceTimes([totales({ restaurant_id: "R002", kvs: 75, r2p: 111, oepe: null })]);
    expect(mapa.get("R002")).toEqual({ kvs: 75, r2p: 111, oepe: null });
  });

  it("conserva el total oficial aunque la venta se recomponga 06→06", () => {
    const mapa = serviceTimes([
      totales({ restaurant_id: "R003", kvs: 76, r2p: 89, oepe: 133 }),
    ]);
    expect(mapa.get("R003")).toEqual({ kvs: 76, r2p: 89, oepe: 133 });
  });

  it("un restaurante sin fila de totales no tiene tiempos: raya, no cero", () => {
    const mapa = serviceTimes([totales({ restaurant_id: "R001", kvs: 82 })]);
    expect(mapa.get("R003")).toBeUndefined();
  });

  it("se queda con la captura más reciente de cada restaurante", () => {
    // Las filas llegan ordenadas por captura descendente; una captura vieja del
    // mismo día no puede pisar a la buena.
    const mapa = serviceTimes([
      totales({ restaurant_id: "R001", kvs: 82, captured_at: "2026-07-27T18:00:00Z" }),
      totales({ restaurant_id: "R001", kvs: 60, captured_at: "2026-07-27T09:00:00Z" }),
    ]);
    expect(mapa.get("R001")?.kvs).toBe(82);
  });
});

describe("diferencial del día contra España", () => {
  it("son puntos, no un cociente", () => {
    expect(differencePp(8.58, 3.9)).toBeCloseTo(4.68, 6);
  });

  it("sin uno de los dos lados no hay diferencial", () => {
    expect(differencePp(8.58, null)).toBeNull();
    expect(differencePp(null, 3.9)).toBeNull();
  });
});
