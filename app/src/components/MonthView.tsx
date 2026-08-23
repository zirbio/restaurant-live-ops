import { useMemo } from "react";

import type { MonthData } from "../data/useMonth";
import { fechaCorta, num } from "../lib/format";
import {
  daysBetween,
  daysInMonth,
  firstDayOfMonth,
  lastDayOfMonth,
  monthKeyOf,
  monthLabel,
  type MonthKey,
} from "../lib/month";
import { closedLaborNote } from "../lib/monthClosing";
import {
  addTotals,
  blendedLaborCost,
  blendedLaborTarget,
  byDay,
  closingDaysBreakdown,
  closingFor,
  closingOldestComputedAt,
  closingTotal,
  costParamsFor,
  differencePp,
  growthPct,
  implausibleDays,
  laborPct as laborPctDe,
  missingTargetDays,
  monthTotals,
  nationalYoy,
  publishableLaborCost,
  publishableTarget,
  publishableTargetGc,
  publishablePriorVphh,
  publishableVphh,
  publishedLaborCost,
  weightedServiceTime,
  type MonthProjectionRow,
  type MonthTotals,
  type TrendPoint,
} from "../lib/monthly";
import { cumulativeServiceTrend, officialTrend, visibleTrendMonths } from "../lib/serviceBands";
import type { Restaurant } from "../lib/types";
import { MonthHero } from "./MonthHero";
import { MonthPerformance, type PerformanceRowData } from "./MonthPerformance";
import { MonthTable, type MonthRowData } from "./MonthTable";
import { MonthTimes, type LocalTimes } from "./MonthTimes";

const TODOS = "all";

/** Lo que se calcula una vez por carga, no en cada repintado. */
interface Calculado {
  diasVentana: string[];
  porLocal: Map<string, MonthTotals>;
  conjunto: MonthTotals | null;
  tiemposPorLocal: Map<string, LocalTimes>;
  excluidosPorLocal: Map<string, number>;
  noDisponiblesPorLocal: Map<string, number>;
  tendenciaPorLocal: Map<string, TrendPoint[]>;
  mediaAcumuladaPorLocal: Map<string, TrendPoint[]>;
  mesesConDato: MonthKey[];
}

/**
 * La pantalla del mes.
 *
 * Todo lo que se pinta aquí se calcula sobre la MISMA ventana de días: del día
 * 1 al último cerrado. Venta, objetivo, interanual, horas y tiempos comparten
 * ese corte, y por eso las cifras del titular, de la tabla y del pie dicen lo
 * mismo. Cada bloque que no puede calcularse enseña raya y su motivo; ninguno
 * rellena con ceros.
 *
 * Las reglas que deciden si una cifra se publica viven en `lib/monthly.ts`
 * (`publishableVphh`, `blendedLaborTarget`): son lógica de negocio y tienen
 * que poder probarse sin montar el componente.
 */
