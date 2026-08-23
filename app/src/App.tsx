import type { Session } from "@supabase/supabase-js";
import { useEffect, useMemo, useState } from "react";

import { DayNav } from "./components/DayNav";
import { Freshness } from "./components/Freshness";
import { Hero } from "./components/Hero";
import { HourlyChart } from "./components/HourlyChart";
import { HourlyTable } from "./components/HourlyTable";
import { LocalCard } from "./components/LocalCard";
import { Login } from "./components/Login";
import { Logo, LogoLockup } from "./components/Logo";
import { MonthNav } from "./components/MonthNav";
import { MonthlyConfigurationError } from "./components/MonthlyConfigurationError";
import { MonthStatus } from "./components/MonthStatus";
import { MonthView } from "./components/MonthView";
import { ViewToggle, type View } from "./components/ViewToggle";
import { useDay } from "./data/useDay";
import { useMonth } from "./data/useMonth";
import { sortByBusinessDay, visibleHours } from "./lib/businessDay";
import { aggregate, currentHourRow } from "./lib/metrics";
import {
  lastClosedDayMadrid,
  monthKeyOf,
  MONTH_PARAM,
  resolveMonth,
  type MonthKey,
} from "./lib/month";
import { differencePp, growthPct } from "./lib/monthly";
import { monthlyFeature, type MonthlyFeature } from "./lib/features";
import { dayProvenance } from "./lib/provenance";
import { DATE_PARAM, defaultSalesDate, HISTORY_START, resolveSalesDate } from "./lib/salesDate";
import { supabase } from "./lib/supabase";
import { businessTodayMadrid, clockMadrid, hourMadrid } from "./lib/tz";
import type { HourRow } from "./lib/types";

const TODOS = "all";
const VIEW_PARAM = "v";

/** Cada cuánto se revisa si el día de negocio ya ha cambiado. */
const CLOCK_MS = 5 * 60_000;

/**
 * Primer mes al que se puede retroceder.
 *
 * Sale del mismo sitio que el tope del selector de día: antes de esa fecha no
 * hay ni una fila guardada, y aceptar un mes anterior por la dirección web
 * cargaría una pantalla entera de rayas sin decir por qué.
 */
const PRIMER_MES = monthKeyOf(HISTORY_START);

/**
 * El último día de negocio CERRADO, revisado mientras la app está abierta.
 *
 * Sin esto, la vista mensual se queda con la ventana que tenía al montar: quien
 * deje el móvil abierto a las 05:50 seguiría viendo "julio en curso · 30 de 31
 * días" a las siete de la mañana, con la venta del mes corta en un día entero y
 * sin poder pasar al mes nuevo. Devolver la misma cadena no repinta nada, así
 * que revisar cada pocos minutos no cuesta.
 */
