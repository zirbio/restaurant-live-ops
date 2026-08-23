import { createClient } from "@supabase/supabase-js";

const url = import.meta.env["VITE_SUPABASE_URL"];
const key = import.meta.env["VITE_SUPABASE_ANON_KEY"];

if (!url || !key) {
  // Mejor romper al arrancar que servir una pantalla en blanco sin explicación.
  throw new Error(
    "Faltan VITE_SUPABASE_URL o VITE_SUPABASE_ANON_KEY. Revisa el fichero .env.local.",
  );
}

/**
 * Cliente único. La clave publicable no da acceso a nada por sí sola: cada
 * consulta viaja con el JWT del usuario y Row Level Security decide qué
 * restaurantes puede leer.
 */
export const supabase = createClient(url, key, {
  auth: { persistSession: true, autoRefreshToken: true },
});
