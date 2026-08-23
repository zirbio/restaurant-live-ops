import { describe, expect, it, vi } from "vitest";

import { isTransientAuthError, withRetry } from "../src/lib/retry";

describe("errores transitorios de autenticación", () => {
  it("reconoce el token rechazado por reloj adelantado", () => {
    // Un pequeño desfase entre máquinas puede hacer que un token recién
    // emitido parezca adelantado.
    expect(isTransientAuthError({ message: "JWT issued at future" })).toBe(true);
  });

  it("reconoce las demás quejas sobre el token", () => {
    expect(isTransientAuthError({ message: "JWT expired" })).toBe(true);
    expect(isTransientAuthError({ code: "PGRST301" })).toBe(true);
  });

  it("no reintenta lo que no se va a arreglar solo", () => {
    expect(isTransientAuthError({ message: "permission denied for table" })).toBe(false);
    expect(isTransientAuthError({ message: "relation does not exist" })).toBe(false);
    expect(isTransientAuthError(null)).toBe(false);
  });
});

describe("reintento", () => {
  it("devuelve el resultado bueno a la primera si no hay error", async () => {
    const fn = vi.fn().mockResolvedValue({ data: [1], error: null });
    await expect(withRetry(fn, { sleep: async () => {} })).resolves.toEqual({
      data: [1],
      error: null,
    });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("reintenta el error de reloj y acaba devolviendo los datos", async () => {
    const fn = vi
      .fn()
      .mockResolvedValueOnce({ data: null, error: { message: "JWT issued at future" } })
      .mockResolvedValueOnce({ data: [1], error: null });
    const r = await withRetry(fn, { sleep: async () => {} });
    expect(r.error).toBeNull();
    expect(fn).toHaveBeenCalledTimes(2);
  });

  it("no reintenta un error que no es transitorio", async () => {
    const fn = vi.fn().mockResolvedValue({ data: null, error: { message: "permission denied" } });
    const r = await withRetry(fn, { sleep: async () => {} });
    expect(r.error).toEqual({ message: "permission denied" });
    expect(fn).toHaveBeenCalledTimes(1);
  });

  it("se rinde tras varios intentos y devuelve el error, sin inventar datos", async () => {
    const fn = vi.fn().mockResolvedValue({ data: null, error: { message: "JWT issued at future" } });
    const r = await withRetry(fn, { sleep: async () => {}, attempts: 3 });
    expect(r.data).toBeNull();
    expect(r.error).not.toBeNull();
    expect(fn).toHaveBeenCalledTimes(3);
  });

  it("espera un poco más en cada intento", async () => {
    const esperas: number[] = [];
    const fn = vi.fn().mockResolvedValue({ data: null, error: { message: "JWT issued at future" } });
    await withRetry(fn, {
      sleep: async (ms) => {
        esperas.push(ms);
      },
      attempts: 3,
    });
    expect(esperas).toEqual([400, 800]);
  });
});