function useLastClosedDay(): string {
  const [dia, setDia] = useState(() => lastClosedDayMadrid());
  useEffect(() => {
    const revisar = () => setDia(lastClosedDayMadrid());
    const id = setInterval(revisar, CLOCK_MS);
    document.addEventListener("visibilitychange", revisar);
    return () => {
      clearInterval(id);
      document.removeEventListener("visibilitychange", revisar);
    };
  }, []);
  return dia;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [comprobando, setComprobando] = useState(true);

  useEffect(() => {
    void supabase.auth.getSession().then(({ data }) => {
      setSession(data.session);
      setComprobando(false);
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => sub.subscription.unsubscribe();
  }, []);

  if (comprobando) return <div className="splash">Cargando…</div>;
  if (!session) return <Login />;
  return <Dashboard monthly={monthlyFeature(import.meta.env)} />;
}

/**
 * Qué se está mirando: el día o el mes, y qué restaurante.
 *
 * Las dos pantallas comparten el selector de restaurante —cambiar de vista no
 * debe hacer perder el local que se estaba mirando— y el conmutador de abajo.
 * Cada una carga sus datos por su cuenta: solo se pide lo que se ve.
 */
export function Dashboard({ monthly }: { monthly: MonthlyFeature }) {
  if (!monthly.enabled) return <DailyDashboard />;
  if (!monthly.configured) return <DailyDashboard monthlyWarning />;
  return <MonthlyDashboard />;
}

function DailyDashboard({ monthlyWarning = false }: { monthlyWarning?: boolean }) {
  const [seleccion, setSeleccion] = useState<string>(TODOS);
  return (
    <div className="app">
      {monthlyWarning && <MonthlyConfigurationError />}
      <DayScreen seleccion={seleccion} onSeleccion={setSeleccion} />
      <Footer />
    </div>
  );
}

function MonthlyDashboard() {
  const [view, setView] = useState<View>(() =>
    new URLSearchParams(window.location.search).get(VIEW_PARAM) === "month" ? "month" : "day",
  );
  const [seleccion, setSeleccion] = useState<string>(TODOS);

  const cambiarVista = (v: View) => {
    // Pulsar la pestaña que ya está activa no es navegar: sin esto, cada toque
    // apila una entrada idéntica y el botón "atrás" del móvil hay que pulsarlo
    // tantas veces como se haya tocado.
    if (v === view) return;
    const url = new URL(window.location.href);
    if (v === "day") url.searchParams.delete(VIEW_PARAM);
    else url.searchParams.set(VIEW_PARAM, v);
    window.history.pushState({}, "", url);
    setView(v);
  };

  useEffect(() => {
    const onPop = () =>
      setView(
        new URLSearchParams(window.location.search).get(VIEW_PARAM) === "month" ? "month" : "day",
      );
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  return (
    <div className="app">
      {view === "day" ? (
        <DayScreen seleccion={seleccion} onSeleccion={setSeleccion} />
      ) : (
        <MonthScreen seleccion={seleccion} onSeleccion={setSeleccion} />
      )}

      <ViewToggle view={view} onChange={cambiarVista} />

      <Footer />
    </div>
  );
}

function Footer() {
  return (
    <footer className="footer">
      <LogoLockup />
      <button
        type="button"
        className="footer__signout"
        onClick={() => void supabase.auth.signOut()}
      >
        Cerrar sesión
      </button>
    </footer>
  );
}

function Tabs({
  restaurants,
  activo,
  onSeleccion,
}: {
  restaurants: { id: string; name: string }[];
  activo: string;
  onSeleccion: (id: string) => void;
}) {
  return (
    <nav className="tabs">
      <button
        type="button"
        className={`tab ${activo === TODOS ? "is-active" : ""}`}
        onClick={() => onSeleccion(TODOS)}
      >
        TODOS
      </button>
      {restaurants.map((r) => (
        <button
          key={r.id}
          type="button"
          className={`tab ${activo === r.id ? "is-active" : ""}`}
          onClick={() => onSeleccion(r.id)}
        >
          {r.name.toUpperCase()}
        </button>
      ))}
    </nav>
  );
}

function DayScreen({
  seleccion,
  onSeleccion,
}: {
  seleccion: string;
  onSeleccion: (id: string) => void;
}) {
  // El día de NEGOCIO vivo: hasta las 06:00 sigue siendo el de ayer, que es
  // el que aún factura. Gobierna el tope del selector y qué día lleva reloj.
  const hoy = businessTodayMadrid();
  // El día con el que se abre: por la mañana, el recién cerrado. Se fija al
  // entrar y no se recalcula: si cambiara solo al cruzar el mediodía, la app
  // se movería de día sola en las manos de quien la tenga abierta.
  const [inicial] = useState(() => defaultSalesDate(businessTodayMadrid(), hourMadrid()));
  const [salesDate, setSalesDate] = useState(() =>
    resolveSalesDate(new URLSearchParams(window.location.search).get(DATE_PARAM), {
      today: hoy,
      fallback: inicial,
    }),
  );

  // El botón "atrás" del móvil debe volver al día anterior, no salir de la app.
  useEffect(() => {
    const onPop = () =>
      setSalesDate(
        resolveSalesDate(new URLSearchParams(window.location.search).get(DATE_PARAM), {
          today: hoy,
          fallback: inicial,
        }),
      );
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [hoy, inicial]);

  const irADia = (iso: string) => {
    const url = new URL(window.location.href);
    // La dirección sin fecha significa "el día con el que abre la app", que por
    // la mañana es ayer: quitar el parámetro al ir a hoy haría que una recarga
    // saltara de vuelta a ayer.
    if (iso === inicial) url.searchParams.delete(DATE_PARAM);
    else url.searchParams.set(DATE_PARAM, iso);
    window.history.pushState({}, "", url);
    setSalesDate(iso);
  };

  const { data, loading, error } = useDay(salesDate);

  // Cinturón y tirantes sobre `discardOtherDay`: nada se pinta si lo cargado
  // no es del día que dice la cabecera.
  const delDia = data && data.salesDate === salesDate ? data : null;

  // Todas las horas del día sumando los restaurantes que el usuario ve.
  const horasConsolidadas = useMemo<HourRow[]>(() => {
    if (!delDia) return [];
    const porHora = new Map<number, HourRow>();
    for (const filas of delDia.hoursByRestaurant.values()) {
      for (const f of filas) {
        const actual = porHora.get(f.hour);
        if (!actual) {
          porHora.set(f.hour, { ...f });
          continue;
        }
        actual.net = suma(actual.net, f.net);
        actual.gc = suma(actual.gc, f.gc);
        actual.drive_through_net = suma(actual.drive_through_net, f.drive_through_net);
        actual.drive_through_cars = suma(actual.drive_through_cars, f.drive_through_cars);
        actual.delivery_net = suma(actual.delivery_net, f.delivery_net);
        actual.delivery_count = suma(actual.delivery_count, f.delivery_count);
        actual.proj_sales = suma(actual.proj_sales, f.proj_sales);
        actual.proj_gc = suma(actual.proj_gc, f.proj_gc);
        // Los tiempos NO se mezclan entre restaurantes: promediarlos entre
        // locales no significa nada, así que la vista de conjunto los omite.
        actual.kvs = null;
        actual.r2p = null;
        actual.oepe = null;
      }
    }
    return sortByBusinessDay([...porHora.values()]);
  }, [delDia]);

  if (loading && !delDia) return <div className="splash">Cargando el día…</div>;

  if (error) {
    return (
      <div className="splash splash--error">
        <p>No se han podido cargar los datos.</p>
        <p className="splash__detail">{error}</p>
      </div>
    );
  }

  if (!delDia) return <div className="splash">Sin datos</div>;

  if (delDia.restaurants.length === 0) {
    return (
      <div className="splash splash--error">
        <p>Tu usuario no tiene ningún restaurante asignado.</p>
        <p className="splash__detail">Pide que te den de alta para poder ver los datos.</p>
      </div>
    );
  }

  const esHoy = salesDate === hoy;
  const cabecera = (
    <header className="topbar">
      <div className="topbar__brand">
        <Logo size={30} />
        <div className="topbar__titles">
          <span className="topbar__kicker">OPERACIÓN DIARIA</span>
          <DayNav
            salesDate={salesDate}
            today={hoy}
            earliest={delDia.earliestDate ?? HISTORY_START}
            onChange={irADia}
          />
        </div>
      </div>
      {/* El reloj es del ahora: en un día cerrado no significa nada. */}
      {esHoy && <span className="topbar__clock">{clockMadrid()}</span>}
    </header>
  );

  // Un día cerrado sin venta se dice, no se pinta con ceros. Se mira la venta
  // real, no el número de filas: la previsión de la fuente de personal también crea filas, y
  // contarlas taparía el aviso justo en los días que la fuente de ventas no llegó a capturar.
  const sinVentaDelDia = [...delDia.hoursByRestaurant.values()]
    .flat()
    .every((f) => f.net === null);
  if (sinVentaDelDia && !esHoy) {
    return (
      <>
        {cabecera}
        <div className="splash splash--error">
          <p>No hay datos de ventas de este día.</p>
          <p className="splash__detail">
            La captura no llegó o no superó las validaciones. Vuelve a intentarlo más tarde.
          </p>
        </div>
      </>
    );
  }

  // Si la fuente de personal no ha traído la previsión del día, el cotejo es imposible y hay
  // que decirlo: un hueco sin explicar es justo lo que no debe pasar.
  const sinPrevision = ![...delDia.hoursByRestaurant.values()]
    .flat()
    .some((f) => f.proj_sales !== null);

  const unico = delDia.restaurants.length === 1;
  const activo = unico ? (delDia.restaurants[0]?.id ?? TODOS) : seleccion;
  const restauranteActivo = delDia.restaurants.find((r) => r.id === activo) ?? null;

  const filas = activo === TODOS ? horasConsolidadas : (delDia.hoursByRestaurant.get(activo) ?? []);
  // La hora en curso está a medias y se ve aparte, pero solo en el día de hoy:
  // un día cerrado ya tiene su última hora completa.
  const horaEnCurso = esHoy ? hourMadrid() : null;
  const filaEnCurso = horaEnCurso === null ? null : currentHourRow(filas, horaEnCurso);
  const totales = aggregate(filas, horaEnCurso === null ? {} : { excludeHour: horaEnCurso });
  // Lo que se pinta, no lo que se suma: los totales siguen saliendo de `filas`
  // completas. Las horas escondidas no tienen venta, pero sí previsión, y
  // quitarla de la cuenta movería la desviación del día.
  const filasVisibles = visibleHours(filas, horaEnCurso);
  const objetivos = restauranteActivo
    ? (delDia.objectivesByRestaurant.get(restauranteActivo.id) ?? null)
    : null;
  // Los tiempos del día de caja los pondera la fuente de ventas y llegan por restaurante: en
  // la vista de conjunto no hay ninguno que enseñar, porque promediarlos entre
  // locales no significaría nada.
  const tiempos = restauranteActivo
    ? (delDia.serviceTimesByRestaurant.get(restauranteActivo.id) ?? null)
    : null;

  const restauranteVisibles = restauranteActivo ? [restauranteActivo] : delDia.restaurants;
  const procedenciaVisible = dayProvenance(
    restauranteVisibles,
    delDia.dailyStatusByRestaurant,
  );

  // La previsión con la que se escala la barra tiene que cubrir los MISMOS
  // locales que la venta del titular. En un día cerrado, un restaurante sin
  // captura sale de los dos lados: su previsión pesando contra una venta que no
  // existe pinta la barra al 77 % de un día que fue normal. En el día vivo no se
  // descuenta a nadie —un local que todavía no ha vendido va a vender, y su
  // previsión sigue en pie—.
  const totalDe = new Map(
    delDia.restaurants.map((r) => [r.id, aggregate(delDia.hoursByRestaurant.get(r.id) ?? [])]),
  );
  const conVenta = restauranteVisibles.filter((r) => totalDe.get(r.id)?.net != null);
  const localesDeLaPrevision = esHoy ? restauranteVisibles : conVenta;
  const previsionDelDia =
    localesDeLaPrevision.length === 0
      ? null
      : sumaOpcional(localesDeLaPrevision.map((r) => totalDe.get(r.id)?.projDay ?? null));
  const localesSinCaptura = esHoy ? 0 : restauranteVisibles.length - conVenta.length;

  // El interanual del día SOLO tiene sentido en un día cerrado: de 2025 no hay
  // hora a hora en ninguna fuente, así que comparar lo que va de hoy contra el
  // día entero del año pasado daría una caída inventada del tamaño de las
  // horas que faltan.
  //
  // Y se emparejan los DOS lados restaurante a restaurante: si uno se quedó sin
  // captura, sale de los dos sumatorios. Sumar la venta de dos locales contra
  // la de tres del año pasado dibujaría un desplome que no ha ocurrido.
  const parejaDelDia = (r: { id: string }): { hoy: number; anterior: number } | null => {
    const hoyNeto = totalDe.get(r.id)?.net ?? null;
    const anterior = delDia.priorByRestaurant.get(r.id)?.net ?? null;
    if (hoyNeto === null || anterior === null) return null;
    return { hoy: hoyNeto, anterior };
  };
  const parejas = esHoy
    ? []
    : restauranteVisibles
        .map(parejaDelDia)
        .filter((p): p is { hoy: number; anterior: number } => p !== null);
  const yoyDia =
    parejas.length === 0
      ? null
      : growthPct(
          parejas.reduce((a, p) => a + p.hoy, 0),
          parejas.reduce((a, p) => a + p.anterior, 0),
        );
  const ventaAnterior = parejas.length === 0 ? null : parejas.reduce((a, p) => a + p.anterior, 0);

  // España solo se enfrenta al día cuando el día ya está cerrado: en el día
  // vivo no hay interanual propio contra el que ponerla, por la misma razón
  // (de 2025 no hay venta hora a hora en ninguna fuente).
  const nacionalDelDia = esHoy ? null : delDia.nationalYoy;

  const etiquetaHero =
    activo === TODOS
      ? `VENTA REAL ACUM. · ${delDia.restaurants.length} LOCALES`
      : `VENTA REAL ACUM. · ${restauranteActivo?.name.toUpperCase() ?? ""}`;

  const yoyDeLocal = (id: string): number | null => {
    if (esHoy) return null;
    const pareja = parejaDelDia({ id });
    return pareja === null ? null : growthPct(pareja.hoy, pareja.anterior);
  };

  return (
    <>
      {cabecera}

      <Freshness
        runs={delDia.runs}
        restaurants={restauranteVisibles}
        dailyStatusByRestaurant={delDia.dailyStatusByRestaurant}
        sinPrevision={sinPrevision}
        closed={!esHoy}
        provenance={procedenciaVisible}
      />

      {!unico && (
        <Tabs restaurants={delDia.restaurants} activo={activo} onSeleccion={onSeleccion} />
      )}

      <Hero
        label={etiquetaHero}
        totals={totales}
        currentHour={
          filaEnCurso && horaEnCurso !== null ? { hour: horaEnCurso, row: filaEnCurso } : null
        }
        reference={previsionDelDia}
        yoy={yoyDia}
        national={nacionalDelDia}
        difference={differencePp(yoyDia, nacionalDelDia)}
        yoyNote={notaDelDia(esHoy, ventaAnterior, localesSinCaptura, !esHoy && nacionalDelDia === null)}
      />

      {activo === TODOS ? (
        <section className="cards">
          {delDia.restaurants.map((r) => (
            <LocalCard
              key={r.id}
              restaurant={r}
              rows={delDia.hoursByRestaurant.get(r.id) ?? []}
              objectives={delDia.objectivesByRestaurant.get(r.id) ?? null}
              times={delDia.serviceTimesByRestaurant.get(r.id) ?? null}
              currentHour={horaEnCurso}
              yoy={yoyDeLocal(r.id)}
              onSelect={() => onSeleccion(r.id)}
            />
          ))}
        </section>
      ) : (
        <section className="detailView">
          <HourlyChart rows={filasVisibles} currentHour={horaEnCurso} />
          <HourlyTable
            rows={filasVisibles}
            totals={totales}
            restaurant={restauranteActivo}
            objectives={objetivos}
            times={tiempos}
            currentHour={horaEnCurso}
          />
        </section>
      )}
    </>
  );
}

function MonthScreen({
  seleccion,
  onSeleccion,
}: {
  seleccion: string;
  onSeleccion: (id: string) => void;
}) {
  // El último mes que se puede mirar es el del último día CERRADO: el día 1 de
  // un mes no hay nada suyo que enseñar. Se recalcula con el reloj para que al
  // cruzar las 06:00 el mes nuevo quede al alcance de la flecha.
  const cierre = useLastClosedDay();
  const ultimo = monthKeyOf(cierre);
  const [month, setMonth] = useState<MonthKey>(() =>
    resolveMonth(new URLSearchParams(window.location.search).get(MONTH_PARAM), {
      latest: monthKeyOf(cierre),
      earliest: PRIMER_MES,
      // Se abre por el mes que se puede leer, no siempre por el vivo: el día 2
      // de cada mes, "agosto en curso · 1 de 31 días" no resume nada. El vivo
      // sigue estando a una flecha, y un enlace con `?m=` llega igual.
      fallback: monthKeyOf(cierre),
    }),
  );

  // El botón "atrás" del móvil debe volver al mes anterior, no salir de la app.
  useEffect(() => {
    const onPop = () =>
      setMonth(
        resolveMonth(new URLSearchParams(window.location.search).get(MONTH_PARAM), {
          latest: ultimo,
          earliest: PRIMER_MES,
          fallback: monthKeyOf(cierre),
        }),
      );
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [ultimo, cierre]);

  const irAMes = (key: MonthKey) => {
    const url = new URL(window.location.href);
    // La dirección sin parámetro significa "el mes con el que abre la app",
    // que no siempre es el vivo: quitarlo al ir al vivo haría que una recarga
    // saltara de vuelta al anterior.
    if (key === monthKeyOf(cierre)) url.searchParams.delete(MONTH_PARAM);
    else url.searchParams.set(MONTH_PARAM, key);
    window.history.pushState({}, "", url);
    setMonth(key);
  };

  const { data, loading, error } = useMonth(month, cierre);
  const delMes = data && data.month === month ? data : null;

  if (loading && !delMes) return <div className="splash">Cargando el mes…</div>;

  if (error) {
    return (
      <div className="splash splash--error">
        <p>No se han podido cargar los datos del mes.</p>
        <p className="splash__detail">{error}</p>
      </div>
    );
  }

  if (!delMes) return <div className="splash">Sin datos</div>;

  if (delMes.restaurants.length === 0) {
    return (
      <div className="splash splash--error">
        <p>Tu usuario no tiene ningún restaurante asignado.</p>
        <p className="splash__detail">Pide que te den de alta para poder ver los datos.</p>
      </div>
    );
  }

  const unico = delMes.restaurants.length === 1;
  const activo = unico ? (delMes.restaurants[0]?.id ?? TODOS) : seleccion;

  return (
    <>
      <header className="topbar">
        <div className="topbar__brand">
          <Logo size={30} />
          <div className="topbar__titles">
            <span className="topbar__kicker">RESUMEN MENSUAL</span>
            <MonthNav
              month={month}
              latest={ultimo}
              earliest={delMes.earliestMonth ?? month}
              onChange={irAMes}
            />
          </div>
        </div>
      </header>

      <MonthStatus month={month} windowEnd={delMes.windowEnd} />

      {!unico && (
        <Tabs restaurants={delMes.restaurants} activo={activo} onSeleccion={onSeleccion} />
      )}

      <MonthView data={delMes} selected={activo} />
    </>
  );
}

/** Por qué las comparaciones del día dicen lo que dicen, o por qué no dicen nada. */
function notaDelDia(
  esHoy: boolean,
  ventaAnterior: number | null,
  localesSinCaptura: number,
  sinNacional: boolean,
): string {
  const partes: string[] = [];

  if (esHoy) {
    partes.push("El interanual espera al cierre del día");
  } else if (ventaAnterior === null) {
    partes.push("Sin venta del mismo día de la semana del año anterior");
  } else {
    // Ambos comparables usan el mismo día equivalente de la semana.
    partes.push(sinNacional ? "YoY mismo día de la semana · sin comparable de España ese día" : "YoY mismo día de la semana · vs ES en puntos");
  }

  if (localesSinCaptura > 0) {
    // Se dice porque el ámbito del titular cambia.
    partes.push(
      `⚠ ${localesSinCaptura} ${localesSinCaptura === 1 ? "local sin captura" : "locales sin captura"}: fuera de venta, objetivo e interanual`,
    );
  }

  return partes.join(" · ");
}

/** Suma tratando el hueco como hueco: null + null sigue siendo null. */
function suma(a: number | null, b: number | null): number | null {
  if (a === null) return b;
  if (b === null) return a;
  return a + b;
}

/** Suma que exige que estén TODOS: si falta uno, no hay total que dar. */
function sumaOpcional(valores: (number | null)[]): number | null {
  if (valores.length === 0 || valores.some((v) => v === null)) return null;
  return valores.reduce<number>((a, b) => a + (b as number), 0);
}
