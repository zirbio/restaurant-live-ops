/**
 * Formato español de números, euros, porcentajes y tiempos de servicio.
 *
 * Estas cifras se leen en el turno para decidir. Dos reglas gobiernan todo el
 * módulo:
 *
 *  1. Cifras completas y en formato español (1.234.567,89 €). Nunca k€ ni M€.
 *  2. Un dato que no existe se muestra como raya, jamás como cero: un cero
 *     falso se lee como un cero real y lleva a decisiones equivocadas.
 */

/** Lo que se muestra cuando un dato no está disponible. */
export const DASH = "—";

/** Menos tipográfico (U+2212), como en el diseño; no es el guion del teclado. */
const MINUS = "−";

const decimalFormatters = new Map<number, Intl.NumberFormat>();

function formatter(decimales: number): Intl.NumberFormat {
  let f = decimalFormatters.get(decimales);
  if (!f) {
    f = new Intl.NumberFormat("es-ES", {
      minimumFractionDigits: decimales,
      maximumFractionDigits: decimales,
      // Sin esto, es-ES no agrupa los millares de cuatro dígitos y una venta
      // de 1234,56 € saldría como "1234,56 €". En una cifra de negocio el
      // punto de millar tiene que estar siempre.
      useGrouping: "always",
    });
    decimalFormatters.set(decimales, f);
  }
  return f;
}

type Nullable = number | null | undefined;

function isMissing(n: Nullable): n is null | undefined {
  return n === null || n === undefined || Number.isNaN(n);
}

/** Euros en formato español. Por defecto con dos decimales. */
export function eur(n: Nullable, options?: { decimales?: number }): string {
  if (isMissing(n)) return DASH;
  return `${formatter(options?.decimales ?? 2).format(n)} €`;
}

/** Número entero con separador de millar. */
export function num(n: Nullable): string {
  if (isMissing(n)) return DASH;
  return formatter(0).format(Math.round(n));
}

/** Euros con signo explícito, para desviaciones. */
export function signedEur(n: Nullable, options?: { decimales?: number }): string {
  if (isMissing(n)) return DASH;
  const signo = n < 0 ? MINUS : "+";
  return `${signo}${eur(Math.abs(n), options)}`;
}

/** Unidades con signo explícito, para diferencias de guest counts. */
export function signedNum(n: Nullable): string {
  if (isMissing(n)) return DASH;
  const signo = n < 0 ? MINUS : "+";
  return `${signo}${num(Math.abs(n))}`;
}

/**
 * Número con un decimal y SIN unidad, para las celdas de una tabla cuya
 * cabecera ya dice de qué son: `VPHH €` arriba, `68,0` debajo.
 *
 * Es el mismo reparto que usa la tabla de venta —`REAL €` sobre `88.156`— y el
 * motivo es el ancho: en un iPhone de 393 px, repetir la unidad en cada celda
 * se come la columna del nombre del restaurante.
 */
export function dec(n: Nullable): string {
  if (isMissing(n)) return DASH;
  return formatter(1).format(n);
}

/**
 * ¿Esta cifra se IMPRIME como cero con un decimal?
 *
 * El color de una desviación tiene que decir lo mismo que su número. Si una
 * diferencia se redondea a cero en pantalla, tampoco debe pintarse como
 * incumplimiento.
 *
 * Es el mismo criterio que la gráfica de tendencia, que juzga la cifra
 * redondeada porque es la que se lee.
 */
export function roundsToZero(n: Nullable): boolean {
  if (isMissing(n)) return false;
  return formatter(1).format(Math.abs(n)) === formatter(1).format(0);
}

/**
 * Lo mismo con signo, para las desviaciones contra el objetivo.
 *
 * Un valor que redondea a cero sale sin signo, por el mismo motivo que en
 * `pct`: a un decimal, tres centésimas es estar en el objetivo, y un "−0,0"
 * insinúa una dirección que la cifra ya no tiene.
 */
export function signedDec(n: Nullable): string {
  if (isMissing(n)) return DASH;
  const cifra = formatter(1).format(Math.abs(n));
  if (cifra === formatter(1).format(0)) return cifra;
  return `${n < 0 ? MINUS : "+"}${cifra}`;
}

