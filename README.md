# Restaurant Live Ops

Restaurant Live Ops es una PWA de solo lectura para seguir la operación diaria
por restaurante. Cada instalación es independiente: usa su propio proyecto
Supabase, sus propias credenciales y sus propias fuentes autorizadas.

## Qué incluye

- Consulta diaria por restaurante y fecha: venta horaria, totales, servicio y
  dotación agregada.
- Worker de venta, previsión y fichajes; cada ejecución queda registrada para
  mostrar frescura y errores.
- Autenticación por correo y autorización explícita por restaurante mediante
  Row Level Security (RLS).
- PWA instalable y refrescada desde Supabase.

La fecha operativa se calcula siempre en `Europe/Madrid`. El día de negocio
empieza a las 06:00, por lo que la madrugada anterior pertenece al día previo.

## Limitación importante de la vista mensual

La vista mensual está desactivada por defecto con
`VITE_MONTHLY_ENABLED=false`. **No funcionará correctamente sin un adaptador
mensual propio.** Esta edición no distribuye el lector ni la automatización que
alimentaba la implementación privada original.

Solo se puede habilitar cuando una integración propia implemente el contrato
`MonthlySource`: por cada restaurante debe entregar `year`, `month`,
`covers_through`, `net_sales` y `labor_cost`, y escribir datos validados en
`monthly_snapshots`. Cuando exista ese adaptador, configure
`VITE_MONTHLY_ENABLED=true` y `VITE_MONTHLY_SOURCE=supabase`. Sin ambos, la
aplicación muestra un error de configuración y no inventa datos. La operación
diaria no depende de esta vista.

## Requisitos

- Git, Docker y Docker Compose para el entorno local.
- Supabase CLI para crear, probar y aplicar el esquema.
- Python 3.12 y `uv` para ejecutar el worker y los hooks fuera del contenedor.
- Node.js LTS y npm para construir la PWA.
- Dos fuentes diarias cuya redistribución e integración estén autorizadas: una
  de ventas y otra de planificación/fichajes.

No guarde secretos en el repositorio. Los ejemplos contienen solo placeholders
y los ficheros `.env.local` están ignorados por Git.

## Instalación diaria paso a paso

1. Cree un proyecto Supabase vacío para esta instalación. Para trabajar en
   local, desde la raíz del repositorio ejecute:

   ```fish
   supabase start
   supabase db reset
   ```

   `supabase db reset` borra y recrea **solo** la base local. Carga las
   migraciones y los restaurantes sintéticos `R001`, `R002` y `R003`.

2. Antes de crear accesos o ejecutar una ingesta remota, cree el catálogo del
   piloto. Edite **solo en su copia protegida** los tres registros sintéticos
   de `supabase/seed.sql` para que sus `id` y `name` sean los locales propios
   del piloto. No añada ese cambio local al control de versiones si contiene
   información de su operación. `RESTAURANTS_JSON` deberá usar exactamente los
   mismos `id`; así las claves foráneas de accesos e ingestas ya tienen su
   restaurante de destino.

   Después, autentíquese con la CLI, enlace exclusivamente el proyecto nuevo y
   aplique migraciones **incluida la semilla**. Sustituya el placeholder, sin
   copiar ningún identificador de otra instalación:

   ```fish
   supabase login
   supabase link --project-ref <project-id>
   supabase db push --include-seed
   ```

   Revise primero las migraciones y la semilla en local; `supabase db push
   --include-seed` modifica el proyecto remoto enlazado y crea el catálogo
   antes de las asignaciones RLS o del primer worker.

3. Prepare las variables de la PWA. Copie `app/.env.example` a
   `app/.env.local` y rellénelo fuera de Git. La consola de Supabase puede
   llamar a su clave publicable `VITE_SUPABASE_PUBLISHABLE_KEY`; esta versión
   de la PWA la recibe con el nombre compatible que realmente consume,
   `VITE_SUPABASE_ANON_KEY`. No cree una segunda variable: copie el valor
   publicable en `VITE_SUPABASE_ANON_KEY`.

4. Prepare el worker. Copie `worker/.env.example` a `worker/.env.local` y
   rellene las URLs y credenciales de sus dos fuentes autorizadas, el JSON de
   restaurantes y `SUPABASE_DB_URL`. Mantenga las variables de la fuente de
   ventas y de personal solo en el entorno del worker.

