/**
 * Fechas y horas en Europe/Madrid.
 *
 * El móvil de quien mire la app puede estar en cualquier zona horaria, y el
 * servidor está en UTC. "Hoy" es siempre hoy en Madrid: nada de
 * `toISOString()` para obtener el día, que devolvería el día equivocado
 * durante las dos primeras horas de cada madrugada.
 */

const MADRID = "Europe/Madrid";

const isoParts = new Intl.DateTimeFormat("en-CA", {
  timeZone: MADRID,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

const hourParts = new Intl.DateTimeFormat("es-ES", {
  timeZone: MADRID,
  hour: "2-digit",
  hour12: false,
});

const longDate = new Intl.DateTimeFormat("es-ES", {
  timeZone: MADRID,
  weekday: "short",
  day: "numeric",
  month: "short",
});

const clock = new Intl.DateTimeFormat("es-ES", {
  timeZone: MADRID,
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/** El día civil de hoy en Madrid, como `YYYY-MM-DD`. */
export function todayMadrid(now: Date = new Date()): string {
  return isoParts.format(now);
}

/** Lo anterior a esta hora de Madrid pertenece al día de negocio ANTERIOR. */
const BUSINESS_DAY_CUTOFF_HOUR = 6;

/**
 * El día de NEGOCIO vivo en Madrid, como `YYYY-MM-DD`.
 *
 * La app compara todo en una ventana común 06:00→06:00. la fuente de ventas usa una fecha de
 * caja variable y el worker la recompone antes de publicar; este helper solo
 * decide qué jornada OPERATIVA está viva en la interfaz.
 */
export function businessTodayMadrid(now: Date = new Date()): string {
  const hoy = todayMadrid(now);
  return hourMadrid(now) < BUSINESS_DAY_CUTOFF_HOUR ? addDaysMadrid(hoy, -1) : hoy;
}

/** La hora (0-23) que es ahora en Madrid. */
export function hourMadrid(now: Date = new Date()): number {
  return Number.parseInt(hourParts.format(now), 10);
}

/** La hora en punto de Madrid, como `HH:MM`. */
export function clockMadrid(now: Date = new Date()): string {
  return clock.format(now);
}

const ISO_RE = /^\d{4}-\d{2}-\d{2}$/;

/** ¿Es un `YYYY-MM-DD` que existe en el calendario? */
export function isValidIsoDate(iso: string): boolean {
  if (!ISO_RE.test(iso)) return false;
  // `Date.UTC` normaliza en silencio: el 30 de febrero se convierte en el 2 de
  // marzo. Se compara el resultado con la entrada para cazarlo.
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  const t = new Date(Date.UTC(y, m - 1, d));
  return t.getUTCFullYear() === y && t.getUTCMonth() === m - 1 && t.getUTCDate() === d;
}

/**
 * Instante de mediodía UTC del día indicado.
 *
 * Se ancla a mediodía a propósito: Madrid va una o dos horas por delante, así
 * que las 12:00 UTC siempre caen dentro del mismo día civil de Madrid, también
 * en las madrugadas del cambio de hora. Anclar a medianoche daría el día
 * anterior media parte del año.
 */
function mediodiaUtc(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d, 12));
}

/**
 * Suma (o resta) días a una fecha `YYYY-MM-DD` sin salirse del calendario de
 * Madrid. Sumar 24 h a medianoche sí se saltaría o repetiría un día las dos
 * noches del año en que cambia la hora.
 */
export function addDaysMadrid(iso: string, delta: number): string {
  return isoParts.format(new Date(mediodiaUtc(iso).getTime() + delta * 86_400_000));
}

/** Fecha larga en español a partir de un `YYYY-MM-DD`. */
export function longDateFromIso(iso: string): string {
  // es-ES abrevia con puntos y separa el día de la semana con una coma
  // ("dom., 26 jul."); el diseño lo escribe sin puntuación.
  return longDate.format(mediodiaUtc(iso)).replace(/\./g, "").replace(",", "");
}

/** Fecha larga en español, tal como la muestra la cabecera del diseño. */
export function longDateMadrid(now: Date = new Date()): string {
  return longDateFromIso(todayMadrid(now));
}

/** Minutos transcurridos desde una marca de tiempo, o null si no hay marca. */
export function minutesAgo(iso: string | null | undefined, now: Date = new Date()): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return Math.floor((now.getTime() - t) / 60_000);
}

/**
 * Frescura en lenguaje llano. Sin marca de tiempo dice "sin datos": nunca
 * finge que un dato es reciente.
 */
export function freshnessLabel(iso: string | null | undefined, now: Date = new Date()): string {
  const minutos = minutesAgo(iso, now);
  if (minutos === null) return "sin datos";
  if (minutos < 1) return "hace menos de 1 min";
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  // Pasado un día, las horas acumuladas ("hace 51 h") obligan a echar cuentas
  // para saber desde cuándo no hay dato. Lo que importa leer de un vistazo es
  // que lleva días parado.
  const dias = Math.floor(horas / 24);
  return dias === 1 ? "hace 1 día" : `hace ${dias} días`;
}