export function MonthView({
  data,
  selected,
}: {
  data: MonthData;
  /** Código de restaurante, o `all` para la vista de conjunto. */
  selected: string;
}) {
  const { month, windowEnd } = data;
  const esMesVivo = windowEnd !== lastDayOfMonth(month);

  const calculado = useMemo<Calculado>(() => {
    const diasVentana = windowEnd === null ? [] : daysBetween(firstDayOfMonth(month), windowEnd);
    const real = byDay(data.windowDays);

    const porLocal = new Map<string, MonthTotals>();
    const tiemposPorLocal = new Map<string, LocalTimes>();
    const excluidosPorLocal = new Map<string, number>();
    const noDisponiblesPorLocal = new Map<string, number>();
    const tendenciaPorLocal = new Map<string, TrendPoint[]>();
    const mediaAcumuladaPorLocal = new Map<string, TrendPoint[]>();

    // El eje arranca en el primer mes con dato y llega hasta el final: un mes
    // vacío de en medio se queda, para que la línea se corte ahí en vez de
    // cruzarlo con una recta que nadie ha medido.
    const conDato = new Set(data.trendDays.map((d) => monthKeyOf(d.sales_date)));
    const mesesConDato = visibleTrendMonths(data.trendMonths, conDato);

    for (const r of data.restaurants) {
      porLocal.set(
        r.id,
        monthTotals({
          restaurantId: r.id,
          calendarDays: diasVentana,
          real,
          prior: data.prior,
          targets: data.targets,
          hours: data.hours,
        }),
      );

      // Un solo barrido por restaurante para los tiempos: antes se filtraba y
      // se recorría la ventana entera unas veinte veces por repintado.
      const dias = data.windowDays.filter((d) => d.restaurant_id === r.id);
      // El R2P y el OEPE del mes son los que PUBLICA la fuente de ventas, no una media de los
      // días: la media se separa hasta 11 segundos de la cifra publicada y
      // llegó a invertir un veredicto. El KVS sí se deriva — la fuente de ventas no publica un
      // KVS mensual—, y coincide al dígito con el panel de referencia de la fuente mensual.
      const oficialDelMes = data.officialTimes.get(r.id)?.get(month);
      const fotografiaDelCierre = windowEnd
        ? data.officialTimeSnapshots.get(r.id)?.get(windowEnd)
        : undefined;
      const tiemposOficiales = fotografiaDelCierre ?? (esMesVivo ? undefined : oficialDelMes);
      const kvsDelMes = weightedServiceTime(dias, "kvs");
      tiemposPorLocal.set(r.id, {
        restaurant: r,
        kvs: kvsDelMes.value,
        r2p: tiemposOficiales?.r2p ?? null,
        // Sin servicio en vehículo, OEPE no existe: no es un cero.
        oepe: r.has_drive_through ? (tiemposOficiales?.oepe ?? null) : null,
        objectives: data.objectives.get(r.id)?.get(month) ?? null,
      });
      // Solo el KVS sale de los días, así que solo él puede perder alguno por
      // traer un tiempo imposible. Contar los tres exclusiones diría que se han
      // descartado días de unas cifras que ya no se calculan aquí.
      excluidosPorLocal.set(r.id, implausibleDays(dias, ["kvs"]));
      noDisponiblesPorLocal.set(r.id, kvsDelMes.unavailable);

      const suyosTendencia = data.trendDays.filter((d) => d.restaurant_id === r.id);
      const oficiales = data.officialTimes.get(r.id) ?? new Map();
      tendenciaPorLocal.set(
        r.id,
        officialTrend(suyosTendencia, mesesConDato, oficiales).map((p) =>
          // Un local sin servicio en vehículo no tiene línea de OEPE que dibujar.
          r.has_drive_through ? p : { ...p, oepe: null },
        ),
      );
      mediaAcumuladaPorLocal.set(
        r.id,
        cumulativeServiceTrend(
          dias,
          diasVentana,
          data.officialTimeSnapshots.get(r.id) ?? new Map(),
        ).map((p) =>
          // Sin servicio en vehículo tampoco existe una media de OEPE.
          r.has_drive_through ? p : { ...p, oepe: null },
        ),
      );
    }

    const conjunto = data.restaurants
      .map((r) => porLocal.get(r.id))
      .filter((t): t is MonthTotals => t !== undefined)
      .reduce<MonthTotals | null>((a, b) => (a === null ? b : addTotals(a, b)), null);

    return {
      diasVentana,
      porLocal,
      conjunto,
      tiemposPorLocal,
      excluidosPorLocal,
      noDisponiblesPorLocal,
      tendenciaPorLocal,
      mediaAcumuladaPorLocal,
      mesesConDato,
    };
  }, [data, esMesVivo, month, windowEnd]);

  const { diasVentana, porLocal, conjunto, tiemposPorLocal } = calculado;
  // El comparable de España existe también para el mes en curso, pero solo
  // sirve si llega al mismo día que la ventana propia.
  const nacional = nationalYoy(data.national.get(month), windowEnd);

  const activo =
    selected === TODOS ? null : (data.restaurants.find((r) => r.id === selected) ?? null);
  const totales = activo ? (porLocal.get(activo.id) ?? null) : conjunto;

  if (windowEnd === null || totales === null || totales.expectedDays === 0) {
    return (
      <div className="splash">
        <p>{monthLabel(month)} todavía no tiene ningún día cerrado.</p>
        <p className="splash__detail">
          Un día no cuenta hasta las 06:00 de la mañana siguiente, que es cuando cierra la rejilla
          de la fuente de ventas. Vuelve mañana o mira el mes anterior.
        </p>
      </div>
    );
  }

  const locales = activo ? [activo] : data.restaurants;

  // La previsión SOLO si cubre la ventana entera, y la misma para los tres
  // bloques: el titular, la tabla y los clientes no pueden discrepar.
  const objetivo = publishableTarget(totales);
  const objetivoGc = publishableTargetGc(totales);
  const diasSinPrevision = missingTargetDays(totales);

  // ── Titular ───────────────────────────────────────────────────────────────
  const yoy = growthPct(totales.comparableNet, totales.priorNet);
  const etiquetaHero = activo
    ? `VENTA ${mesEnMayusculas(month)} · ${activo.name.toUpperCase()}`
    : `VENTA ${mesEnMayusculas(month)} · ${data.restaurants.length} ${
        data.restaurants.length === 1 ? "LOCAL" : "LOCALES"
      }`;

  // ── Tabla por restaurante ─────────────────────────────────────────────────
  const filas: MonthRowData[] = data.restaurants.map((r) => {
    const t = porLocal.get(r.id);
    const suYoy = t ? growthPct(t.comparableNet, t.priorNet) : null;
    return {
      restaurant: r,
      net: t?.net ?? null,
      targetDiff: t ? resta(t.net, publishableTarget(t)) : null,
      yoy: suYoy,
      vsEs: differencePp(suYoy, nacional),
    };
  });

  const yoyConjunto = growthPct(conjunto?.comparableNet, conjunto?.priorNet);
  const totalTabla = {
    net: conjunto?.net ?? null,
    targetDiff: conjunto ? resta(conjunto.net, publishableTarget(conjunto)) : null,
    yoy: yoyConjunto,
    vsEs: differencePp(yoyConjunto, nacional),
  };

  // ── Productividad ─────────────────────────────────────────────────────────
  const objetivoMo = blendedLaborTarget(data.pctTargets, data.restaurants.length);

  // Cada local contra SU objetivo de mano de obra, que es lo que la tarjeta no
  // podía enseñar: los tres son muy distintos entre sí.
  const objetivoMoDe = (r: Restaurant): number | null =>
    data.pctTargets.find((p) => p.restaurant_id === r.id)?.target_pct ?? null;

  const filasKpi = data.restaurants.map((r) => {
    const t = porLocal.get(r.id);
    const suVphh = t ? publishableVphh(t) : null;
    return {
      restaurant: r,
      vphh: suVphh,
      vphhYoy: growthPct(suVphh, t ? publishablePriorVphh(t) : null),
    };
  });

  const vphhConjunto = conjunto ? publishableVphh(conjunto) : null;
  const totalKpi = {
    vphh: vphhConjunto,
    vphhYoy: growthPct(vphhConjunto, conjunto ? publishablePriorVphh(conjunto) : null),
  };

  // ── Tiempos de servicio ───────────────────────────────────────────────────
  const porLocalTiempos = data.restaurants
    .map((r) => tiemposPorLocal.get(r.id))
    .filter((t): t is LocalTimes => t !== undefined);

  const diasExcluidos = locales.reduce(
    (total, r) => total + (calculado.excluidosPorLocal.get(r.id) ?? 0),
    0,
  );
  const diasSinKvsExacto = locales.reduce(
    (total, r) => total + (calculado.noDisponiblesPorLocal.get(r.id) ?? 0),
    0,
  );

  const diasSinCaptura = totales.expectedDays - totales.days;
  const fotografiasOficialesAusentes = locales.reduce(
    (total, restaurant) =>
      total +
      diasVentana.filter(
        (day) => !data.officialTimeSnapshots.get(restaurant.id)?.has(day),
      ).length,
    0,
  );

  // En el mes vivo manda el cierre proyectado de la fuente mensual. En uno cerrado
  // manda el P&L real y, mientras no haya llegado, la estimación declarada.
  const cierre = (() => {
    if (esMesVivo) {
      const filas = data.restaurants.map((r) => {
        const p = closingFor(data.closingProjections, r.id, month);
        const pct = p ? laborPctDe(p.labor_cost_projected, p.sales_projected) : null;
        return {
          restaurant: r,
          sales: p?.sales_projected ?? null,
          laborPct: pct,
          laborDiff: resta(pct, objetivoMoDe(r)),
        };
      });
      // Sin ninguna proyección no se dibuja el bloque: una tabla de rayas se
      // leería como un dato que está a punto de llegar.
      if (filas.every((f) => f.sales === null)) return null;

      const t = closingTotal(
        data.closingProjections,
        data.restaurants.map((r) => r.id),
        month,
      );
      const pctTotal = t ? laborPctDe(t.cost, t.sales) : null;
      // El pie describe los locales que SÍ tienen proyección, nunca solo el
      // primero: cada uno publica su cuadrante con un horizonte propio.
      const disponibles = data.restaurants
        .map((r) => closingFor(data.closingProjections, r.id, month))
        .filter((p): p is MonthProjectionRow => p !== null);
      return {
        title: "CIERRE PROYECTADO",
        filas,
        total: {
          sales: t?.sales ?? null,
          laborPct: pctTotal,
          laborDiff: resta(pctTotal, objetivoMo),
        },
        nota: notaCierre(disponibles, filas.filter((f) => f.sales === null).length),
      };
    }

    const publicados = data.restaurants.map((r) => {
      const t = porLocal.get(r.id);
      const publicado = t
        ? publishedLaborCost(
            data.plActuals,
            r.id,
            month,
            publishableLaborCost(t, costParamsFor(data.costParams, r.id, windowEnd), month),
          )
        : null;
      return { restaurant: r, totals: t, publicado };
    });
    if (publicados.every((p) => p.publicado === null)) return null;

    const filas = publicados.map(({ restaurant, totals, publicado }) => {
      const sales = publicado?.net ?? totals?.net ?? null;
      const pct = laborPctDe(publicado?.cost ?? null, sales);
      return {
        restaurant,
        sales,
        laborPct: pct,
        laborDiff: resta(pct, objetivoMoDe(restaurant)),
      };
    });
    const agregado = blendedLaborCost(
      publicados.map(({ totals, publicado }) => ({
        published: publicado,
        sourceNet: totals?.net ?? null,
      })),
    );
    const estimados = publicados.filter((p) => p.publicado?.source === "estimado").length;
    const sinDato = publicados.filter((p) => p.publicado === null).length;
    const pctTotal = laborPctDe(agregado.cost, agregado.net);
    return {
      title:
        agregado.realCount === data.restaurants.length ? "CIERRE REAL" : "CIERRE DEL MES",
      filas,
      total: {
        sales: agregado.net,
        laborPct: pctTotal,
        laborDiff: resta(pctTotal, objetivoMo),
      },
      nota: closedLaborNote({
        actual: agregado.realCount,
        estimated: estimados,
        unavailable: sinDato,
        restaurants: data.restaurants.length,
      }),
    };
  })();

  const cierrePorLocal = new Map(cierre?.filas.map((fila) => [fila.restaurant.id, fila]) ?? []);
  const filasRendimiento: PerformanceRowData[] = filasKpi.map((fila) => {
    const filaCierre = cierrePorLocal.get(fila.restaurant.id);
    return {
      ...fila,
      laborPct: filaCierre?.laborPct ?? null,
      laborDiff: filaCierre?.laborDiff ?? null,
    };
  });
  const totalRendimiento = {
    ...totalKpi,
    laborPct: cierre?.total.laborPct ?? null,
    laborDiff: cierre?.total.laborDiff ?? null,
  };

  return (
    <>
      <MonthHero
        label={etiquetaHero}
        net={totales.net}
        target={objetivo}
        yoy={yoy}
        national={nacional}
        difference={differencePp(yoy, nacional)}
        targetLabel={
          diasVentana.length === daysInMonth(month)
            ? "OBJETIVO MES"
            : `OBJETIVO HASTA EL ${diasVentana.length}`
        }
        // Los clientes del ámbito elegido, no los de los tres locales: es lo
        // mismo que enseña la cifra grande de arriba, en clientes.
        guests={{
          count: totales.gc,
          targetDiff: resta(totales.gc, objetivoGc),
          yoy: growthPct(totales.comparableGc, totales.priorGc),
        }}
      />

      <MonthTable
        rows={filas}
        total={totalTabla}
        note={nota({
          comparables: totales.comparableDays,
          esperados: totales.expectedDays,
          hayEspana: nacional !== null,
          diasSinCaptura,
          diasSinPrevision,
        })}
      />

      <MonthPerformance
        rows={filasRendimiento}
        total={totalRendimiento}
        productivityNote={notaKpis({
          hours: conjunto?.hours ?? null,
          diasSinHoras: conjunto ? conjunto.expectedDays - conjunto.pairedDays : 0,
          esperados: conjunto?.expectedDays ?? 0,
          sinCierreProyectado: esMesVivo && cierre === null,
        })}
        closingTitle={cierre?.title ?? null}
        closingNote={cierre?.nota ?? null}
      />

      <MonthTimes
        single={activo ? (tiemposPorLocal.get(activo.id) ?? null) : null}
        byLocal={porLocalTiempos}
        trends={calculado.tendenciaPorLocal}
        currentTrends={calculado.mediaAcumuladaPorLocal}
        objectives={data.objectives}
        month={month}
        // El último punto de la tendencia es el mes en curso, y hasta que no
        // cierre son menos días que los demás: el 3 de agosto, dos.
        partialDays={
          diasVentana.length < daysInMonth(month)
            ? { covered: diasVentana.length, total: daysInMonth(month) }
            : null
        }
        trendMonths={calculado.mesesConDato}
        excludedDays={diasExcluidos}
        unavailableDays={diasSinKvsExacto}
        missingDailyCloses={diasSinCaptura}
        missingOfficialSnapshots={fotografiasOficialesAusentes}
      />
    </>
  );
}