5. Compruebe localmente la PWA y el worker antes de desplegarlos:

   ```fish
   cd app
   npm ci
   npm run build
   cd ../worker
   uv sync --all-groups
   uv run restaurant-live-ops-worker --help
   ```

## Configuración de Supabase Auth y RLS

Las migraciones crean las tablas, los roles de ingesta mínimos, las políticas
RLS y el hook `private.restrict_signup_to_allowlist`. El navegador recibe la
URL del proyecto y la clave publicable; RLS, no la clave, decide las filas que
cada sesión puede leer.

1. En Auth, active el método de acceso por correo que vaya a utilizar y
   configure la URL pública de su propia PWA como URL de sitio y redirección.
2. Configure el hook **before-user-created** con
   `private.restrict_signup_to_allowlist`. El hook solo admite correos incluidos
   previamente en `private.allowed_email`.
3. Añada una dirección autorizada desde una sesión administrativa protegida:

   ```sql
   insert into private.allowed_email (email)
   values ('operator@example.com');
   ```

4. Después de que esa persona haya creado su cuenta, asígnele solo los locales
   necesarios. El identificador debe proceder de `auth.users` de su propio
   proyecto:

   ```sql
   insert into public.app_user_access (user_id, restaurant_id)
   values ('<auth-user-id>', 'R001');
   ```

No conceda acceso global por defecto. Una fila por usuario y restaurante hace
que la app, las ventas, el personal, el estado de ingesta y el contrato mensual
permanezcan aislados por RLS.

## Configuración del worker

`worker/.env.example` es la lista completa de variables ejecutables del
worker:

| Variable | Uso |
| --- | --- |
| `SALES_SOURCE_BASE_URL`, `SALES_SOURCE_USERNAME`, `SALES_SOURCE_PASSWORD` | Fuente diaria de ventas. |
| `SALES_SOURCE_VIEW_LABEL`, `SALES_SOURCE_HOURLY_PATH`, `SALES_SOURCE_HOURLY_QUERY` | Selector de vista y ruta/query exactas que vinculan cada respuesta horaria con el clic actual. |
| `WORKFORCE_SOURCE_BASE_URL`, `WORKFORCE_SOURCE_BUSINESS_ID`, `WORKFORCE_SOURCE_USERNAME`, `WORKFORCE_SOURCE_PASSWORD`, `WORKFORCE_SOURCE_API_KEY` | Fuente de previsión, cuadrante y fichajes; la clave API es opcional. |
| `RESTAURANTS_JSON` | Lista JSON de locales propios con `id`, `name`, `source_site`, `display_order`, `has_drive_through` y `workforce_expected_hours`. |
| `SUPABASE_DB_URL` | Conexión Postgres privada del worker; nunca una clave de navegador. |
| `STAFFING_EXCLUDED_PEOPLE` | Exclusiones por nombre separadas por `;`; déjela vacía si no aplica y nunca la versiona. |

Las URLs base de ambas fuentes deben usar HTTPS, incluir un host y no contener
credenciales, query ni fragmento. HTTP se admite únicamente contra
`localhost`, `127.0.0.1` o `::1` si un test activa explícitamente
`ALLOW_INSECURE_LOCAL_SOURCE_URLS_FOR_TESTS=true`; no configure esa opción en
una instalación real.

El worker falla de forma cerrada si una respuesta de ventas supera 1 MiB o 96
filas, si una respuesta de personal supera 2 MiB o 10.000 filas, o si un ciclo
de personal intenta resolver más de 500 personas únicas. Los límites se
aplican también a cuerpos HTTP sin `Content-Length`: superarlos aborta el ciclo
sin publicar un snapshot parcial como si fuera completo.

`workforce_expected_hours` es la lista pública, no vacía y sin duplicados, de
horas `0` a `23` que debe cubrir cada jornada de ese restaurante. Sustituya las
horas sintéticas del ejemplo por la cobertura que su instalación pueda exigir
de forma verificable. Previsión y staffing deben devolver exactamente ese
conjunto: si falta una hora, sobra otra, la lista está vacía o no existe la
configuración del restaurante, el ciclo termina en error antes de escribir.
Cada cohorte conserva la lista esperada y la app vuelve a compararla con las
filas recibidas; una captura única pero incompleta tampoco se publica.

