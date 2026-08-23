/**
 * Cálculos de la pantalla del día.
 *
 * Definiciones canónicas, las mismas que en el resto de las herramientas:
 *
 *  - Mostrador + kiosko = neto total − servicio en vehículo − Delivery. En clientes, la misma
 *    resta con los coches de servicio en vehículo y los pedidos de Delivery.
 *  - Ticket medio = neto / guest counts. Sin guest counts NO se muestra.
 *  - Desviación = real − previsto, en euros y en porcentaje.
 *  - Los tiempos de servicio del día NO se calculan aquí: llegan de la fila de
 *    totales de la fuente de ventas, que los pondera por pedidos y coches (ver `ServiceTimes`).
 *
 * Ninguna función devuelve 0 para tapar un hueco: cuando falta el dato,
 * devuelve null y la interfaz muestra una raya.
 */

import type { DayTotals, HourRow, Light } from "./types";

/** Umbral ámbar del diseño: hasta un 12 % por encima del objetivo. */
const WARN_FACTOR = 1.12;

type Nullable = number | null | undefined;

function has(n: Nullable): n is number {
  return n !== null && n !== undefined && !Number.isNaN(n);
}

/** Venta neta / guest counts. Null si no hay guest counts: nunca cero. */
export function ticketMedio(net: Nullable, gc: Nullable): number | null {
  if (!has(net) || !has(gc) || gc === 0) return null;
  return net / gc;
}

/** Desviación frente a la previsión, en euros y en porcentaje. */
export function deviation(
  real: Nullable,
  proj: Nullable,
): { euros: number | null; pct: number | null } {
  if (!has(real) || !has(proj)) return { euros: null, pct: null };
  const euros = real - proj;
  // Se calcula desde la diferencia y no como (real/proj - 1): restar uno a un
  // cociente arrastra error de coma flotante (1100/1000 - 1 da 0,100000…09).
  // Sin previsión no hay porcentaje posible: no se inventa.
  const pct = proj === 0 ? null : (euros / proj) * 100;
  return { euros, pct };
}

/** Mostrador + kiosko de una hora. */
export function counterNet(row: Pick<HourRow, "net" | "drive_through_net" | "delivery_net">): number | null {
  if (!has(row.net) || !has(row.drive_through_net) || !has(row.delivery_net)) return null;
  return row.net - row.drive_through_net - row.delivery_net;
}

/**
 * Clientes de mostrador + kiosko de una hora.
 *
 * Misma resta que en euros, con las unidades de cada canal. La ausencia de
 * guest counts se conserva como nulo.
 */
export function counterGc(
  row: Pick<HourRow, "gc" | "drive_through_cars" | "delivery_count">,
): number | null {
  if (!has(row.gc) || !has(row.drive_through_cars) || !has(row.delivery_count)) return null;
  return row.gc - row.drive_through_cars - row.delivery_count;
}

/** Color del tiempo de servicio frente al objetivo del mes. */
export function serviceLight(value: Nullable, objective: Nullable): Light {
  if (!has(value) || !has(objective)) return "none";
  if (value <= objective) return "ok";
  if (value <= objective * WARN_FACTOR) return "warn";
  return "bad";
}

function sum(values: (number | null)[]): number | null {
  const presentes = values.filter(has);
  return presentes.length === 0 ? null : presentes.reduce((a, b) => a + b, 0);
}

/**
 * Totales del día.
 *
 * `projToNow` suma solo la previsión de las horas que ya tienen venta real.
 * Sumar la del día entero daría una desviación negativa toda la mañana por el
 * simple hecho de que el día no ha terminado.
 *
 * Aquí no hay tiempos de servicio a propósito: los del día los da la fuente de ventas en su
 * fila de totales diarios del contrato público.
 */
export function aggregate(rows: HourRow[], options?: { excludeHour?: number }): DayTotals {
  const excluida = options?.excludeHour;
  const considerar = excluida === undefined ? rows : rows.filter((r) => r.hour !== excluida);
  const conVenta = considerar.filter((r) => has(r.net));
  return {
    net: sum(conVenta.map((r) => r.net)),
    gc: sum(conVenta.map((r) => r.gc)),
    projToNow: sum(conVenta.map((r) => r.proj_sales)),
    projDay: sum(rows.map((r) => r.proj_sales)),
    projGcToNow: sum(conVenta.map((r) => r.proj_gc)),
  };
}

/** La fila de una hora concreta, o null si esa hora no tiene datos. */
export function currentHourRow(rows: HourRow[], hour: number): HourRow | null {
  return rows.find((r) => r.hour === hour && has(r.net)) ?? null;
}

/**
 * El personal de la hora que se está viviendo, para la tarjeta del resumen.
 *
 * En un día en curso interesa quién está dentro AHORA, así que se toma la hora
 * en curso aunque vaya a medias. En un día cerrado no hay hora en curso: se
 * toma la última que llegó a tener gente —fichada o asignada—, que es el
 * cierre del turno.
 *
 * Las horas de 0/0 no valen aunque sean las últimas: el worker emite filas de
 * madrugada que existen solo para enseñar un fichaje recortado, y con el local
 * ya cerrado ganaban por llegar al final. La tarjeta pintaba "0/0 ⚠" en lugar
 * del cierre de turno, y encima marcando una hora que la tabla esconde. Si no
 * queda ninguna hora con gente se devuelve null y la tarjeta enseña raya: un
 * 0/0 afirmaría que en el cierre del turno no había nadie, que es otra cosa.
 *
 * Se arrastra también `clipped`, el aviso de fichaje sin cerrar de ESA misma
 * hora: la tarjeta y la tabla enseñan la misma cifra y tienen que decir lo
 * mismo de ella, o la marca aparece solo al entrar en el local.
 */
export function liveStaffing(
  rows: HourRow[],
  currentHour: number | null,
): { clocked: number | null; assigned: number | null; clipped: number | null } | null {
  const desde = (r: HourRow) => ({ clocked: r.clocked, assigned: r.assigned, clipped: r.clipped });
  if (currentHour !== null) {
    const fila = rows.find((r) => r.hour === currentHour);
    if (fila && fila.assigned !== null) return desde(fila);
    return null;
  }
  const conGente = rows.filter(
    (r) => r.clocked !== null && r.assigned !== null && (r.assigned > 0 || r.clocked > 0),
  );
  const ultima = conGente[conGente.length - 1];
  return ultima ? desde(ultima) : null;
}
