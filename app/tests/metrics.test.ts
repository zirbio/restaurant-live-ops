import { describe, expect, it } from "vitest";

import {
  aggregate,
  counterGc,
  counterNet,
  currentHourRow,
  deviation,
  liveStaffing,
  serviceLight,
  ticketMedio,
} from "../src/lib/metrics";
import type { HourRow } from "../src/lib/types";

function hora(partial: Partial<HourRow> & { hour: number }): HourRow {
  return {
    hour: partial.hour,
    net: partial.net ?? null,
    gc: partial.gc ?? null,
    drive_through_net: partial.drive_through_net ?? null,
    drive_through_cars: partial.drive_through_cars ?? null,
    delivery_net: partial.delivery_net ?? null,
    delivery_count: partial.delivery_count ?? null,
    kvs: partial.kvs ?? null,
    r2p: partial.r2p ?? null,
    oepe: partial.oepe ?? null,
    proj_sales: partial.proj_sales ?? null,
    proj_gc: partial.proj_gc ?? null,
    clocked: partial.clocked ?? null,
    assigned: partial.assigned ?? null,
    clipped: partial.clipped ?? null,
  };
}

describe("ticket medio", () => {
  it("es la venta entre los guest counts", () => {
    expect(ticketMedio(1000, 100)).toBe(10);
  });

  it("sin guest counts no se muestra: no es cero", () => {
    expect(ticketMedio(1000, 0)).toBeNull();
    expect(ticketMedio(1000, null)).toBeNull();
    expect(ticketMedio(null, 100)).toBeNull();
  });
});

describe("desviación frente a la previsión", () => {
  it("va en euros y en porcentaje", () => {
    expect(deviation(1100, 1000)).toEqual({ euros: 100, pct: 10 });
    expect(deviation(900, 1000)).toEqual({ euros: -100, pct: -10 });
  });

  it("sin previsión no inventa un porcentaje", () => {
    expect(deviation(1100, 0)).toEqual({ euros: 1100, pct: null });
    expect(deviation(1100, null)).toEqual({ euros: null, pct: null });
  });
});

describe("mostrador y kiosko", () => {
  it("es el total menos servicio en vehículo y Delivery", () => {
    expect(counterNet(hora({ hour: 14, net: 100, drive_through_net: 30, delivery_net: 20 }))).toBe(50);
  });

  it("si falta cualquier operando conserva la ausencia", () => {
    expect(counterNet(hora({ hour: 14, net: 100, delivery_net: 20 }))).toBeNull();
    expect(counterNet(hora({ hour: 14, net: 100, drive_through_net: 30 }))).toBeNull();
    expect(counterNet(hora({ hour: 14, drive_through_net: 30 }))).toBeNull();
  });

  it("el servicio en vehículo puede ser un cero real y se resta igual", () => {
    expect(counterNet(hora({ hour: 14, net: 100, drive_through_net: 0, delivery_net: 20 }))).toBe(80);
  });
});

describe("clientes de mostrador y kiosko", () => {
  it("son los guest counts menos los coches de servicio en vehículo y los pedidos de Delivery", () => {
    expect(counterGc(hora({ hour: 14, gc: 100, drive_through_cars: 30, delivery_count: 20 }))).toBe(50);
  });

  it("si falta cualquier operando conserva la ausencia", () => {
    expect(counterGc(hora({ hour: 14, gc: 100, delivery_count: 20 }))).toBeNull();
    expect(counterGc(hora({ hour: 14, gc: 100, drive_through_cars: 30 }))).toBeNull();
    expect(counterGc(hora({ hour: 14, drive_through_cars: 30 }))).toBeNull();
  });

  it("los coches pueden ser un cero real y se restan igual", () => {
    expect(counterGc(hora({ hour: 14, gc: 100, drive_through_cars: 0, delivery_count: 20 }))).toBe(80);
  });
});

describe("semáforo de tiempos de servicio", () => {
  it("verde por debajo del objetivo del mes", () => {
    expect(serviceLight(70, 81)).toBe("ok");
    expect(serviceLight(81, 81)).toBe("ok");
  });

  it("ámbar hasta un 12 % por encima", () => {
    expect(serviceLight(85, 81)).toBe("warn");
    expect(serviceLight(90, 81)).toBe("warn");
  });

  it("rojo bastante por encima", () => {
    expect(serviceLight(120, 81)).toBe("bad");
  });

  it("sin objetivo o sin dato no hay color", () => {
    expect(serviceLight(70, null)).toBe("none");
    expect(serviceLight(null, 81)).toBe("none");
    // Sin servicio en vehículo no hay dato ni objetivo de OEPE.
    expect(serviceLight(null, null)).toBe("none");
  });
});

