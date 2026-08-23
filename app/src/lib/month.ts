/**
 * Meses de negocio, en Europe/Madrid.
 *
 * Un mes se identifica por su clave `YYYY-MM`. Como con los días, nada se
 * calcula con el reloj del dispositivo: el mes que está vivo es el del día de
 * NEGOCIO vivo, que hasta las 06:00 sigue siendo el de ayer. La madrugada del
 * 1 de agosto pertenece todavía a julio, y la vista mensual tiene que decir
 * julio.
 */

import { addDaysMadrid, businessTodayMadrid, isValidIsoDate } from "./tz";

const MADRID = "Europe/Madrid";

const MONTH_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

/** Clave de mes: `2026-07`. */
export type MonthKey = string;

const nombreLargo = new Intl.DateTimeFormat("es-ES", {
  timeZone: MADRID,
  month: "long",
  year: "numeric",
});

const nombreCorto = new Intl.DateTimeFormat("es-ES", { timeZone: MADRID, month: "short" });

const anioCorto = new Intl.DateTimeFormat("es-ES", { timeZone: MADRID, year: "2-digit" });

/**
 * Instante de mediodía UTC del día 15 del mes.
 *
 * El día 15 y el mediodía a propósito: ni el cambio de hora ni el desfase con
 * Madrid pueden sacarlo del mes al que pertenece. Anclar al día 1 a medianoche
 * daría el mes anterior media parte del año.
 */
function mediodiaDelMes(key: MonthKey): Date {
  const [y, m] = key.split("-").map(Number) as [number, number];
  return new Date(Date.UTC(y, m - 1, 15, 12));
}

export function isValidMonthKey(key: string): boolean {
  return MONTH_RE.test(key);
}

/** El mes al que pertenece un día `YYYY-MM-DD`. */
export function monthKeyOf(iso: string): MonthKey {
  return iso.slice(0, 7);
}

export function firstDayOfMonth(key: MonthKey): string {
  return `${key}-01`;
}

export function lastDayOfMonth(key: MonthKey): string {
  const [y, m] = key.split("-").map(Number) as [number, number];
  // El día 0 del mes siguiente es el último del actual, y `Date.UTC` ya sabe
  // de años bisiestos: no hay que decirle nada de febrero.
  const ultimo = new Date(Date.UTC(y, m, 0)).getUTCDate();
  return `${key}-${String(ultimo).padStart(2, "0")}`;
}

export function daysInMonth(key: MonthKey): number {
  return Number(lastDayOfMonth(key).slice(8));
}

/** Suma (o resta) meses sin salirse del calendario. */
export function addMonths(key: MonthKey, delta: number): MonthKey {
  const [y, m] = key.split("-").map(Number) as [number, number];
  const total = y * 12 + (m - 1) + delta;
  const anio = Math.floor(total / 12);
  const mes = total - anio * 12 + 1;
  return `${String(anio).padStart(4, "0")}-${String(mes).padStart(2, "0")}`;
}

/** Los meses del rango, extremos incluidos, en orden cronológico. */
export function monthRange(from: MonthKey, to: MonthKey): MonthKey[] {
  const meses: MonthKey[] = [];
  for (let k = from; k <= to; k = addMonths(k, 1)) meses.push(k);
  return meses;
}

/** `Julio 2026`, como en la cabecera del diseño. */
export function monthLabel(key: MonthKey): string {
  const crudo = nombreLargo.format(mediodiaDelMes(key)).replace(/ de /g, " ");
  return crudo.charAt(0).toUpperCase() + crudo.slice(1);
}

/** `JUL`, para el eje del gráfico de tendencia. */
export function monthAxisLabel(key: MonthKey): string {
  return nombreCorto
    .format(mediodiaDelMes(key))
    .replace(".", "")
    .toUpperCase()
    .slice(0, 3);
}

/** `jul 26`, para decir de dónde a dónde va una serie. */
export function monthShortLabel(key: MonthKey): string {
  const mes = nombreCorto.format(mediodiaDelMes(key)).replace(".", "");
  return `${mes} ${anioCorto.format(mediodiaDelMes(key))}`;
}

/**
 * El último día de negocio CERRADO.
 *
 * Un día no está cerrado hasta las 06:00 de Madrid del siguiente, así que el
 * último completo es siempre el anterior al día de negocio vivo. Es la línea
 * que gobierna toda la vista mensual: la venta, el objetivo, el interanual y
 * las horas se cortan aquí, todos por el mismo sitio.
 */
export function lastClosedDayMadrid(now: Date = new Date()): string {
  return addDaysMadrid(businessTodayMadrid(now), -1);
}

/**
 * Hasta dónde llega la ventana de un mes: su último día o el último cerrado.
 *
 * El día de cierre llega YA CALCULADO y no se consulta el reloj aquí: quien
 * pinta la pantalla y quien pide los datos tienen que estar de acuerdo en dónde
 * termina el mes, y si cada uno mira la hora por su cuenta, al cruzar las 06:00
 * la cabecera dice "31 días completos" sobre unas cifras que son de 30.
 *
 * Devuelve `null` si el mes todavía no tiene ningún día cerrado, que es lo que
 * pasa el día 1 de cada mes. Un mes sin días no es un mes con cero euros.
 */
export function monthWindowEndFor(key: MonthKey, lastClosed: string): string | null {
  const ultimo = lastDayOfMonth(key);
  const fin = lastClosed < ultimo ? lastClosed : ultimo;
  return fin < firstDayOfMonth(key) ? null : fin;
}

export const MONTH_PARAM = "m";

/**
 * Ajusta la clave que venga de la dirección web a algo que exista.
 *
 * Ni futuro ni antes del primer mes con datos. Como en el selector de día, una
 * clave ilegible no deja la pantalla en blanco: se ajusta al extremo más
 * cercano. Es navegación, no cifras: aquí no hay nada que fingir.
 */
export function resolveMonth(
  raw: string | null,
  {
    latest,
    earliest,
    fallback = latest,
  }: { latest: MonthKey; earliest: MonthKey; fallback?: MonthKey },
): MonthKey {
  // `fallback` y `latest` son cosas distintas: el tope es el mes vivo —una
  // dirección con `?m=2026-08` tiene que llevar allí— pero al abrir sin
  // parámetro se entra por el mes que se puede leer.
  const key = raw !== null && isValidMonthKey(raw) ? raw : fallback;
  if (key > latest) return latest;
  if (key < earliest) return earliest;
  return key;
}

/** El mismo día 364 días antes: el mismo día de la semana, 52 semanas atrás. */
export function priorYearDay(iso: string): string {
  return addDaysMadrid(iso, -YOY_SHIFT_DAYS);
}

/**
 * Desplazamiento del interanual: 364 días, no 365.
 *
 * 364 = 52 × 7, así que un sábado se compara siempre con un sábado. Es la
 * misma base que usa la fuente mensual en los seis sitios donde calcula un
 * interanual, y cambiarla aquí daría dos porcentajes distintos para el mismo
 * mes según qué herramienta se mire. El precio es que la ventana se desplaza
 * un día por año respecto al calendario.
 */
export const YOY_SHIFT_DAYS = 364;

/** Los días de un rango `YYYY-MM-DD`, extremos incluidos. */
export function daysBetween(start: string, end: string): string[] {
  if (!isValidIsoDate(start) || !isValidIsoDate(end) || end < start) return [];
  const dias: string[] = [];
  for (let d = start; d <= end; d = addDaysMadrid(d, 1)) dias.push(d);
  return dias;
}
