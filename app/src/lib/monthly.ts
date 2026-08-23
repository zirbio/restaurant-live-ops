/**
 * Cálculos de la pantalla del mes.
 *
 * Un mes no se lee solo: se lee comparándolo. Contra el objetivo, contra el
 * mismo mes del año pasado y contra España. Aquí están las cuatro reglas que
 * gobiernan esas comparaciones, y las cuatro existen porque su alternativa
 * produce una cifra falsa:
 *
 *  1. **Una sola ventana.** Venta, objetivo, interanual y horas se cortan
 *     todos por el último día CERRADO. Comparar la venta acumulada a día 5
 *     contra el objetivo de 31 días da un −85 % que no ha ocurrido.
 *  2. **Interanual sobre días comparables.** Solo cuentan los días con dato en
 *     los dos años. Un hueco en el año pasado inflaría el crecimiento.
 *  3. **Tiempos ponderados por guest counts, y nunca entre restaurantes.** La
 *     media simple sale 1-2 segundos por debajo porque los días de más volumen
 *     son los más lentos, y con eso basta para dar por cumplido un objetivo que
 *     no lo está.
 *  4. **Nada se rellena con ceros.** Sin dato, `null`, y la pantalla enseña
 *     raya.
 */

import { daysInMonth, monthKeyOf, priorYearDay, type MonthKey } from "./month";
import type { DailyQuality } from "./types";

/** Un día de venta real del contrato diario público. */
export interface MonthDayRow {
  restaurant_id: string;
  sales_date: string;
  /** Suma horaria propia: la cifra exacta. `net` viene redondeado por la fuente de ventas. */
  hourly_net_sum: number | null;
  gc: number | null;
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
  /** GC de la misma fecha de caja que los tiempos; ausente en el histórico. */
  service_time_gc?: number | null;
  /** Solo en la vista la fuente de ventas nueva; el histórico anterior no la tenía. */
  quality?: DailyQuality;
}

/** Venta y guest counts de un día de un año anterior. */
export interface PriorDayRow {
  restaurant_id: string;
  sales_date: string;
  net: number | null;
  gc: number | null;
}

/**
 * La previsión de venta y clientes para un día.
 */
export interface ProjectionRow {
  restaurant_id: string;
  sales_date: string;
  projected_net: number | null;
  projected_gc: number | null;
}

export interface HoursRow {
  restaurant_id: string;
  sales_date: string;
  clocked_hours: number | null;
}


export interface CostParamsRow {
  restaurant_id: string;
  fixed_cost_month: number;
  variable_cost_hour: number;
  calibrated_at: string;
  valid_from: string;
  valid_to: string | null;
}

export interface PctTargetRow {
  restaurant_id: string;
  year: number;
  month: number;
  target_pct: number | null;
  target_mo_eur: number | null;
  target_sales_eur: number | null;
}

export interface NationalRow {
  year: number;
  month: number;
  sales_yoy_pct: number;
  covers_through: string | null;
  closed: boolean;
}

/** Comparable de España de un mes, y hasta qué día llega. */
export interface NationalComparable {
  yoyPct: number;
  /** Último día completo que incluye la cifra. */
  coversThrough: string;
  /** false = mes en curso; la cifra seguirá moviéndose. */
  closed: boolean;
}

/**
 * El comparable de España, solo si cubre los mismos días que la ventana.
 *
 * España se lee del panel de la fuente de ventas una vez al día, y cada lectura trae el
 * acumulado del mes hasta la víspera. Eso permite seguir el mes en curso sin
 * esperar a que cierre, pero obliga a comprobar el corte: enfrentar un
 * acumulado que llega al día 12 con una ventana propia que termina el 15
 * compararía dos periodos distintos y llamaría "vs ES" a la diferencia.
 *
 * Cuando no coinciden se devuelve nulo y la pantalla enseña raya, que es lo
 * correcto: el hueco de un día se rellena solo con la lectura siguiente.
 */
