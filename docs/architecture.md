# Arquitectura diaria

La instalación está diseñada para que los datos diarios y los permisos sean
independientes de cualquier otra organización.

```text
fuente diaria de ventas ─┐
                         ├─> worker de ingesta ─> roles mínimos ─> Supabase con RLS ─> PWA
fuente diaria de personal┘
```

## Flujo diario

1. El worker consulta las fuentes configuradas mediante sus variables de
   entorno. La venta, la previsión y los fichajes se validan antes de
   publicarse; los errores se registran por restaurante en `ingest_runs`.
2. Las conexiones de ingesta usan roles separados. El rol de ventas solo puede
   escribir sus tablas y sus ejecuciones; el de personal solo sus proyecciones,
   dotación y ejecuciones. Ninguno puede administrar usuarios, autorizaciones o
   datos mensuales.
3. Supabase conserva datos agregados por restaurante. Todas las tablas públicas
   tienen RLS; una sesión autenticada solo lee los restaurantes presentes en
   `app_user_access`. La allowlist y el hook de alta viven en el esquema
   privado.
4. La PWA consulta Supabase con el JWT de la sesión. La URL y la clave
   publicable permiten conectar, pero no conceden filas sin una política RLS.

Las fechas de negocio se resuelven en `Europe/Madrid`, con corte operativo a
las 06:00. Esto evita que la madrugada se atribuya al día equivocado cuando el
worker se ejecuta en otra zona horaria.

## Contrato mensual aislado

La parte mensual no forma parte de la instalación diaria. El repositorio solo
define `MonthlySource` y la tabla `monthly_snapshots`: un adaptador propio debe
aportar por restaurante el período, la fecha cubierta, ventas netas y coste de
personal. Hasta entonces la PWA debe conservar `VITE_MONTHLY_ENABLED=false`.

El adaptador mensual no recibe permisos implícitos de los roles diarios y debe
tener su propio diseño de permisos, validación y operación. No se publican
conectores, automatizaciones ni credenciales de una implementación anterior.
