/**
 * Qué día está mirando el usuario.
 *
 * La fecha vive en la dirección web (`?d=2026-07-20`), no en el estado del
 * componente: así el enlace de un día concreto se puede compartir y el botón
 * "atrás" del móvil hace lo que se espera.
 *
 * Sin fecha en la dirección se abre por el día que toca mirar a esa hora —ayer
 * por la mañana, hoy a partir del mediodía—; ver `defaultSalesDate`. Una fecha
 * ilegible o fuera de rango no deja la pantalla en blanco: se ajusta al extremo
 * más cercano. No hay ningún dato que fingir aquí — es navegación, no cifras.
 */

import { addDaysMadrid, isValidIsoDate } from "./tz";

/** Primer día del histórico importado. Es solo el valor por defecto. */
export const HISTORY_START = "2026-01-01";

export const DATE_PARAM = "d";

/**
 * Hora de Madrid a partir de la cual el día que interesa ya es el de hoy.
 *
 * Entre las 06:00 y las 12:00 el día en curso apenas ha vendido —los locales
 * abren a las 10 u 11— y lo que se abre la app a mirar es cómo acabó ayer.
 */
export const MORNING_ENDS_AT = 12;

/** Hasta esta hora el día vivo ES el de ayer: no hay nada anterior que abrir. */
const BUSINESS_DAY_CUTOFF_HOUR = 6;

/**
 * El día que se enseña al abrir la app sin pedir ninguno.
 *
 * `businessToday` es el día de NEGOCIO vivo (ver `businessTodayMadrid`). De
 * madrugada es él mismo el que interesa: aún está facturando. De 06:00 a
 * 12:00, el recién cerrado, completo. Desde el mediodía, el día en curso. Es
 * solo el punto de partida: las flechas y el calendario siguen llevando a
 * cualquier día.
 */
export function defaultSalesDate(businessToday: string, hour: number): string {
  const manana = hour >= BUSINESS_DAY_CUTOFF_HOUR && hour < MORNING_ENDS_AT;
  return manana ? addDaysMadrid(businessToday, -1) : businessToday;
}

export function resolveSalesDate(
  raw: string | null,
  {
    today,
    earliest = HISTORY_START,
    fallback = today,
  }: { today: string; earliest?: string; fallback?: string },
): string {
  const iso = raw !== null && isValidIsoDate(raw) ? raw : fallback;
  // Las fechas ISO se comparan bien como texto: mismo formato, misma anchura.
  // El recorte se aplica también al día por defecto: si el histórico empezara
  // hoy, "ayer" sería un día que no existe en la base.
  if (iso > today) return today;
  if (iso < earliest) return earliest;
  return iso;
}

export function canGoBack(iso: string, earliest: string): boolean {
  return iso > earliest;
}

export function canGoForward(iso: string, today: string): boolean {
  return iso < today;
}
