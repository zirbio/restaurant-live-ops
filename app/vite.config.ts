import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";
// Se importa de vitest/config, no de vite: es el que conoce la clave `test`.
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      manifest: {
        name: "Restaurant Live Ops",
        short_name: "Live Ops",
        description: "Panel diario neutral para operaciones de restauración",
        lang: "es-ES",
        start_url: "/",
        display: "standalone",
        orientation: "portrait",
        background_color: "#f8fafc",
        theme_color: "#0f172a",
        icons: [
          { src: "/icon.svg", sizes: "any", type: "image/svg+xml" },
          {
            src: "/icon.svg",
            sizes: "any",
            type: "image/svg+xml",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Los datos NUNCA se cachean: un dato viejo presentado como fresco es
        // peor que no tener dato. Solo se guarda el armazón de la aplicación.
        runtimeCaching: [],
        // Sin esto, tras publicar una versión el móvil sigue abriendo la
        // anterior hasta que se cierran todas las pestañas: la corrección
        // tarda días en llegar al usuario, o no llega.
        skipWaiting: true,
        clientsClaim: true,
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts"],
    // El cliente de Supabase se crea al importar el módulo y rompe adrede si
    // faltan estas dos variables. Definirlas aquí permite que los tests que
    // importan código de la app corran sin un `.env.local` en la máquina (ni
    // en el CI), sin ablandar ese guard: en `dev` y en `build` sigue vigente.
    // El host es `.invalid` (reservado por RFC 2606, nunca resuelve): si algún
    // test intentara una llamada de verdad, fallaría en vez de tocar la base.
    env: {
      VITE_SUPABASE_URL: "https://test.supabase.invalid",
      VITE_SUPABASE_ANON_KEY: "clave-de-test",
    },
  },
});
