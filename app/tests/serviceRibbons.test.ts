import { describe, expect, it } from "vitest";

import { serviceRibbons, type ServiceRibbon } from "../src/lib/serviceRibbons";
import type { ServiceMetric } from "../src/lib/serviceBands";
import type { HourRow, Light, Objectives } from "../src/lib/types";

function hora(partial: Partial<HourRow> & { hour: number }): HourRow {
  return {
    hour: partial.hour,
    net: partial.net ?? null,
    // Por defecto, una hora con clientes y coches de sobra: lo que se prueba en
    // cada caso es el tiempo, no el volumen. El volumen tiene sus propias
    // pruebas más abajo. Se compara con `undefined` y no con `??` para que un
    // `gc: null` escrito a mano llegue como null, que es uno de los casos.
    gc: partial.gc === undefined ? 100 : partial.gc,
    drive_through_net: partial.drive_through_net ?? null,
    drive_through_cars: partial.drive_through_cars === undefined ? 30 : partial.drive_through_cars,
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

const OBJETIVOS: Objectives = { restaurant_id: "R001", kvs: 81, r2p: 139, oepe: 162 };

/** Las luces de una métrica, en orden. Lista vacía si esa cinta no se dibuja. */
function luces(cintas: ServiceRibbon[], metric: ServiceMetric): Light[] {
  return cintas.find((c) => c.metric === metric)?.cells.map((c) => c.light) ?? [];
}

describe("serviceRibbons", () => {
  it("da una cinta por métrica, en orden KVS, R2P, OEPE", () => {
    const filas = [hora({ hour: 13, kvs: 70, r2p: 120, oepe: 150 })];
    expect(serviceRibbons(filas, OBJETIVOS, true).map((c) => c.metric)).toEqual([
      "kvs",
      "r2p",
      "oepe",
    ]);
  });

  it("da una luz por hora, en el mismo orden que las filas", () => {
    // El orden lo fija quien llama (día de negocio: 06…23 y luego 00…05); la
    // cinta se limita a seguirlo, para que cada celda caiga bajo su barra.
    const filas = [
      hora({ hour: 22, kvs: 70 }),
      hora({ hour: 23, kvs: 90 }),
      hora({ hour: 0, kvs: 200 }),
    ];
    expect(luces(serviceRibbons(filas, OBJETIVOS, true), "kvs")).toEqual(["ok", "warn", "bad"]);
  });

  it("cada celda lleva su hora, para poder emparejarla con la barra de venta", () => {
    const filas = [hora({ hour: 22, kvs: 70 }), hora({ hour: 23, kvs: 90 })];
    const kvs = serviceRibbons(filas, OBJETIVOS, true).find((c) => c.metric === "kvs");
    expect(kvs?.cells.map((c) => c.hour)).toEqual([22, 23]);
  });

  it("juzga con el mismo umbral que el resto de la app: ámbar hasta un 12 %", () => {
    // 81 × 1,12 = 90,72: 90 es ámbar y 91 ya es rojo.
    const filas = [
      hora({ hour: 13, kvs: 81 }),
      hora({ hour: 14, kvs: 90 }),
      hora({ hour: 15, kvs: 91 }),
    ];
    expect(luces(serviceRibbons(filas, OBJETIVOS, true), "kvs")).toEqual(["ok", "warn", "bad"]);
  });

  it("una hora sin tiempo se queda sin luz: nunca en verde por defecto", () => {
    const filas = [hora({ hour: 13, kvs: 70 }), hora({ hour: 14 })];
    expect(luces(serviceRibbons(filas, OBJETIVOS, true), "kvs")).toEqual(["ok", "none"]);
  });

  it("sin objetivo del mes no se juzga nada, y no queda cinta que dibujar", () => {
    // Sin objetivo guardado, una cinta entera en gris se leería como un dato
    // que no ha llegado, aunque la métrica sí esté disponible.
    const filas = [hora({ hour: 13, kvs: 70, r2p: 120, oepe: 150 })];
    expect(serviceRibbons(filas, null, true)).toEqual([]);
  });

  it("sin servicio en vehículo no hay cinta de OEPE", () => {
    // Sin servicio en vehículo, una fila gris invitaría a esperar una métrica
    // que no aplica.
    const filas = [hora({ hour: 13, kvs: 70, r2p: 120, oepe: 150 })];
    const sinDriveThrough: Objectives = { ...OBJETIVOS, oepe: null };
    expect(serviceRibbons(filas, sinDriveThrough, false).map((c) => c.metric)).toEqual(["kvs", "r2p"]);
  });

  it("no dibuja la métrica que no tiene ni una sola hora medida", () => {
    // Misma regla que la gráfica de tendencia: una cinta sin una sola luz no
    // dice nada, y ocupa el sitio de las que sí.
    const filas = [hora({ hour: 13, kvs: 70, r2p: 120 })];
    expect(serviceRibbons(filas, OBJETIVOS, true).map((c) => c.metric)).toEqual(["kvs", "r2p"]);
  });

  it("sin horas no hay cintas", () => {
    expect(serviceRibbons([], OBJETIVOS, true)).toEqual([]);
  });
});

describe("umbral de clientes", () => {
  it("una hora que no llega al umbral no se juzga, por buena que parezca", () => {
    // El objetivo del mes lo fija la hora punta: contra esa vara, una hora sin
    // cola sale verde por no tener a quien atender. Eso no es un veredicto.
    const filas = [hora({ hour: 11, gc: 6, kvs: 40, r2p: 60, oepe: 80 })];
    expect(serviceRibbons(filas, OBJETIVOS, true)).toEqual([]);
  });

  it("el caso que lo motivó: la hora de 6 clientes no pinta, ni bien ni mal", () => {
    // Una muestra mínima no basta para juzgar un tiempo extremo.
    const filas = [
      hora({ hour: 11, gc: 6, net: 27.82, r2p: 504 }),
      hora({ hour: 21, gc: 156, r2p: 111 }),
    ];
    expect(luces(serviceRibbons(filas, OBJETIVOS, true), "r2p")).toEqual(["none", "ok"]);
  });

  it("el umbral son 10 clientes: con 10 no se juzga y con 11 sí", () => {
    const filas = [hora({ hour: 12, gc: 10, kvs: 70 }), hora({ hour: 13, gc: 11, kvs: 70 })];
    expect(luces(serviceRibbons(filas, OBJETIVOS, true), "kvs")).toEqual(["none", "ok"]);
  });

  it("el mismo umbral vale para las tres, sea cual sea el canal que miden", () => {
    // 40 clientes de los que 25 son coches y 13 de delivery: quedan 2 de
    // mostrador, y aun así el R2P se juzga. La misma regla se aplica a las tres.
    const filas = [
      hora({ hour: 21, gc: 40, drive_through_cars: 25, delivery_count: 13, kvs: 70, r2p: 120, oepe: 150 }),
    ];
    const cintas = serviceRibbons(filas, OBJETIVOS, true);
    expect(cintas.map((c) => c.metric)).toEqual(["kvs", "r2p", "oepe"]);
  });

  it("sin guest counts no se puede saber el volumen, así que no se juzga", () => {
    const filas = [hora({ hour: 12, gc: null, kvs: 70 }), hora({ hour: 13, gc: 40, kvs: 70 })];
    expect(luces(serviceRibbons(filas, OBJETIVOS, true), "kvs")).toEqual(["none", "ok"]);
  });

  it("el umbral apaga el tiempo, nunca la barra de venta", () => {
    // La cinta deja de juzgar esa hora; la venta de la curva no la toca nadie.
    const filas = [hora({ hour: 11, gc: 6, net: 27.82, kvs: 40 })];
    expect(serviceRibbons(filas, OBJETIVOS, true)).toEqual([]);
    expect(filas[0]?.net).toBe(27.82);
  });
});