export function nationalYoy(
  entry: NationalComparable | null | undefined,
  windowEnd: string | null,
): number | null {
  if (!entry || windowEnd === null) return null;
  return entry.coversThrough === windowEnd ? entry.yoyPct : null;
}

/**
 * Suelo de credibilidad de un tiempo diario, en segundos. Las exclusiones se
 * contabilizan para que la interfaz no presente una media como completa.
 */
export const MIN_PLAUSIBLE_SECONDS = 30;

type Nullable = number | null | undefined;

function has(n: Nullable): n is number {
  return n !== null && n !== undefined && !Number.isNaN(n);
}

function sum(values: Nullable[]): number | null {
  const presentes = values.filter(has);
  return presentes.length === 0 ? null : presentes.reduce((a, b) => a + b, 0);
}

/** Índice por `restaurante|día`, que es como se cruzan todas estas tablas. */
export function byDay<T extends { restaurant_id: string; sales_date: string }>(
  rows: T[],
): Map<string, T> {
  return new Map(rows.map((r) => [`${r.restaurant_id}|${r.sales_date}`, r]));
}

export interface MonthTotals {
  /** Venta real de los días de la ventana que la tienen. */
  net: number | null;
  gc: number | null;
  /**
   * Previsión de TODOS los días de la ventana, tengan captura de la fuente de ventas o no. Un
   * día que la fuente de ventas no llegó a capturar sigue teniendo previsión, y quitárselo
   * encogería la meta hasta hacerla cuadrar sola.
   *
   * `targetDays` y `targetGcDays` dicen sobre cuántos días se ha podido sumar.
   * Si no llegan a `expectedDays` la cifra está corta y NO se publica: la
   * previsión de la fuente de personal, a diferencia del plan base, solo existe para los días que
   * el worker capturó, y una meta corta hace que la desviación parezca mejor
   * de lo que es. Lo decide `publishableTarget`.
   */
  target: number | null;
  targetGc: number | null;
  targetDays: number;
  targetGcDays: number;
  /** Días de la ventana con venta real, y días que debería haber. */
  days: number;
  expectedDays: number;
  /** Interanual: solo los días con dato en los dos años. */
  comparableDays: number;
  comparableNet: number | null;
  priorNet: number | null;
  comparableGcDays: number;
  comparableGc: number | null;
  priorGc: number | null;
  /** Horas fichadas de la ventana. `hoursDays` dice sobre cuántos días. */
  hours: number | null;
  hoursDays: number;
  /**
   * Venta y horas de los días que tienen LAS DOS COSAS. Es lo único con lo que
   * se puede calcular un VPHH: dividir la venta de treinta días entre las horas
   * de veintiocho da euros por hora que nadie ha trabajado.
   */
  pairedNet: number | null;
  pairedHours: number | null;
  pairedDays: number;
  /** Lo mismo del año anterior, y solo de los días emparejados en los dos años. */
  priorPairedNet: number | null;
  priorPairedHours: number | null;
  priorPairedDays: number;
}

const VACIO: MonthTotals = {
  net: null,
  gc: null,
  target: null,
  targetGc: null,
  targetDays: 0,
  targetGcDays: 0,
  days: 0,
  expectedDays: 0,
  comparableDays: 0,
  comparableNet: null,
  priorNet: null,
  comparableGcDays: 0,
  comparableGc: null,
  priorGc: null,
  hours: null,
  hoursDays: 0,
  pairedNet: null,
  pairedHours: null,
  pairedDays: 0,
  priorPairedNet: null,
  priorPairedHours: null,
  priorPairedDays: 0,
};

