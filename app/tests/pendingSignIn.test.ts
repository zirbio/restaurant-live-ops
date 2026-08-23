import { beforeEach, describe, expect, it } from "vitest";

import { CODE_TTL_MINUTES, clearPending, readPending, savePending } from "../src/lib/pendingSignIn";

// Almacenamiento de mentira, para no depender del navegador en los tests.
class MemoryStorage {
  private datos = new Map<string, string>();
  getItem(k: string): string | null {
    return this.datos.get(k) ?? null;
  }
  setItem(k: string, v: string): void {
    this.datos.set(k, v);
  }
  removeItem(k: string): void {
    this.datos.delete(k);
  }
}

let almacen: MemoryStorage;
const AHORA = new Date("2026-07-26T20:00:00Z");

beforeEach(() => {
  almacen = new MemoryStorage();
});

describe("petición de código pendiente", () => {
  it("recuerda el correo al que se pidió el código", () => {
    savePending("user@example.com", { storage: almacen, now: AHORA });
    expect(readPending({ storage: almacen, now: AHORA })?.email).toBe("user@example.com");
  });

  it("sigue recordándolo tras cerrar y reabrir la app", () => {
    // El navegador puede descartar la página mientras se consulta el correo.
    // Sin persistencia, al volver se perdería el primer paso.
    savePending("user@example.com", { storage: almacen, now: AHORA });
    const masTarde = new Date(AHORA.getTime() + 3 * 60_000);
    expect(readPending({ storage: almacen, now: masTarde })?.email).toBe("user@example.com");
  });

  it("lo olvida cuando el código ya ha caducado", () => {
    savePending("user@example.com", { storage: almacen, now: AHORA });
    const caducado = new Date(AHORA.getTime() + (CODE_TTL_MINUTES + 1) * 60_000);
    expect(readPending({ storage: almacen, now: caducado })).toBeNull();
  });

  it("lo olvida justo al cumplirse el plazo", () => {
    savePending("user@example.com", { storage: almacen, now: AHORA });
    const justo = new Date(AHORA.getTime() + CODE_TTL_MINUTES * 60_000 + 1);
    expect(readPending({ storage: almacen, now: justo })).toBeNull();
  });

  it("se puede borrar a mano al cambiar de correo", () => {
    savePending("user@example.com", { storage: almacen, now: AHORA });
    clearPending({ storage: almacen });
    expect(readPending({ storage: almacen, now: AHORA })).toBeNull();
  });

  it("devuelve también la hora a la que se pidió", () => {
    savePending("user@example.com", { storage: almacen, now: AHORA });
    expect(readPending({ storage: almacen, now: AHORA })?.requestedAt).toEqual(AHORA);
  });

  it("sin nada guardado no devuelve nada", () => {
    expect(readPending({ storage: almacen, now: AHORA })).toBeNull();
  });

  it("un contenido corrupto no rompe la pantalla de acceso", () => {
    almacen.setItem("restaurant-live-ops.pending-signin", "esto no es json");
    expect(readPending({ storage: almacen, now: AHORA })).toBeNull();
  });
});
