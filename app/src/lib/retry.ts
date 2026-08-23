/**
 * Reintento de consultas rechazadas por un desfase de reloj.
 *
 * Supabase reparte las peticiones entre varias máquinas. Cuando alguna va unos
 * segundos por detrás de la que emitió el token, rechaza ese token con "JWT
 * issued at future" aunque sea perfectamente válido.
 *
 * Es transitorio y se arregla solo en menos de un segundo, así que se
 * reintenta. Lo que NO se hace es tragarse el error: si tras los reintentos
 * sigue fallando, se devuelve tal cual para que la pantalla lo enseñe.
 */

/** Forma mínima de una respuesta de supabase-js. */
export interface Resultado<T> {
  data: T | null;
  error: { message?: string; code?: string } | null;
}

const MENSAJES_TRANSITORIOS = ["issued at future", "jwt expired", "jwt is expired"];

/** Código de PostgREST para un JWT que no le cuadra. */
const CODIGO_JWT = "PGRST301";

export function isTransientAuthError(error: { message?: string; code?: string } | null): boolean {
  if (!error) return false;
  if (error.code === CODIGO_JWT) return true;
  const m = (error.message ?? "").toLowerCase();
  return MENSAJES_TRANSITORIOS.some((t) => m.includes(t));
}

export async function withRetry<T>(
  // PromiseLike, no Promise: el constructor de consultas de supabase-js es
  // "esperable" pero no una promesa completa.
  consulta: () => PromiseLike<Resultado<T>>,
  opciones?: { attempts?: number; sleep?: (ms: number) => Promise<void> },
): Promise<Resultado<T>> {
  const intentos = opciones?.attempts ?? 3;
  const dormir =
    opciones?.sleep ?? ((ms: number) => new Promise<void>((r) => setTimeout(r, ms)));

  let ultimo: Resultado<T> = { data: null, error: null };
  for (let i = 0; i < intentos; i++) {
    ultimo = await consulta();
    if (!isTransientAuthError(ultimo.error)) return ultimo;
    if (i < intentos - 1) await dormir(400 * (i + 1));
  }
  return ultimo;
}
