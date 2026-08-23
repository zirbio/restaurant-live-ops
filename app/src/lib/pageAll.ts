/**
 * Lectura completa de una tabla por páginas.
 *
 * PostgREST corta las respuestas largas, y el corte NO viene marcado como
 * error: llegan mil filas y la consulta parece haber ido bien. En la pantalla
 * del día eso no pasaba —un día son un puñado de filas— pero la del mes pide
 * más de un año de días por restaurante, y una venta mensual calculada sobre
 * una tabla truncada sale corta sin que nada lo avise. Que es exactamente el
 * tipo de número falso que este proyecto no puede permitirse.
 *
 * Así que se pide por páginas hasta que una vuelve incompleta. Y si el número
 * de páginas se dispara, se para con un error visible en vez de seguir dando
 * vueltas: un bucle infinito silencioso también es un fallo.
 */

import { withRetry, type Resultado } from "./retry";

/** Tamaño de página. Por debajo del corte de PostgREST, que es de mil. */
export const PAGE_SIZE = 1000;

/** Tope de páginas. A mil filas cada una, medio millón de filas: es de sobra. */
const MAX_PAGES = 500;

export class TruncatedReadError extends Error {}

/**
 * Recorre una consulta por páginas y devuelve todas las filas.
 *
 * `page` recibe el rango de índices y devuelve la consulta ya acotada, que es
 * lo que hace `.range(desde, hasta)` de supabase-js.
 */
export async function pageAll<T>(
  page: (from: number, to: number) => PromiseLike<Resultado<T[]>>,
): Promise<Resultado<T[]>> {
  const todas: T[] = [];

  for (let pagina = 0; pagina < MAX_PAGES; pagina++) {
    const desde = pagina * PAGE_SIZE;
    const respuesta = await withRetry(() => page(desde, desde + PAGE_SIZE - 1));
    if (respuesta.error) return { data: null, error: respuesta.error };

    const filas = respuesta.data ?? [];
    todas.push(...filas);
    // Una página incompleta es la última: no hay más que pedir.
    if (filas.length < PAGE_SIZE) return { data: todas, error: null };
  }

  return {
    data: null,
    error: {
      message: `la lectura superó las ${MAX_PAGES} páginas y se ha parado: hay más filas de las esperadas`,
    },
  };
}