function resta(a: number | null | undefined, b: number | null | undefined): number | null {
  if (a === null || a === undefined || b === null || b === undefined) return null;
  return a - b;
}

/**
 * El pie de la tabla de productividad, en una línea.
 *
 * Lleva las claves de las columnas y, detrás, las horas de la ventana. La mano
 * de obra vive únicamente en el bloque de cierre de la fuente mensual, no duplicada
 * en esta tabla.
 */
function notaKpis({
  hours,
  diasSinHoras,
  esperados,
  sinCierreProyectado,
}: {
  hours: number | null;
  diasSinHoras: number;
  esperados: number;
  /** Mes vivo sin ninguna proyección de cierre importada: el bloque no se dibuja. */
  sinCierreProyectado: boolean;
}): string {
  const partes = ["VPHH venta / horas fichadas · YoY mismo día de la semana"];

  const contexto = [hours === null ? null : `${num(hours)} h`].filter(
    (x): x is string => x !== null,
  );
  if (contexto.length > 0) partes.push(contexto.join(" · "));

  // El denominador va delante para que se entienda la unidad: en la vista de
  // conjunto son días de restaurante, no días de calendario.
  if (diasSinHoras > 0) {
    partes.push(`⚠ faltan horas en ${diasSinHoras} de ${esperados} días`);
  }
  // Sin fila importada el bloque de cierre no se dibuja, y desaparecer sin más
  // se lee como una avería. Se dice lo único que se sabe con certeza — que no
  // ha llegado proyección de la fuente mensual —, nunca el motivo concreto: puede ser
  // el tope sin publicar, los parámetros de coste o que la importación diaria
  // no ha corrido, y la app no tiene forma de distinguir cuál de los tres es.
  if (sinCierreProyectado) {
    partes.push("⚠ sin cierre proyectado: no ha llegado proyección de la fuente mensual");
  }
  return partes.join(" · ");
}

