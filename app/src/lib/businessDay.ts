/**
 * La jornada operativa común de la app: de 06:00 a 06:00.
 *
 * Un turno no empieza a medianoche: abre por la mañana y cierra de madrugada,
 * la fuente de ventas no usa necesariamente ese corte: el worker recompone cada fila desde
 * su fecha civil antes de que llegue aquí. Ordenar 06…23 y después 00…05 no
 * es una preferencia de presentación: es la cronología común contra la que se
 * comparan venta, previsión y personal. También "pasada" o "futura" se decide en ese
 * orden: a la 01:00, las 09:00 de este día pasaron hace dieciséis horas y las
 * 02:00 aún no han llegado.
 *
 * Se esconden las horas ya pasadas sin venta. El corte coincide con
 * `BUSINESS_DAY_CUTOFF_HOUR` del worker y con `businessTodayMadrid`.
 */

/** Hora a la que abre el día de restaurante, en Madrid. */
const DAY_STARTS_AT = 6;

/**
 * Posición de una hora dentro del día de restaurante.
 *
 * Las 06:00 son la primera (0) y las 05:00 la última (23), de modo que
 * ordenar por este número deja la madrugada detrás de las 23:00.
 */
export function businessDayOrder(hour: number): number {
  return (hour - DAY_STARTS_AT + 24) % 24;
}

/** Ordena las horas como se vive el turno: 06…23 y después 00…05. */
export function sortByBusinessDay<T extends { hour: number }>(rows: T[]): T[] {
  // Copia: `sort` ordena en el sitio y quien llama puede estar reutilizando su
  // lista para otra cosa (los totales, sin ir más lejos).
  return [...rows].sort((a, b) => businessDayOrder(a.hour) - businessDayOrder(b.hour));
}

/**
 * Las horas que merece la pena pintar.
 *
 * Se cae la hora que **ya pasó y no vendió**: la madrugada muerta y las de
 * apertura antes del primer cliente, que solo alargan la tabla. Se quedan:
 *
 * - las que vendieron, a la hora que fuese, madrugada incluida;
 * - las que todavía no han llegado, porque ahí está la previsión de lo que
 *   queda de día, que es justo lo que se mira para decidir;
 * - la hora en curso, que va a medias y aún puede vender.
 *
 * `currentHour` nulo significa día cerrado: allí ya pasó todo.
 *
 * No toca los totales. Se filtra lo que se enseña, nunca lo que se suma: las
 * horas escondidas no tienen venta, pero sí previsión, y descontarla movería
 * la desviación del día.
 */
export function visibleHours<T extends { hour: number; net: number | null }>(
  rows: T[],
  currentHour: number | null,
): T[] {
  return rows.filter((row) => {
    // la fuente de ventas da ceros explícitos además de no traer la hora; ninguno es venta.
    const vendio = row.net !== null && row.net !== 0;
    if (vendio) return true;
    // "Pasada" se decide en orden de día de negocio: a la 01:00, las 09:00 de
    // este día pasaron hace dieciséis horas y las 02:00 aún no han llegado.
    const yaPaso =
      currentHour === null || businessDayOrder(row.hour) < businessDayOrder(currentHour);
    return !yaPaso;
  });
}
