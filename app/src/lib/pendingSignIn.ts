/**
 * Recuerda que hay un código de acceso pendiente de teclear.
 *
 * Sin esto, el acceso se rompe en el uso real: la persona pide el código, sale
 * al correo a buscarlo y, mientras tanto, Safari descarta la pestaña (pasa
 * enseguida con muchas pestañas abiertas o poca batería). Al volver, la app
 * arranca de cero y vuelve a pedir el correo, con el código ya en la mano y
 * sin ninguna casilla donde meterlo.
 *
 * Se guarda solo el correo y el instante de la petición: ni el código, ni
 * ningún token.
 */

const CLAVE = "restaurant-live-ops.pending-signin";

/** Lo que dura el código de Supabase. Pasado ese plazo hay que pedir otro. */
export const CODE_TTL_MINUTES = 60;

/** Mínimo que se necesita de `localStorage`, para poder probarlo sin navegador. */
export interface SimpleStorage {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
}

interface Opciones {
  storage?: SimpleStorage | undefined;
  now?: Date | undefined;
}

function almacen(opciones?: Opciones): SimpleStorage | null {
  if (opciones?.storage) return opciones.storage;
  try {
    return window.localStorage;
  } catch {
    return null; // navegación privada con almacenamiento bloqueado
  }
}

export function savePending(email: string, opciones?: Opciones): void {
  const s = almacen(opciones);
  if (!s) return;
  const cuando = (opciones?.now ?? new Date()).toISOString();
  try {
    s.setItem(CLAVE, JSON.stringify({ email, cuando }));
  } catch {
    // Si no se puede guardar, el acceso sigue funcionando sin recordarlo.
  }
}

export interface Pending {
  email: string;
  /** Instante en que se pidió el código. */
  requestedAt: Date;
}

/** La petición pendiente y aún válida, o null. */
export function readPending(opciones?: Opciones): Pending | null {
  const s = almacen(opciones);
  if (!s) return null;

  const crudo = s.getItem(CLAVE);
  if (!crudo) return null;

  try {
    const { email, cuando } = JSON.parse(crudo) as { email?: string; cuando?: string };
    if (!email || !cuando) return null;

    const pedido = new Date(cuando).getTime();
    if (Number.isNaN(pedido)) return null;

    const minutos = ((opciones?.now ?? new Date()).getTime() - pedido) / 60_000;
    if (minutos > CODE_TTL_MINUTES) {
      s.removeItem(CLAVE);
      return null;
    }
    return { email, requestedAt: new Date(pedido) };
  } catch {
    // Contenido corrupto: se descarta en silencio, nunca rompe el acceso.
    return null;
  }
}

export function clearPending(opciones?: Opciones): void {
  almacen(opciones)?.removeItem(CLAVE);
}