/**
 * El pie del cierre: de qué está hecha la proyección y de cuándo es.
 *
 * `disponibles` son solo los locales que SÍ tienen proyección ese mes — nunca
 * "el primero de la lista": `closingDaysBreakdown` imprime un número cuando
 * coinciden y su rango real cuando no, para no atribuir a los tres el reparto
 * de uno solo. Los tres cajones llevan su unidad y se marca que el rango es
 * ENTRE LOCALES (cada uno publica su cuadrante con un horizonte propio, no un
 * reparto del mismo mes en tres trozos): sin eso, "6-13 con cuadrante
 * publicado" en una frase de días del mes se lee como "los días 6 al 13", y
 * los tres cajones ya no suman los días de la ventana como sumaban cuando
 * describían un solo local. Y la fecha es la MÁS ANTIGUA de esos locales
 * (`closingOldestComputedAt`), no la del primero: si a uno se le despublica el
 * tope y su proyección deja de refrescarse, la del primero escondería justo la
 * vieja, y es esa la que de verdad avisa de un puente atascado.
 */
function notaCierre(disponibles: MonthProjectionRow[], sinProyeccion: number): string {
  const partes = ["proyección de la fuente mensual"];
  const reparto = closingDaysBreakdown(disponibles);
  if (reparto) {
    partes.push(
      `${reparto.actual} d fichados · ${reparto.scheduled} d con cuadrante publicado · ` +
        `${reparto.reference} d por referencia del recibo (rango entre locales)`,
    );
  }
  const masAntigua = closingOldestComputedAt(disponibles);
  if (masAntigua) {
    partes.push(`calculada el ${fechaCorta(masAntigua)}`);
  }
  if (sinProyeccion > 0) {
    // Se dice lo único que se sabe con certeza — que a esos locales no les ha
    // llegado proyección de la fuente mensual —, nunca el motivo concreto: puede ser
    // el tope sin publicar, los parámetros de coste o la importación de esa
    // mañana, y la app no tiene forma de distinguir cuál de los tres es. Es
    // la misma corrección que `notaKpis` aplicó dos commits antes.
    partes.push(
      `⚠ ${sinProyeccion} ${sinProyeccion === 1 ? "local" : "locales"} sin proyección de la fuente mensual este mes`,
    );
  }
  return partes.join(" · ");
}