/**
 * Porcentaje con un decimal y signo.
 *
 * Un valor que redondea a cero sale SIN signo. Con él, una desviación de tres
 * centésimas se leía "−0,0 %", que parece un despiste de la pantalla y además
 * insinúa una dirección que la cifra ya no tiene: a un decimal, eso es estar
 * en el objetivo.
 */
export function pct(n: Nullable): string {
  if (isMissing(n)) return DASH;
  const cifra = formatter(1).format(Math.abs(n));
  if (cifra === formatter(1).format(0)) return `${cifra} %`;
  return `${n < 0 ? MINUS : "+"}${cifra} %`;
}

/**
 * Porcentaje con un decimal y SIN signo.
 *
 * Para las cifras que no son una desviación: un 27,5 % de mano de obra o un
 * 95,8 % de cumplimiento no van "hacia arriba" ni "hacia abajo", y con signo se
 * leerían como un crecimiento, que es otra cosa.
 */
export function pctPlain(n: Nullable): string {
  if (isMissing(n)) return DASH;
  // El menos tipográfico, como en el resto del módulo: mezclar los dos guiones
  // en la misma pantalla se nota, y el del teclado es más corto.
  return `${n < 0 ? MINUS : ""}${formatter(1).format(Math.abs(n))} %`;
}

/** Tiempo de servicio en segundos enteros. */
export function secs(n: Nullable): string {
  if (isMissing(n)) return DASH;
  return `${Math.round(n)}"`;
}

const fechaCortaFormatter = new Intl.DateTimeFormat("es-ES", {
  timeZone: "Europe/Madrid",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
});

/**
 * `11/08 15:55`: cuándo se calculó un dato que trae de fuera la app, en Madrid.
 *
 * Con zona explícita, como todo lo demás en este proyecto. Un `toLocaleString`
 * sin `timeZone` usa el reloj del dispositivo que lo ejecuta: el móvil de un
 * gerente de viaje en otro huso horario enseñaría una hora que no es la de
 * Madrid, y esta cifra dice de cuándo es el dato, no qué hora es donde está él.
 *
 * El formateo va parte a parte y no por `.format()` directo: pedirle a es-ES
 * día y mes en `"2-digit"` junto con hora y minuto hace que Chrome resuelva el
 * patrón SIN el cero — comprobado en consola, `resolvedOptions()` devuelve
 * `month: "numeric"` aunque se pida `"2-digit"` — y "11/8" no es la fecha con
 * dos dígitos que pide el diseño. Rellenar cada parte a mano lo hace inmune a
 * qué patrón elija el motor.
 */
export function fechaCorta(iso: string): string {
  const partes = new Map(fechaCortaFormatter.formatToParts(new Date(iso)).map((p) => [p.type, p.value]));
  const dosDigitos = (valor: string | undefined) => (valor ?? "").padStart(2, "0");
  return (
    `${dosDigitos(partes.get("day"))}/${dosDigitos(partes.get("month"))} ` +
    `${dosDigitos(partes.get("hour"))}:${dosDigitos(partes.get("minute"))}`
  );
}

/**
 * Personal fichado y asignado, "8/9".
 *
 * Tres estados distintos, y la diferencia importa: sin cuadrante no hay dato y
 * se muestra raya entera; con cuadrante pero sin fichados porque la hora aún no
 * ha empezado, raya solo en el lado izquierdo; un 0 significa que no hay nadie
 * dentro, que es una afirmación muy distinta de "todavía no ha pasado".
 */
export function staffing(clocked: Nullable, assigned: Nullable, clipped?: Nullable): string {
  if (isMissing(assigned)) return DASH;
  const cifra = `${isMissing(clocked) ? DASH : Math.round(clocked)}/${Math.round(assigned)}`;
  // Un fichaje que nadie cerró se deja de contar, y eso baja la F. Sin avisar,
  // la fila parecería una ausencia de verdad.
  //
  // El espacio es DURO (U+00A0) a propósito: un espacio normal es punto de
  // corte, y en la celda estrecha de la tabla "12/14 ⚠" se partía en dos
  // líneas dejando la fila más alta que sus vecinas. Va escapado y no literal
  // porque un U+00A0 en el código fuente es invisible y se pierde al editar.
  return !isMissing(clipped) && clipped > 0 ? `${cifra}\u00A0⚠` : cifra;
}