export interface MonthSources {
  restaurantId: string;
  /**
   * Todos los días de la VENTANA, del 1 al último cerrado, vengan o no en la
   * captura. Se pasan como calendario y no como filas a propósito: el objetivo
   * y el recuento de días que faltan necesitan saber qué días DEBERÍA haber.
   */
  calendarDays: string[];
  /** Venta real indexada por `restaurante|día`. */
  real: Map<string, MonthDayRow>;
  /** Venta del año anterior, indexada igual. */
  prior: Map<string, PriorDayRow>;
  /** Previsión de la fuente de personal por día, indexada igual. */
  targets: Map<string, ProjectionRow>;
  hours: Map<string, HoursRow>;
}

/**
 * Totales de un mes para un restaurante y una ventana de días.
 *
 * Cada cifra dice sobre cuántos días se ha calculado, y ninguna se mezcla con
 * otra que cubra días distintos. Es la regla que evita el error más caro de
 * esta pantalla: comparar un numerador y un denominador que no hablan del
 * mismo periodo.
 */
export function monthTotals(sources: MonthSources): MonthTotals {
  if (sources.calendarDays.length === 0) return { ...VACIO };

  const clave = (dia: string) => `${sources.restaurantId}|${dia}`;

  let net = 0;
  let gc = 0;
  let days = 0;
  let gcDays = 0;

  let comparableNet = 0;
  let priorNet = 0;
  let comparableDays = 0;
  let comparableGc = 0;
  let priorGc = 0;
  let comparableGcDays = 0;

  let horas = 0;
  let hoursDays = 0;
  let pairedNet = 0;
  let pairedHours = 0;
  let pairedDays = 0;
  let priorPairedNet = 0;
  let priorPairedHours = 0;
  let priorPairedDays = 0;

  for (const dia of sources.calendarDays) {
    const real = sources.real.get(clave(dia));
    const venta = real?.hourly_net_sum ?? null;
    const anterior = sources.prior.get(clave(priorYearDay(dia)));
    const horasDelDia = sources.hours.get(clave(dia))?.clocked_hours ?? null;
    const horasAnteriores = sources.hours.get(clave(priorYearDay(dia)))?.clocked_hours ?? null;

    if (has(venta)) {
      net += venta;
      days += 1;
      if (has(real?.gc)) {
        gc += real.gc;
        gcDays += 1;
      }
    }
    if (has(horasDelDia)) {
      horas += horasDelDia;
      hoursDays += 1;
    }
    // VPHH: solo los días que traen venta Y horas.
    if (has(venta) && has(horasDelDia)) {
      pairedNet += venta;
      pairedHours += horasDelDia;
      pairedDays += 1;
    }

    if (!has(venta) || !anterior || !has(anterior.net)) continue;
    comparableDays += 1;
    comparableNet += venta;
    priorNet += anterior.net;
    // Los guest counts se emparejan aparte: un día puede traer venta en los
    // dos años y guest counts en uno solo, y mezclar las dos poblaciones daría
    // un crecimiento de clientes que no se ha medido.
    if (has(real?.gc) && has(anterior.gc)) {
      comparableGcDays += 1;
      comparableGc += real.gc;
      priorGc += anterior.gc;
    }
    // Y el VPHH del año anterior, sobre los días que aquel año tuvieron venta
    // Y horas. Si no, se dividiría la venta de un conjunto de días entre las
    // horas de otro.
    if (has(horasAnteriores)) {
      priorPairedNet += anterior.net;
      priorPairedHours += horasAnteriores;
      priorPairedDays += 1;
    }
  }

  const objetivos = sources.calendarDays.map(
    (d) => sources.targets.get(clave(d))?.projected_net ?? null,
  );
  const objetivosGc = sources.calendarDays.map(
    (d) => sources.targets.get(clave(d))?.projected_gc ?? null,
  );

  return {
    net: days === 0 ? null : net,
    gc: gcDays === 0 ? null : gc,
    target: sum(objetivos),
    targetGc: sum(objetivosGc),
    targetDays: objetivos.filter(has).length,
    targetGcDays: objetivosGc.filter(has).length,
    days,
    expectedDays: sources.calendarDays.length,
    comparableDays,
    comparableNet: comparableDays === 0 ? null : comparableNet,
    priorNet: comparableDays === 0 ? null : priorNet,
    comparableGcDays,
    comparableGc: comparableGcDays === 0 ? null : comparableGc,
    priorGc: comparableGcDays === 0 ? null : priorGc,
    hours: hoursDays === 0 ? null : horas,
    hoursDays,
    pairedNet: pairedDays === 0 ? null : pairedNet,
    pairedHours: pairedDays === 0 ? null : pairedHours,
    pairedDays,
    priorPairedNet: priorPairedDays === 0 ? null : priorPairedNet,
    priorPairedHours: priorPairedDays === 0 ? null : priorPairedHours,
    priorPairedDays,
  };
}

