import { describe, expect, it } from "vitest";

import { businessDayOrder, sortByBusinessDay, visibleHours } from "../src/lib/businessDay";

/** Fila mínima: a estas funciones solo les importan la hora y la venta. */
function fila(hour: number, net: number | null = null) {
  return { hour, net };
}

describe("businessDayOrder", () => {
  it("abre el día a las 06:00", () => {
    expect(businessDayOrder(6)).toBe(0);
  });

  it("mantiene el orden del reloj durante el día", () => {
    expect(businessDayOrder(13)).toBeLessThan(businessDayOrder(23));
  });

  it("manda la madrugada al final, detrás de las 23", () => {
    expect(businessDayOrder(0)).toBeGreaterThan(businessDayOrder(23));
  });

  it("cierra el día a las 05:00, que es la última hora", () => {
    expect(businessDayOrder(5)).toBe(23);
  });
});

describe("sortByBusinessDay", () => {
  it("ordena el día como se vive el turno: 06 primero, madrugada al final", () => {
    const desordenadas = [fila(0), fila(13), fila(6), fila(5), fila(23)];
    expect(sortByBusinessDay(desordenadas).map((f) => f.hour)).toEqual([6, 13, 23, 0, 5]);
  });

  it("no altera la lista que recibe", () => {
    const original = [fila(0), fila(6)];
    sortByBusinessDay(original);
    expect(original.map((f) => f.hour)).toEqual([0, 6]);
  });
});

describe("visibleHours", () => {
  it("esconde una hora ya pasada que no tuvo venta", () => {
    // Las 08:00 con el reloj en las 14:00: pasó y no vendió nada.
    const filas = [fila(8, null), fila(13, 500)];
    expect(visibleHours(filas, 14).map((f) => f.hour)).toEqual([13]);
  });

  it("trata el 0,00 € de la fuente de ventas como hora sin venta", () => {
    // la fuente de ventas sí llega a dar ceros explícitos: 26 en el histórico. Un cero y un
    // hueco dicen lo mismo de cara a la tabla.
    expect(visibleHours([fila(8, 0), fila(13, 500)], 14).map((f) => f.hour)).toEqual([13]);
  });

  it("mantiene la madrugada que sí vendió", () => {
    // Las horas entre las 00:00 y las 05:59 pertenecen al turno y deben verse.
    expect(visibleHours([fila(0, 471), fila(13, 500)], 14).map((f) => f.hour)).toEqual([0, 13]);
  });

  it("mantiene las horas que todavía no han llegado", () => {
    // A las 14:00, las 20:00 no tienen venta porque no han pasado. Ahí está la
    // previsión de lo que queda de tarde: esconderla sería perder lo útil.
    expect(visibleHours([fila(20, null)], 14).map((f) => f.hour)).toEqual([20]);
  });

  it("mantiene la hora en curso aunque aún no tenga venta", () => {
    expect(visibleHours([fila(14, null)], 14).map((f) => f.hour)).toEqual([14]);
  });

  it("en un día cerrado esconde toda hora sin venta", () => {
    const filas = [fila(8, null), fila(13, 500), fila(20, null)];
    expect(visibleHours(filas, null).map((f) => f.hour)).toEqual([13]);
  });

  it("respeta el orden que recibe", () => {
    const filas = sortByBusinessDay([fila(0, 300), fila(13, 500), fila(8, null)]);
    expect(visibleHours(filas, 14).map((f) => f.hour)).toEqual([13, 0]);
  });

  it("la madrugada del día en curso todavía no ha llegado: se ve", () => {
    // A las 14:00, las 01:00 de ESTE día de negocio son esta noche, no esta
    // mañana: ahí está la previsión del cierre y no se puede esconder.
    const filas = sortByBusinessDay([fila(1, null), fila(13, 500)]);
    expect(visibleHours(filas, 14).map((f) => f.hour)).toEqual([13, 1]);
  });

  it("de madrugada, la mañana ya pasada sin venta se esconde", () => {
    // A la 01:00, las 09:00 de este día de negocio pasaron hace dieciséis
    // horas: si no vendieron, fuera. Las 02:00 aún no han llegado: se ven.
    const filas = sortByBusinessDay([fila(9, null), fila(23, 500), fila(2, null)]);
    expect(visibleHours(filas, 1).map((f) => f.hour)).toEqual([23, 2]);
  });

  it("la hora en curso de madrugada se ve aunque no tenga venta", () => {
    expect(visibleHours([fila(1, null)], 1).map((f) => f.hour)).toEqual([1]);
  });
});
