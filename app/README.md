# Restaurant Live Ops — aplicación

PWA de React y TypeScript para consultar la operación diaria. La vista mensual
está desactivada por defecto y solo se habilita cuando existe el contrato
mensual de Supabase.

## Desarrollo local

1. Copia `.env.example` a `.env.local` y completa las variables de Supabase.
2. Instala dependencias con `npm ci`.
3. Inicia la aplicación con `npm run dev`.

Los datos dependen de las políticas RLS del proyecto conectado. No uses datos
reales en pruebas ni en archivos versionados.
