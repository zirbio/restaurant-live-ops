/**
 * Las tres franjas de la tendencia de tiempos, ya listas para dibujar.
 *
 * Una franja por métrica y no tres líneas sobre una misma escala: KVS, R2P y
 * OEPE miden cosas distintas y compartir eje solo sirve para aplastarlas. Con
 * la escala de cada una se ve su relieve, y sobre todo cabe la cifra de cada
 * mes, que es lo que se venía a leer.
 *
 * El OEPE solo existe en restaurantes con servicio en vehículo. Cada mes se
 * compara con su propio objetivo; sin objetivo no se asigna estado.
 */

import { serviceLight } from "./metrics";
import { monthKeyOf, type MonthKey } from "./month";
import {
  MIN_PLAUSIBLE_SECONDS,
  weightedServiceTime,
  type MonthDayRow,
  type TrendPoint,
} from "./monthly";
import type { Light, Objectives } from "./types";

export type ServiceMetric = "kvs" | "r2p" | "oepe";

/** R2P y OEPE de un mes tal como los publica la fuente de ventas. Sin KVS: no lo publica. */
export interface OfficialMonthlyTime {
  r2p: number | null;
  oepe: number | null;
}

/**
 * La tendencia mensual: lo que publica la fuente de ventas, y solo lo que no, derivado.
 *
 * R2P y OEPE conservan la cifra mensual publicada. KVS se deriva mediante una
 * media ponderada por clientes. Sin cifra oficial, R2P y OEPE quedan ausentes.
 */
export function officialTrend(
  days: MonthDayRow[],
  months: MonthKey[],
  official: Map<MonthKey, OfficialMonthlyTime>,
): TrendPoint[] {
  const porMes = new Map<MonthKey, MonthDayRow[]>();
  for (const d of days) {
    const mes = monthKeyOf(d.sales_date);
    const lista = porMes.get(mes);
    if (lista) lista.push(d);
    else porMes.set(mes, [d]);
  }

  return months.map((month) => {
    const suyo = official.get(month);
    return {
      month,
      kvs: weightedServiceTime(porMes.get(month) ?? [], "kvs").value,
      r2p: suyo?.r2p ?? null,
      oepe: suyo?.oepe ?? null,
    };
  });
}

/**
 * Evolución diaria de la media acumulada del mes.
 *
 * Cada punto responde a «¿qué acumulado oficial llevaba el mes al cerrar este
 * día?». El KVS conserva la ponderación por clientes que usa el panel de referencia. R2P y
 * OEPE se copian de la fotografía mensual oficial de la fuente de ventas, sin promediarlos ni
 * reconstruirlos desde los cierres diarios.
 *
 * Un día efectivo sin dato invalida los puntos siguientes de ESA métrica: no
 * se rellena con cero ni se presenta una media parcial como completa.
 */
export function cumulativeServiceTrend(
  days: MonthDayRow[],
  axisDays: string[] = [],
  officialSnapshots: ReadonlyMap<string, { r2p: number | null; oepe: number | null }> = new Map(),
): TrendPoint[] {
  const porFecha = new Map(days.map((d) => [d.sales_date, d]));
  const fechas = [...new Set(axisDays.length > 0 ? axisDays : days.map((d) => d.sales_date))].toSorted();
  const acumulados: MonthDayRow[] = [];
  let kvsIncompleto = false;

  return fechas.map((fecha) => {
    const dia = porFecha.get(fecha);
    const fotografia = officialSnapshots.get(fecha);
    const oficiales = { r2p: fotografia?.r2p ?? null, oepe: fotografia?.oepe ?? null };
    if (dia === undefined) {
      kvsIncompleto = true;
      return { month: fecha, kvs: null, ...oficiales };
    }
    acumulados.push(dia);

    if (
      dia.kvs !== null &&
      dia.kvs !== undefined &&
      !Number.isNaN(dia.kvs) &&
      dia.kvs < MIN_PLAUSIBLE_SECONDS
    ) {
      // `weightedServiceTime` excluye el valor imposible del cálculo. En una
      // curva acumulada eso no basta: seguir dibujando después aparentaría que
      // el mes está completo, así que el hueco queda abierto desde ese día.
      kvsIncompleto = true;
    }

    return {
      // `TrendPoint.month` es la clave horizontal de la serie. En esta vista
      // contiene el día completo para que cada punto y cada nodo sean únicos.
      month: fecha,
      kvs: kvsIncompleto ? null : weightedServiceTime(acumulados, "kvs").value,
      ...oficiales,
    };
  });
}

const METRICAS: { key: ServiceMetric; label: string }[] = [
  { key: "kvs", label: "KVS" },
  { key: "r2p", label: "R2P" },
  { key: "oepe", label: "OEPE" },
];