function mesEnMayusculas(month: MonthKey): string {
  return (monthLabel(month).split(" ")[0] ?? "").toUpperCase();
}

/**
 * El pie de la tabla, en una línea.
 *
 * Dice qué es cada columna y nada más. Lo que había antes eran cuatro frases
 * explicando de dónde sale cada cifra, y eso se lee una vez: quien abre esta
 * pantalla todos los días necesita las claves, no el manual. El porqué de cada
 * cálculo vive en `la documentación técnica`, que es donde se consulta.
 *
 * Lo único que sobrevive entero es el aviso de días sin captura, porque no
 * explica un método: avisa de que la desviación pinta peor de lo que es.
 */
function nota({
  comparables,
  esperados,
  hayEspana,
  diasSinCaptura,
  diasSinPrevision,
}: {
  comparables: number;
  esperados: number;
  hayEspana: boolean;
  diasSinCaptura: number;
  diasSinPrevision: number;
}): string {
  const partes = [
    "Δ OBJ vs previsión la fuente de personal",
    `YoY mismo día de la semana (${comparables}/${esperados} d)`,
    hayEspana ? "vs ES en puntos" : "sin comparable de España este mes",
  ];
  if (diasSinCaptura > 0) {
    partes.push(
      `⚠ ${diasSinCaptura} ${diasSinCaptura === 1 ? "día sin captura" : "días sin captura"}: falta su venta, no su previsión`,
    );
  }
  if (diasSinPrevision > 0) {
    // Sin este aviso, la desviación desaparecería sin explicación.
    partes.push(
      `⚠ sin previsión de la fuente de personal en ${diasSinPrevision} ${diasSinPrevision === 1 ? "día" : "días"}: no hay Δ OBJ que dar`,
    );
  }
  return partes.join(" · ");
}