/**
 * Suma dos totales para la vista de conjunto, sin inventar ceros.
 *
 * Los recuentos de días se suman también: es lo que permite exigir después que
 * el VPHH del conjunto salga de locales cuyas horas cubren TODOS sus días, y
 * no de dos restaurantes con horas y uno sin ellas.
 */
export function addTotals(a: MonthTotals, b: MonthTotals): MonthTotals {
  return {
    net: sum([a.net, b.net]),
    gc: sum([a.gc, b.gc]),
    target: sum([a.target, b.target]),
    targetGc: sum([a.targetGc, b.targetGc]),
    targetDays: a.targetDays + b.targetDays,
    targetGcDays: a.targetGcDays + b.targetGcDays,
    days: a.days + b.days,
    expectedDays: a.expectedDays + b.expectedDays,
    comparableDays: a.comparableDays + b.comparableDays,
    comparableNet: sum([a.comparableNet, b.comparableNet]),
    priorNet: sum([a.priorNet, b.priorNet]),
    comparableGcDays: a.comparableGcDays + b.comparableGcDays,
    comparableGc: sum([a.comparableGc, b.comparableGc]),
    priorGc: sum([a.priorGc, b.priorGc]),
    hours: sum([a.hours, b.hours]),
    hoursDays: a.hoursDays + b.hoursDays,
    pairedNet: sum([a.pairedNet, b.pairedNet]),
    pairedHours: sum([a.pairedHours, b.pairedHours]),
    pairedDays: a.pairedDays + b.pairedDays,
    priorPairedNet: sum([a.priorPairedNet, b.priorPairedNet]),
    priorPairedHours: sum([a.priorPairedHours, b.priorPairedHours]),
    priorPairedDays: a.priorPairedDays + b.priorPairedDays,
  };
}

/** Crecimiento porcentual. Null si falta cualquiera de los dos lados. */
export function growthPct(current: Nullable, prior: Nullable): number | null {
  if (!has(current) || !has(prior) || prior === 0) return null;
  return ((current - prior) / prior) * 100;
}

/** Diferencial en puntos porcentuales frente a España. */
export function differencePp(own: Nullable, national: Nullable): number | null {
  if (!has(own) || !has(national)) return null;
  return own - national;
}

/** Venta por hora trabajada. Sin horas no hay VPHH: nunca es cero. */
export function vphh(net: Nullable, hours: Nullable): number | null {
  if (!has(net) || !has(hours) || hours === 0) return null;
  return net / hours;
}

/**
 * Coste estimado de mano de obra del periodo.
 *
 *   coste = fijo del mes × (días cubiertos / días del mes) + marginal × horas
 *
 * El fijo se prorratea por días cubiertos. El resultado siempre se identifica
 * como estimación; un cierre real, cuando existe, tiene prioridad.
 */
export function estimatedLaborCost(
  params: CostParamsRow | undefined,
  { hours, coveredDays, month }: { hours: Nullable; coveredDays: number; month: MonthKey },
): number | null {
  if (!params || !has(hours) || coveredDays <= 0) return null;
  const proporcion = Math.min(1, coveredDays / daysInMonth(month));
  return params.fixed_cost_month * proporcion + params.variable_cost_hour * hours;
}