/**
 * Cuánto puede estirar la escala un objetivo lejano, en veces el recorrido de
 * los valores.
 *
 * El objetivo tiene que verse —una escalera fuera de la franja no dice nada—,
 * pero estirar la escala sin tope devuelve el defecto que este gráfico vino a
 * corregir: con valores entre 120" y 135" y un objetivo en 200", la serie
 * quedaría en una quinta parte de su franja y no se vería su relieve. Al doble
 * del recorrido, la serie nunca baja de la mitad de su franja.
 */
const ESTIRON_MAXIMO = 2;
/** Aire por debajo del mínimo, para que la línea no se pegue al suelo. */
const AIRE_ABAJO = 0.14;
/** Recorrido mínimo de una franja, en segundos, para una serie casi plana. */
const RECORRIDO_MINIMO = 12;

/**
 * El sitio que el dibujo necesita reservar arriba para la cifra de cada mes.
 *
 * Va en PÍXELES y lo manda el componente porque es él quien conoce el tamaño
 * de la letra, su desplazamiento y el alto de la franja. Cuando esto vivía
 * aquí como una fracción del recorrido, el margen real era de medio píxel y
 * nada ataba las dos mitades: subir la letra de 8,5 a 9 metía la cifra dentro
 * del rótulo de la cabecera sin que fallara ni un test.
 */
export interface Hueco {
  /** Alto del área de dibujo de una franja. */
  areaPx: number;
  /** Alto que ocupa la cifra por encima del punto más alto. */
  headroomPx: number;
}

const HUECO_POR_DEFECTO: Hueco = { areaPx: 46, headroomPx: 11.5 };

export interface BandValue {
  month: MonthKey;
  value: number | null;
  /** El objetivo de ese mes, o null si no se guardó ninguno. */
  objective: number | null;
  /** Cumplimiento de ese mes contra su propio objetivo. */
  light: Light;
}

export interface Band {
  key: ServiceMetric;
  label: string;
  values: BandValue[];
  /** Extremos de la escala vertical, con el aire ya incluido. */
  min: number;
  max: number;
  /**
   * El objetivo queda tan lejos que no cabe sin aplastar la serie.
   *
   * Su escalera NO se dibuja: pegarla al borde de la franja pondría una línea
   * en una altura que no le corresponde. El número exacto sigue en la cabecera
   * y el color de cada cifra sigue saliendo del objetivo de su mes, así que no
   * se pierde el veredicto, solo el dibujo.
   */
  objectiveOffScale: boolean;
}

/**
 * Una franja por métrica con algún valor.
 *
 * Una métrica sin datos no da franja: en un restaurante sin servicio en
 * vehículo, un recuadro vacío rotulado OEPE invita a buscar un dato inexistente.
 */
export function serviceBands(
  points: TrendPoint[],
  objectives: Map<MonthKey, Objectives>,
  hueco: Hueco = HUECO_POR_DEFECTO,
): Band[] {
  const bandas: Band[] = [];

  for (const m of METRICAS) {
    const values: BandValue[] = points.map((p) => {
      const objetivo = objectives.get(p.month)?.[m.key] ?? null;
      // Se juzga la cifra REDONDEADA, que es la que se enseña: con el valor
      // crudo, una media de 81,3 se imprimía "81" en ámbar bajo una cabecera
      // que decía «obj ≤ 81"», y otra de 80,6 imprimía el mismo "81" en verde.
      const valor = p[m.key] === null ? null : Math.round(p[m.key] as number);
      return {
        month: p.month,
        value: valor,
        objective: objetivo,
        light: serviceLight(valor, objetivo),
      };
    });

    if (values.every((v) => v.value === null)) continue;
    bandas.push({ ...m, values, ...escala(values, hueco) });
  }

  return bandas;
}

/**
 * Extremos de la franja.
 *
 * La escala abarca los valores y, si cabe, los objetivos: sin ellos la
 * escalera se saldría de la franja y el mes dejaría de tener contra qué
 * leerse. Pero el objetivo no manda sobre la escala —ver `ESTIRON_MAXIMO`—:
 * cuando queda demasiado lejos se le deja fuera y se dice.
 */
