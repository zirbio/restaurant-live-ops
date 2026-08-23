/**
 * Las cintas de tiempos que van bajo la curva de la tarjeta de cada local.
 *
 * La curva dice cómo va la venta hora a hora; las cintas dicen cómo iba el
 * servicio en esas mismas horas. Una fila por métrica —miden cosas distintas y
 * no comparten vara— y una celda por hora, con el semáforo del objetivo del MES.
 *
 * Se juzga cada hora con `serviceLight`, el mismo umbral que la tabla horaria y
 * que la vista mensual: una cifra no puede salir verde en un sitio y ámbar en
 * otro. Aquí no se promedia ni se rellena nada: la hora sin tiempo medido se
 * queda sin luz, nunca en verde por defecto.
 *
 * Una métrica sin una sola luz no dibuja cinta. Los valores ausentes o sin
 * objetivo permanecen sin clasificación.
 */

import { serviceLight } from "./metrics";
import type { ServiceMetric } from "./serviceBands";
import type { HourRow, Light, Objectives } from "./types";

/** Una hora de la cinta. Lleva su hora consigo: la celda sabe a quién juzga. */
export interface RibbonCell {
  hour: number;
  light: Light;
}

export interface ServiceRibbon {
  metric: ServiceMetric;
  /** Una celda por hora, en el mismo orden en que llegaron las filas. */
  cells: RibbonCell[];
}

/**
 * Umbral de clientes para no clasificar horas sin volumen representativo. Se
 * aplica igual a las tres métricas; nunca convierte una ausencia en verde.
 */
export const MIN_GC_FOR_SERVICE_LIGHT = 10;

export function serviceRibbons(
  rows: HourRow[],
  objectives: Objectives | null,
  hasDriveThrough: boolean,
): ServiceRibbon[] {
  const metricas: { metric: ServiceMetric; objetivo: number | null }[] = [
    { metric: "kvs", objetivo: objectives?.kvs ?? null },
    { metric: "r2p", objetivo: objectives?.r2p ?? null },
    // Sin servicio en vehículo no hay OEPE que juzgar, aunque la fuente trajera un número.
    { metric: "oepe", objetivo: hasDriveThrough ? (objectives?.oepe ?? null) : null },
  ];

  // Sin recuento de clientes no se puede saber si la hora tenía volumen, así
  // que tampoco se juzga: el hueco es preferible a un semáforo sin respaldo.
  const juzgable = (r: HourRow) => r.gc !== null && r.gc > MIN_GC_FOR_SERVICE_LIGHT;

  return metricas
    .map(({ metric, objetivo }) => ({
      metric,
      cells: rows.map((r) => ({
        hour: r.hour,
        light: juzgable(r) ? serviceLight(r[metric], objetivo) : ("none" as Light),
      })),
    }))
    .filter((cinta) => cinta.cells.some((c) => c.light !== "none"));
}