/** Coste de mano de obra sobre venta, en porcentaje. */
export function laborPct(cost: Nullable, net: Nullable): number | null {
  if (!has(cost) || !has(net) || net === 0) return null;
  return (cost / net) * 100;
}

/**
 * Objetivo de mano de obra del conjunto.
 *
 * No es la media de los tres porcentajes: es la suma de los costes
 * presupuestados entre la suma de las ventas presupuestadas. Con locales de
 * tamaños tan distintos, la media simple se desvía del objetivo de verdad.
 */
export function blendedLaborTarget(rows: PctTargetRow[], expected: number): number | null {
  // Con dos objetivos de tres, el porcentaje que sale es el de una plantilla
  // que no es la del titular: mejor raya que una meta de otro conjunto.
  if (expected <= 0 || rows.length !== expected) return null;
  const mo = sum(rows.map((r) => r.target_mo_eur));
  const venta = sum(rows.map((r) => r.target_sales_eur));
  if (!has(mo) || !has(venta) || venta === 0) return null;
  return (mo / venta) * 100;
}

/**
 * ¿Cubren las horas fichadas TODOS los días de la ventana?
 *
 * Es la condición que decide si el VPHH y la mano de obra se publican. Vive
 * aquí y no en el componente porque es la regla de más riesgo de la pantalla:
 * relajarla a `>=` devolvería en silencio el defecto que existe para evitar
 * —venta de treinta y un días dividida entre horas de veintiocho—.
 */
export function hasFullHourCoverage(t: MonthTotals): boolean {
  return t.expectedDays > 0 && t.pairedDays === t.expectedDays;
}

/** Lo mismo para el año anterior, que es el otro lado del interanual. */
export function hasFullPriorHourCoverage(t: MonthTotals): boolean {
  return t.expectedDays > 0 && t.priorPairedDays === t.expectedDays;
}

/**
 * La previsión del periodo, o null si le falta algún día de la ventana.
 *
 * La misma exigencia que el VPHH, y por el mismo motivo: la suma se salta los
 * días que no tienen fila, así que una previsión incompleta se compara contra
 * la venta ENTERA y la desviación sale mejor de lo que es. La previsión solo
 * existe para los días que el worker capturó: hoy son los 642 de 642 del rango
 * navegable, pero eso hay que comprobarlo, no suponerlo.
 */
export function publishableTarget(t: MonthTotals): number | null {
  return t.expectedDays > 0 && t.targetDays === t.expectedDays ? t.target : null;
}

/** Ídem para los clientes, contado aparte: puede faltar uno y no el otro. */
export function publishableTargetGc(t: MonthTotals): number | null {
  return t.expectedDays > 0 && t.targetGcDays === t.expectedDays ? t.targetGc : null;
}

/** Días de la ventana sin previsión, para poder decir por qué falta la cifra. */
export function missingTargetDays(t: MonthTotals): number {
  return Math.max(0, t.expectedDays - Math.min(t.targetDays, t.targetGcDays));
}

/** VPHH del periodo, o null si las horas no cubren la ventana entera. */
export function publishableVphh(t: MonthTotals): number | null {
  return hasFullHourCoverage(t) ? vphh(t.pairedNet, t.pairedHours) : null;
}

/** VPHH del año anterior, con la misma exigencia de cobertura. */
export function publishablePriorVphh(t: MonthTotals): number | null {
  return hasFullPriorHourCoverage(t) ? vphh(t.priorPairedNet, t.priorPairedHours) : null;
}

/** Coste estimado de mano de obra, o null si las horas no cubren la ventana. */
export function publishableLaborCost(
  t: MonthTotals,
  params: CostParamsRow | undefined,
  month: MonthKey,
): number | null {
  if (!hasFullHourCoverage(t)) return null;
  return estimatedLaborCost(params, {
    hours: t.hours,
    coveredDays: t.expectedDays,
    month,
  });
}