function escala(
  values: BandValue[],
  hueco: Hueco,
): { min: number; max: number; objectiveOffScale: boolean } {
  const valores = values.map((v) => v.value).filter((n): n is number => n !== null);
  const objetivos = values.map((v) => v.objective).filter((n): n is number => n !== null);

  const propio = Math.max(Math.max(...valores) - Math.min(...valores), RECORRIDO_MINIMO);
  const tope = propio * ESTIRON_MAXIMO;

  const cabe = [...valores, ...objetivos];
  const conObjetivos = Math.max(...cabe) - Math.min(...cabe);
  const objectiveOffScale = objetivos.length > 0 && conObjetivos > tope;

  const cifras = objectiveOffScale ? valores : cabe;
  const bajo = Math.min(...cifras);
  const alto = Math.max(...cifras);
  const recorrido = Math.max(alto - bajo, RECORRIDO_MINIMO);

  // El aire de arriba se pide en píxeles y se traduce a segundos: el resto de
  // la franja (`areaPx − headroomPx`) es lo que queda para el recorrido y el
  // aire de abajo.
  const util = Math.max(hueco.areaPx - hueco.headroomPx, 1);
  const porUnidad = (recorrido * (1 + AIRE_ABAJO)) / util;

  return {
    min: bajo - recorrido * AIRE_ABAJO,
    max: alto + hueco.headroomPx * porUnidad,
    objectiveOffScale,
  };
}

/**
 * Objetivos opcionales de servicio por restaurante y mes.
 *
 * El OEPE es el único que puede faltar, y significa "no aplica". El centinela
 * de origen se normaliza a nulo.
 */
export interface ObjectiveRow {
  restaurant_id: string;
  year: number;
  month: number;
  kvs: number;
  r2p: number;
  oepe: number | null;
}

/** Tiempos que la fuente mensual publica para un restaurante y mes. */
export interface OfficialTimeRow {
  restaurant_id: string;
  year: number;
  month: number;
  r2p: number | null;
  oepe: number | null;
}

/**
 * Indexa por restaurante y por mes.
 *
 * Dos niveles y no una clave compuesta porque cada franja se dibuja de un solo
 * restaurante: se busca su mapa una vez y luego se pregunta por meses.
 */
function byRestaurantAndMonth<F extends { restaurant_id: string; year: number; month: number }, T>(
  rows: F[],
  value: (row: F) => T,
): Map<string, Map<MonthKey, T>> {
  const indice = new Map<string, Map<MonthKey, T>>();

  for (const r of rows) {
    const suyos = indice.get(r.restaurant_id) ?? new Map<MonthKey, T>();
    suyos.set(`${r.year}-${String(r.month).padStart(2, "0")}`, value(r));
    indice.set(r.restaurant_id, suyos);
  }

  return indice;
}

/** Los objetivos de cada mes, para juzgar cada cifra con la vara de SU mes. */
export function objectivesByMonth(rows: ObjectiveRow[]): Map<string, Map<MonthKey, Objectives>> {
  return byRestaurantAndMonth(rows, (r) => ({
    restaurant_id: r.restaurant_id,
    kvs: r.kvs,
    r2p: r.r2p,
    oepe: r.oepe,
  }));
}

/** El R2P y el OEPE que publica la fuente de ventas, listos para `officialTrend`. */
export function officialTimesByMonth(
  rows: OfficialTimeRow[],
): Map<string, Map<MonthKey, OfficialMonthlyTime>> {
  return byRestaurantAndMonth(rows, (r) => ({ r2p: r.r2p, oepe: r.oepe }));
}

/**
 * Los meses que enseña el eje: desde el primero con dato hasta el final.
 *
 * Se recorta por DELANTE y solo por delante. Los meses anteriores al arranque
 * de la captura no pintan nada y dejarían medio gráfico en blanco, pero un mes
 * vacío de en medio SÍ se queda: quitarlo juntaría a sus dos vecinos y la
 * curva los uniría con un trazo continuo por encima de un hueco que nadie ha
 * medido, con el eje repartido en pasos iguales y ninguna pista de que falta
 * un mes. Y el último tampoco se recorta: es el que se está mirando, y su
 * ausencia de dato es en sí misma la respuesta.
 */
export function visibleTrendMonths(months: MonthKey[], withData: Set<MonthKey>): MonthKey[] {
  const primero = months.findIndex((m) => withData.has(m));
  return primero === -1 ? [] : months.slice(primero);
}

export interface SegmentPoint {
  /** Posición del mes en la serie: la línea se dibuja sobre el eje entero. */
  i: number;
  value: number;
}

/**
 * Tramos continuos de una serie.
 *
 * Un mes sin dato CORTA la línea. Unir por encima del hueco dibujaría una
 * evolución que nadie ha medido, y es indistinguible de una de verdad.
 */
export function trendSegments(values: BandValue[]): SegmentPoint[][] {
  const tramos: SegmentPoint[][] = [];
  let actual: SegmentPoint[] = [];

  values.forEach((v, i) => {
    if (v.value === null) {
      if (actual.length > 0) tramos.push(actual);
      actual = [];
      return;
    }
    actual.push({ i, value: v.value });
  });
  if (actual.length > 0) tramos.push(actual);

  return tramos;
}
