import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * El cliente de Supabase se crea al importar el módulo y rompe adrede si
 * faltan las variables de entorno. Esos dos comportamientos se prueban por
 * separado porque tiran en direcciones opuestas y es fácil romper uno al
 * arreglar el otro:
 *
 * - En los tests el módulo debe importarse sin depender de que exista un
 *   `.env.local` en la máquina de quien los ejecuta (ni en el CI).
 * - En la aplicación real, si faltan las variables tiene que reventar al
 *   arrancar en vez de servir una pantalla en blanco sin explicación.
 */

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("cliente de Supabase", () => {
  it("se importa sin necesitar un fichero de entorno local", async () => {
    const modulo = await import("../src/lib/supabase");
    expect(modulo.supabase).toBeDefined();
  });

  it("rompe al importar si falta la URL", async () => {
    vi.stubEnv("VITE_SUPABASE_URL", "");
    vi.resetModules();
    await expect(import("../src/lib/supabase")).rejects.toThrow(/VITE_SUPABASE_URL/);
  });

  it("rompe al importar si falta la clave", async () => {
    vi.stubEnv("VITE_SUPABASE_ANON_KEY", "");
    vi.resetModules();
    await expect(import("../src/lib/supabase")).rejects.toThrow(/VITE_SUPABASE_ANON_KEY/);
  });
});