/** Coste real de la mano de obra de un mes ya cerrado, del P&L de la fuente mensual. */
export interface PlLaborActualRow {
  restaurant_id: string;
  year: number;
  month: number;
  /** Mano de Obra + Dirección + Seguridad Social. Lo suma la base. */
  total_labor_eur: number;
  /** Venta neta del MISMO P&L: el denominador del %MO real. */
  net_sales_eur: number;
}

export interface PublishedLaborCost {
  cost: number;
  /**
   * Denominador del %MO. Con el coste real es la venta del P&L, para que la
   * cifra salga entera de una sola fuente; con la estimación es nulo y manda la
   * venta que ya tiene la pantalla.
   */
  net: number | null;
  source: "real" | "estimado";
}

/**
 * El coste de mano de obra que se publica, y de dónde sale.
 *
 * El cierre real tiene prioridad. Si aún no existe, se conserva la estimación
 * identificada como tal.
 */
export function publishedLaborCost(
  actuals: PlLaborActualRow[],
  restaurantId: string,
  month: MonthKey,
  estimated: number | null,
): PublishedLaborCost | null {
  const [anio, mes] = month.split("-").map(Number) as [number, number];
  const fila = actuals.find(
    (a) => a.restaurant_id === restaurantId && a.year === anio && a.month === mes,
  );
  if (fila) {
    return { cost: fila.total_labor_eur, net: fila.net_sales_eur, source: "real" };
  }
  if (!has(estimated)) return null;
  return { cost: estimated, net: null, source: "estimado" };
}

/** El coste publicado de un local, emparejado con SU venta de la fuente de ventas de reserva. */
export interface LaborCostEntry {
  published: PublishedLaborCost | null;
  /** Venta de la fuente de ventas del local: el denominador cuando el coste es estimado. */
  sourceNet: number | null;
}

export interface BlendedLaborCost {
  /** Coste y venta del conjunto, o null si a algún local le falta alguno. */
  cost: number | null;
  net: number | null;
  /** Cuántos locales publican coste real del P&L, no estimación. */
  realCount: number;
}

/**
 * Mezcla el coste y la venta de mano de obra de varios locales para un Total.
 *
 * Numerador y denominador van EMPAREJADOS por local: si un local publica
 * coste real, su venta es la del P&L (`published.net`); si publica
 * estimación, es la venta de la fuente de ventas que ya tiene la pantalla (`sourceNet`).
 * Mezclar el coste contable de un local con la venta de otra fuente daría un
 * %MO que no es ni el uno ni el otro.
 *
 * `realCount` se cuenta siempre, aunque a algún local le falte el coste: es lo
 * que decide la palabra del pie («estimado» / «real» / «real en N de 3»), y
 * esa frase sigue teniendo sentido aunque el Total no se pueda sumar entero.
 *
 * El Total (`cost`/`net`) solo sale si TODOS los locales tienen coste Y una
 * venta con la que emparejarlo. Sin eso se prefiere el hueco a una suma a la
 * que le falta un tercio, o a rellenar el hueco con un cero que nadie ha
 * medido — ese caso no debería darse (`hasFullHourCoverage` ya garantiza que
 * un local con estimación siempre trae su propia venta de la fuente de ventas), pero si
 * algún día dejara de darse, es mejor una raya que un %MO fabricado.
 */
export function blendedLaborCost(entries: LaborCostEntry[]): BlendedLaborCost {
  const realCount = entries.filter((e) => e.published?.source === "real").length;

  const netes = entries.map((e) => e.published?.net ?? e.sourceNet);
  const completo =
    entries.length > 0 && entries.every((e) => e.published !== null) && netes.every(has);

  if (!completo) return { cost: null, net: null, realCount };

  return {
    cost: entries.reduce((total, e) => total + e.published!.cost, 0),
    net: netes.reduce<number>((total, n) => total + (n as number), 0),
    realCount,
  };
}

export type ServiceMetric = "kvs" | "r2p" | "oepe";