La migración define `sales_ingest_worker` y `workforce_ingest_worker` como
roles **NOLOGIN** y con permisos separados. Después de `supabase db push
--include-seed`, una persona administradora debe crear dos logins de runtime
separados en una sesión SQL administrativa protegida: uno para ventas y otro
para personal. No use el login administrador ni el rol `postgres` durante la
ejecución del worker.

Genere una contraseña distinta para cada login en fish y guárdela directamente
en el gestor de secretos del hosting; no la copie en Git, incidencias, chat ni
salida de terminal:

```fish
set -x RLO_SALES_RUNTIME_PASSWORD (openssl rand -hex 32)
set -x RLO_WORKFORCE_RUNTIME_PASSWORD (openssl rand -hex 32)
```

En esa sesión administrativa, sustituya los dos placeholders sin publicar sus
valores. Los logins heredan exclusivamente el rol mínimo y no pueden crear
bases, roles ni iniciar sesión como administrador:

```sql
create role rlo_sales_runtime login nosuperuser nocreatedb nocreaterole noreplication inherit
  password '<generated-sales-password>';
grant sales_ingest_worker to rlo_sales_runtime
  WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;

create role rlo_workforce_runtime login nosuperuser nocreatedb nocreaterole noreplication inherit
  password '<generated-workforce-password>';
grant workforce_ingest_worker to rlo_workforce_runtime
  WITH ADMIN FALSE, INHERIT TRUE, SET FALSE;
```

Configure en el servicio de ventas el secreto `SUPABASE_DB_URL` con el login
`rlo_sales_runtime` y, en el servicio de personal, el mismo nombre de secreto
con `rlo_workforce_runtime`. Use únicamente la interfaz de secretos del
hosting para esas cadenas; el valor cambia por servicio aunque la variable se
llame igual. Verifique desde cada servicio que puede conectar y escribir solo
sus tablas antes de programarlo.

Para probar un ciclo con las variables cargadas por su gestor de secretos:

```fish
cd worker
uv run restaurant-live-ops-worker sales
uv run restaurant-live-ops-worker workforce
uv run restaurant-live-ops-worker staffing
uv run restaurant-live-ops-worker backfill --days 14
```

`backfill` recupera días ausentes o incoherentes. Para un rango cerrado de
ventas use `sales-recapture --from AAAA-MM-DD --to AAAA-MM-DD`; el comando
rechaza fechas que todavía no han cerrado en `Europe/Madrid`.

## Despliegue y programación

Construya el contenedor desde `worker/`; la imagen instala las dependencias
exactas de `uv.lock`, incluye Chromium y se ejecuta como usuario sin privilegios:

```fish
cd worker
docker build -t restaurant-live-ops-worker .
docker run --rm --env-file .env.local restaurant-live-ops-worker sales
```

Programe servicios independientes con el mismo contenedor y con la conexión de
mínimo privilegio correspondiente: ventas recibe el secreto de
`rlo_sales_runtime`; personal y `staffing`, el de
`rlo_workforce_runtime`. Una pauta inicial es captura de ventas cada 10–15
minutos durante la operación, `staffing` cada 15 minutos, `workforce` al inicio
del día operativo y `backfill` una vez diaria. Observe primero `ingest_runs` y
ajuste la frecuencia a la capacidad de sus fuentes; no solape ejecuciones del
mismo comando.

Para la PWA, inyecte `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`,
`VITE_MONTHLY_ENABLED=false` y `VITE_MONTHLY_SOURCE=` durante el build. El
archivo `netlify.toml` ejecuta `cd app && npm run build` y publica `app/dist`;
cualquier alojamiento estático equivalente debe publicar esa misma carpeta y
redirigir rutas a `index.html`.

## Verificación de permisos

Ejecute las pruebas SQL locales antes de una puesta en marcha:

```fish
supabase db reset
supabase test db
supabase db advisors --local --type security
```

Después, cree dos cuentas de prueba propias, asigne cada una a un restaurante
distinto y confirme en la PWA que cada sesión solo ve su propio local. Sin
sesión, las consultas deben devolver cero filas. Compruebe también que el
worker de ventas no escribe personal, que el de personal no escribe ventas y
que ninguno escribe `monthly_snapshots`.

## Datos sintéticos y privacidad