describe("totales del día", () => {
  it("suma solo las horas con venta real", () => {
    const t = aggregate([
      hora({ hour: 14, net: 100, gc: 10, proj_sales: 90, proj_gc: 9 }),
      hora({ hour: 15, proj_sales: 80, proj_gc: 8 }),
    ]);
    expect(t.net).toBe(100);
    expect(t.gc).toBe(10);
  });

  it("compara contra la previsión de esas mismas horas, no la del día entero", () => {
    // Si se sumara la previsión de horas que aún no han ocurrido, la
    // desviación saldría negativa toda la mañana sin motivo.
    const t = aggregate([
      hora({ hour: 14, net: 100, gc: 10, proj_sales: 90, proj_gc: 9 }),
      hora({ hour: 15, proj_sales: 80, proj_gc: 8 }),
    ]);
    expect(t.projToNow).toBe(90);
    expect(t.projDay).toBe(170);
  });

  it("no promedia los tiempos de servicio: esos los pondera la fuente de ventas", () => {
    // La media local no coincide necesariamente con la fuente, que pondera por
    // pedidos y coches, y no debe reemplazar el total publicado.
    const t = aggregate([
      hora({ hour: 14, net: 100, gc: 90, kvs: 100 }),
      hora({ hour: 15, net: 100, gc: 10, kvs: 200 }),
    ]);
    expect(t).not.toHaveProperty("kvs");
  });

  it("un día sin datos no da ceros", () => {
    const t = aggregate([]);
    expect(t.net).toBeNull();
    expect(t.gc).toBeNull();
  });

  it("puede dejar fuera la hora en curso, que está a medias", () => {
    // Una hora en curso lleva venta parcial y su previsión completa no debe
    // sumarse como si ya estuviera cerrada.
    const filas = [
      hora({ hour: 19, net: 483, gc: 40, proj_sales: 592, proj_gc: 46 }),
      hora({ hour: 20, net: 159, gc: 13, proj_sales: 1505, proj_gc: 120 }),
    ];
    const conParcial = aggregate(filas);
    const cerrado = aggregate(filas, { excludeHour: 20 });

    expect(conParcial.net).toBe(642);
    expect(conParcial.projToNow).toBe(2097);

    expect(cerrado.net).toBe(483);
    expect(cerrado.projToNow).toBe(592);
  });

  it("en un día cerrado no se descuenta ninguna hora", () => {
    // Un día cerrado entra entero: la hora del reloj actual no puede excluir
    // una hora del día histórico.
    const filas = [
      hora({ hour: 11, net: 300, gc: 20, proj_sales: 280, proj_gc: 19 }),
      hora({ hour: 12, net: 260.79, gc: 18, proj_sales: 250, proj_gc: 17 }),
    ];

    expect(aggregate(filas).net).toBe(560.79);
    expect(aggregate(filas, {}).net).toBe(560.79);
  });

  it("la hora en curso se puede consultar aparte", () => {
    const filas = [
      hora({ hour: 19, net: 483, gc: 40, proj_sales: 592 }),
      hora({ hour: 20, net: 159, gc: 13, proj_sales: 1505 }),
    ];
    expect(currentHourRow(filas, 20)?.net).toBe(159);
    expect(currentHourRow(filas, 21)).toBeNull();
  });
});

describe("personal de la hora en curso", () => {
  it("en un día en curso toma la hora que se está viviendo", () => {
    const filas = [
      hora({ hour: 12, clocked: 5, assigned: 6 }),
      hora({ hour: 13, clocked: 9, assigned: 11 }),
      hora({ hour: 14, clocked: null, assigned: 12 }),
    ];
    expect(liveStaffing(filas, 13)).toEqual({ clocked: 9, assigned: 11, clipped: null });
  });

  it("en un día cerrado toma la última hora con gente dentro", () => {
    const filas = [
      hora({ hour: 22, clocked: 9, assigned: 11 }),
      hora({ hour: 23, clocked: 4, assigned: 5 }),
    ];
    expect(liveStaffing(filas, null)).toEqual({ clocked: 4, assigned: 5, clipped: null });
  });

  it("arrastra el aviso de fichaje sin cerrar de esa misma hora", () => {
    // La tarjeta y la tabla enseñan la misma cifra: si una va corregida a la
    // baja, las dos tienen que decirlo, o la marca solo sale al entrar.
    const filas = [
      hora({ hour: 20, clocked: 11, assigned: 12, clipped: 1 }),
      hora({ hour: 21, clocked: 8, assigned: 8, clipped: 0 }),
    ];
    expect(liveStaffing(filas, 20)).toEqual({ clocked: 11, assigned: 12, clipped: 1 });
    expect(liveStaffing(filas, null)).toEqual({ clocked: 8, assigned: 8, clipped: 0 });
  });

  it("en un día cerrado se salta las horas de madrugada sin nadie", () => {
    // Entrada a las 20:00, cuadrante hasta la 01:30 y sin salida: el worker
    // emite las horas 02 a 05 solo para que se vea el recorte, con cero
    // fichados y cero asignados. Ganaban por ser las últimas y la tarjeta
    // pintaba "0/0 ⚠" en vez del cierre de turno, y encima en una fila que la
    // tabla esconde por ser una hora pasada sin venta.
    const filas = [
      ...[20, 21, 22, 23, 0, 1].map((h) => hora({ hour: h, clocked: 1, assigned: 1 })),
      ...[2, 3, 4, 5].map((h) => hora({ hour: h, clocked: 0, assigned: 0, clipped: 1 })),
    ];
    expect(liveStaffing(filas, null)).toEqual({ clocked: 1, assigned: 1, clipped: null });
  });

  it("devuelve null si ninguna hora tuvo gente: un 0/0 afirmaría demasiado", () => {
    const filas = [2, 3].map((h) => hora({ hour: h, clocked: 0, assigned: 0, clipped: 1 }));
    expect(liveStaffing(filas, null)).toBeNull();
  });

  it("devuelve null si esa hora no tiene cuadrante", () => {
    expect(liveStaffing([hora({ hour: 13 })], 13)).toBeNull();
    expect(liveStaffing([], null)).toBeNull();
  });
});