/** Las tres métricas, en el orden en el que se leen en pantalla. */
export const SERVICE_METRICS: ServiceMetric[] = ["kvs", "r2p", "oepe"];

export interface WeightedTime {
  value: number | null;
  /** Días que han pesado en la media. */
  days: number;
  /** Días descartados por traer un valor imposible. Se dicen en pantalla. */
  excluded: number;
  /** Días efectivos sin un tiempo que se pueda imputar con exactitud. */
  unavailable: number;
}

/**
 * Tiempo de servicio del mes, ponderado por guest counts.
 *
 * Un día sin la métrica o sin clientes no cuenta como cero. Los días efectivos
 * incompletos invalidan la media para evitar presentar una cobertura parcial.
 */
export function weightedServiceTime(days: MonthDayRow[], metric: ServiceMetric): WeightedTime {
  let numerador = 0;
  let peso = 0;
  let contados = 0;
  let excluidos = 0;
  let noDisponibles = 0;

  for (const d of days) {
    const valor = d[metric];
    const pesoDelTiempo = d.service_time_gc === undefined ? d.gc : d.service_time_gc;
    if (!has(valor)) {
      // Los días efectivos sí declaran calidad. Si tienen clientes pero no
      // tiempo, omitirlos produciría una media parcial con apariencia de mes
      // completo. El histórico sin `quality` conserva su semántica anterior.
      if (d.quality !== undefined && has(d.gc) && d.gc > 0) noDisponibles += 1;
      continue;
    }
    if (!has(pesoDelTiempo) || pesoDelTiempo <= 0) {
      if (d.quality !== undefined && has(d.gc) && d.gc > 0) noDisponibles += 1;
      continue;
    }
    if (valor < MIN_PLAUSIBLE_SECONDS) {
      excluidos += 1;
      continue;
    }
    numerador += valor * pesoDelTiempo;
    peso += pesoDelTiempo;
    contados += 1;
  }

  return {
    value: peso === 0 || noDisponibles > 0 ? null : numerador / peso,
    days: contados,
    excluded: excluidos,
    unavailable: noDisponibles,
  };
}

/**
 * Días DISTINTOS con algún tiempo por debajo del suelo de credibilidad.
 *
 * Se cuentan días, no exclusiones por métrica: un día con el KVS roto y otro
 * con el R2P roto son dos días fuera, y quedarse con el máximo de cada métrica
 * los reduciría a uno. El aviso existe para que nadie tome la media por
 * completa, así que quedarse corto lo vacía de sentido.
 *
 * `metrics` acota qué métricas cuentan cuando la interfaz combina fuentes.
 */
export function implausibleDays(
  days: MonthDayRow[],
  metrics: readonly ServiceMetric[] = SERVICE_METRICS,
): number {
  return days.filter((d) =>
    metrics.some((m) => {
      const v = d[m];
      return has(v) && v < MIN_PLAUSIBLE_SECONDS;
    }),
  ).length;
}

/** Un punto de la tendencia: el mes y sus tres tiempos ya ponderados. */
export interface TrendPoint {
  month: MonthKey;
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
}

/**
 * Tendencia mensual de los tres tiempos.
 *
 * Cada mes se calcula con sus propios días. Un mes sin datos conserva un hueco
 * para no dibujar una evolución inexistente.
 */
export function serviceTrend(days: MonthDayRow[], months: MonthKey[]): TrendPoint[] {
  const porMes = new Map<MonthKey, MonthDayRow[]>();
  for (const d of days) {
    const mes = monthKeyOf(d.sales_date);
    const lista = porMes.get(mes);
    if (lista) lista.push(d);
    else porMes.set(mes, [d]);
  }
  return months.map((month) => {
    const delMes = porMes.get(month) ?? [];
    return {
      month,
      kvs: weightedServiceTime(delMes, "kvs").value,
      r2p: weightedServiceTime(delMes, "r2p").value,
      oepe: weightedServiceTime(delMes, "oepe").value,
    };
  });
}