Las semillas y fixtures usan solo datos sintéticos. Puede reiniciar localmente
las veces necesarias; no los sustituya por exportaciones de producción.

No añada al repositorio nombres, correos, direcciones, horarios, fichajes,
ventas, objetivos, identificadores de despliegue, rutas personales, cookies,
tokens, contraseñas ni cadenas de conexión. Las excepciones de fuentes externas
se deben sanear antes de registrar un error.

Antes de compartir una copia, ejecute el escáner de neutralidad:

```fish
uv run --python 3.12 --project worker python scripts/check_repository_hygiene.py .
uv run --python 3.12 --project worker python scripts/check_repository_hygiene.py --git-archive .
```

## Gate técnico y decisión de publicación

Instale Python 3.12 y `pre-commit` de forma reproducible con `uv` una vez en
cada clon. `fish_add_path` añade el directorio de herramientas de `uv` al PATH
persistente de fish sin depender de una ruta personal concreta. Los dos
comandos de versión comprueban el intérprete y que `pre-commit` ya es visible
antes de instalar los hooks:

```fish
uv python install 3.12
uv run --python 3.12 python --version
uv tool install --python 3.12 pre-commit==4.6.1
fish_add_path (uv tool dir --bin)
type -q pre-commit
pre-commit --version
pre-commit install --install-hooks
```

Los hooks incluyen Ruff, mypy, lint y tipos de la PWA, Gitleaks y el escáner
de neutralidad; el hook de `pre-push` añade la suite del worker. Los controles
del worker usan siempre Python 3.12. Ruff solo comprueba: si encuentra un
problema, el hook falla y deja el árbol sin modificar para que la corrección
sea una decisión visible.

El modo `private` es el predeterminado del gate total:

```fish
scripts/verify_public_release.sh
```

El comando ejecuta, sin omisiones, hooks sobre todo el árbol; lint, tipos,
tests, build y auditorías npm completas y de producción; controles del worker;
construcción real de Docker; recreación, pruebas, integraciones y asesores de
Supabase local; Gitleaks y neutralidad tanto del árbol como del archivo Git
exportable. Que termine en verde demuestra que el
snapshot es técnicamente apto para una instalación privada. **No concede derechos de
redistribución, no elige una licencia y no cambia la visibilidad del
repositorio.**

El modo `public` permanece bloqueado salvo que existan dos decisiones humanas
separadas y explícitas: autorización para redistribuir los conectores externos
y aprobación de una licencia pública concreta. Solo después de documentar
ambas decisiones, sus responsables pueden expresarlas para una ejecución:

```fish
set -x CONNECTOR_REDISTRIBUTION_APPROVED true
set -x PUBLIC_LICENSE_APPROVED true
scripts/verify_public_release.sh public
```

Si falta cualquiera de las dos aprobaciones, el gate falla antes de ejecutar
herramientas. Incluso con ambas y todos los controles técnicos en verde, hacer
público el repositorio sigue siendo una acción humana separada y fuera de este
script.

Para esta distribución, la redistribución del código de los conectores externos
y la licencia MIT fueron aprobadas expresamente antes de ejecutar el gate
público.

## Desarrollo local

Use ficheros separados para evitar que variables del navegador lleguen al
worker o que secretos del worker entren en el bundle:

```fish
cp app/.env.example app/.env.local
cp worker/.env.example worker/.env.local
cd app
npm run dev
```

Los comandos interactivos que necesiten una variable temporal usan fish:

```fish
set -x VITE_MONTHLY_ENABLED false
set -x SALES_SOURCE_USERNAME <usuario-de-prueba>
```

No use `export` ni cargue `.env.local` con sintaxis de otro shell. Para el
worker local, elija un cargador de secretos compatible con fish o configure las
variables en su terminal antes de ejecutar `uv run`.

## Seguridad

Consulte [SECURITY.md](SECURITY.md) para reportar una vulnerabilidad. Si una
credencial se expone, revóquela o rótela en su sistema de origen antes de
investigar; eliminar el texto del repositorio no invalida el secreto.

## Licencia

El proyecto se distribuye bajo la [licencia MIT](LICENSE). Puede usarlo,
modificarlo y redistribuirlo manteniendo el aviso de licencia. Se entrega sin
garantías y cada instalación es responsable de sus conectores, credenciales y
datos.