/** El parámetro de coste vigente ese mes, o `undefined` si no lo hay. */
export function costParamsFor(
  params: CostParamsRow[],
  restaurantId: string,
  windowEnd: string,
): CostParamsRow | undefined {
  return params
    .filter(
      (p) =>
        p.restaurant_id === restaurantId &&
        p.valid_from <= windowEnd &&
        (p.valid_to === null || p.valid_to >= windowEnd),
    )
    .sort((a, b) => b.valid_from.localeCompare(a.valid_from))[0];
}

/**
 * El cierre proyectado del mes, tal como lo calculó la fuente mensual.
 *
 * Se consume como un hecho publicado por la fuente mensual; la aplicación no
 * lo recalcula con datos parciales.
 */
export interface MonthProjectionRow {
  restaurant_id: string;
  year: number;
  month: number;
  /** Cuándo la calculó la fuente mensual. Si el puente no corre, envejece. */
  computed_at: string;
  days_in_month: number;
  days_actual: number;
  days_scheduled: number;
  days_reference: number;
  sales_projected: number;
  hours_projected: number;
  labor_cost_projected: number;
}

/** La proyección de un restaurante y un mes, o null si no la hay. */
export function closingFor(
  rows: MonthProjectionRow[],
  restaurantId: string,
  month: MonthKey,
): MonthProjectionRow | null {
  const [anio, mes] = month.split("-").map(Number) as [number, number];
  return (
    rows.find((r) => r.restaurant_id === restaurantId && r.year === anio && r.month === mes) ??
    null
  );
}

/**
 * El cierre del conjunto: solo si TODOS los locales tienen proyección.
 *
 * Con dos de tres, el %MO que sale es el de un conjunto que no es el del
 * titular — la misma regla que `blendedLaborTarget`.
 */
export function closingTotal(
  rows: MonthProjectionRow[],
  restaurantIds: string[],
  month: MonthKey,
): { sales: number; cost: number } | null {
  const suyas = restaurantIds.map((id) => closingFor(rows, id, month));
  if (suyas.some((r) => r === null)) return null;
  return {
    sales: suyas.reduce((a, r) => a + r!.sales_projected, 0),
    cost: suyas.reduce((a, r) => a + r!.labor_cost_projected, 0),
  };
}

/** El reparto de días del pie del cierre: un número, o el rango si no coinciden. */
export interface ClosingDaysBreakdown {
  actual: string;
  scheduled: string;
  reference: string;
}

/**
 * El reparto de días que va en el pie del cierre, sin atribuir a todos el de
 * uno solo.
 *
 * Si los restaurantes no comparten el mismo reparto, se muestra el rango. No
 * se atribuye al conjunto la cobertura de una sola fila.
 */
export function closingDaysBreakdown(rows: MonthProjectionRow[]): ClosingDaysBreakdown | null {
  if (rows.length === 0) return null;
  const rango = (valores: number[]): string => {
    const min = Math.min(...valores);
    const max = Math.max(...valores);
    return min === max ? String(min) : `${min}-${max}`;
  };
  return {
    actual: rango(rows.map((r) => r.days_actual)),
    scheduled: rango(rows.map((r) => r.days_scheduled)),
    reference: rango(rows.map((r) => r.days_reference)),
  };
}

/**
 * La fecha de cálculo más antigua entre las proyecciones que se están
 * pintando, no la del primer local.
 *
 * Si a un local se le despublica el tope y su proyección deja de refrescarse
 * mientras las otras dos siguen, la fecha del PRIMERO escondería justo la
 * vieja: la más antigua es la que de verdad avisa de un puente atascado.
 */
export function closingOldestComputedAt(rows: MonthProjectionRow[]): string | null {
  if (rows.length === 0) return null;
  return rows.reduce((masAntigua, r) => {
    return new Date(r.computed_at).getTime() < new Date(masAntigua).getTime()
      ? r.computed_at
      : masAntigua;
  }, rows[0]!.computed_at);
}
