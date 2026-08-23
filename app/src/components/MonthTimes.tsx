import { useState } from "react";

import { DASH, secs } from "../lib/format";
import { monthAxisLabel, monthShortLabel, type MonthKey } from "../lib/month";
import { serviceLight } from "../lib/metrics";
import type { TrendPoint } from "../lib/monthly";
import type { Light, Objectives, Restaurant } from "../lib/types";
import { ServiceTrendChart } from "./ServiceTrendChart";

/**
 * Tiempos de servicio del mes y su tendencia.
 *
 * Con un restaurante elegido se ve su tendencia. En la vista de conjunto se
 * conserva una fila por restaurante: los tiempos no se promedian entre ellos.
 */

/** Un solo mapa vacío para todos: uno nuevo por repintado no lo necesita nadie. */
const VACIO: Map<MonthKey, Objectives> = new Map();

export interface LocalTimes {
  restaurant: Restaurant;
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
  objectives: Objectives | null;
}

export function MonthTimes({
  single,
  byLocal,
  trends,
  currentTrends,
  objectives,
  month,
  partialDays,
  trendMonths,
  excludedDays,
  unavailableDays,
  missingDailyCloses,
  missingOfficialSnapshots,
}: {
  /** El restaurante elegido, o null en la vista de conjunto. */
  single: LocalTimes | null;
  byLocal: LocalTimes[];
  /** La tendencia de CADA restaurante. Nunca una mezclada. */
  trends: Map<string, TrendPoint[]>;
  /** Media acumulada, un punto por día cerrado del mes seleccionado. */
  currentTrends: Map<string, TrendPoint[]>;
  /** Objetivos por restaurante y mes: cada mes se juzga con el suyo. */
  objectives: Map<string, Map<MonthKey, Objectives>>;
  /** El mes que se está mirando. */
  month: MonthKey;
  /**
   * Días cubiertos y días del mes cuando el mes en curso aún no ha cerrado.
   *
   * Null si el mes está entero. El último punto de la tendencia es ese mes a
   * medias —el 3 de agosto son dos días—, y sin decirlo se lee al lado de doce
   * meses completos como si valiera lo mismo.
   */
  partialDays: { covered: number; total: number } | null;
  /** Meses con dato de verdad en la tendencia. */
  trendMonths: MonthKey[];
  /** Días descartados por traer un tiempo imposible. */
  excludedDays: number;
  /** Días cuyo KVS no se puede llevar con exactitud a la ventana 06→06. */
  unavailableDays: number;
  /** Cierres diarios de la fuente de ventas que deberían existir en la ventana y faltan. */
  missingDailyCloses: number;
  /** Fotografías oficiales R2P/OEPE que faltan en la ventana. */
  missingOfficialSnapshots: number;
}) {
  const [view, setView] = useState<"current" | "trend">("current");
  const primero = trendMonths[0];
  const ultimo = trendMonths[trendMonths.length - 1];
  const rangoHistorico =
    primero && ultimo ? `${monthShortLabel(primero)} → ${monthShortLabel(ultimo)}` : "";
  const ultimoDia = [...currentTrends.values()]
    .flatMap((puntos) => puntos.map((p) => Number(p.month.slice(8))))
    .reduce((maximo, dia) => Math.max(maximo, dia), 0);
  const rangoActual = ultimoDia > 0 ? `1 → ${ultimoDia} ${monthAxisLabel(month)}` : "";
  const etiquetaActual = partialDays === null ? "MEDIA MES" : "MES EN CURSO";

  return (
    <section className="monthTimes">
      <div className="monthTimes__box">
        <div className="monthTimes__head">
          <span className="monthTimes__title">
            {single ? "TIEMPOS DE SERVICIO" : "TIEMPOS DE SERVICIO POR LOCAL"}
          </span>
          <span className="monthTimes__span">
            {view === "current" ? rangoActual : rangoHistorico}
          </span>
        </div>

        <div className="monthTimes__toggle" role="tablist" aria-label="Periodo de los tiempos">
          <button
            type="button"
            role="tab"
            aria-selected={view === "current"}
            className={view === "current" ? "is-active" : ""}
            onClick={() => setView("current")}
          >
            {etiquetaActual}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={view === "trend"}
            className={view === "trend" ? "is-active" : ""}
            onClick={() => setView("trend")}
          >
            12 MESES
          </button>
        </div>

        {single ? (
          <Local
            times={single}
            trend={
              view === "current"
                ? (currentTrends.get(single.restaurant.id) ?? [])
                : (trends.get(single.restaurant.id) ?? [])
            }
            objectives={objectives.get(single.restaurant.id) ?? VACIO}
            month={month}
            partialDays={partialDays}
            axisMode={view === "current" ? "day" : "month"}
          />
        ) : (
          /* Cada restaurante con SU trío y SU tendencia. Ninguna línea mezcla
             locales: lo que se apila son tres series independientes, no una
             media. */
          byLocal.map((l) => (
            <Local
              key={l.restaurant.id}
              times={l}
              trend={
                view === "current"
                  ? (currentTrends.get(l.restaurant.id) ?? [])
                  : (trends.get(l.restaurant.id) ?? [])
              }
              objectives={objectives.get(l.restaurant.id) ?? VACIO}
              month={month}
              partialDays={partialDays}
              axisMode={view === "current" ? "day" : "month"}
              titulo={l.restaurant.name}
            />
          ))
        )}

        <p className="monthTimes__note">
          {nota({
            locales: single ? [single] : byLocal,
            objectives,
            trendMonths,
            partialDays,
            excludedDays,
            unavailableDays,
            missingDailyCloses,
            missingOfficialSnapshots,
            view,
          })}
        </p>
      </div>
    </section>
  );
}

function Local({
  times,
  trend,
  objectives,
  month,
  partialDays,
  axisMode,
  titulo,
}: {
  times: LocalTimes;
  trend: TrendPoint[];
  objectives: Map<MonthKey, Objectives>;
  month: MonthKey;
  partialDays: { covered: number; total: number } | null;
  axisMode: "month" | "day";
  /** Solo en la vista de conjunto: con un local elegido, ya está en la cabecera. */
  titulo?: string;
}) {
  return (
    <div className="monthTimes__local">
      {titulo && <span className="monthTimes__localName">{titulo}</span>}
      <div className="monthTimes__chips">
        <Chip label="KVS" value={times.kvs} objective={times.objectives?.kvs} />
        <Chip label="R2P" value={times.r2p} objective={times.objectives?.r2p} />
        <Chip label="OEPE" value={times.oepe} objective={times.objectives?.oepe} />
      </div>
      {/* La caja solo si hay algo que dibujar. `trend.length > 0` no servía:
          la tendencia trae un punto por mes aunque ese local no tenga ni un
          dato, así que un restaurante sin tiempos dejaba un recuadro vacío con
          su relleno y sin explicación. Sus pastillas en raya son la respuesta. */}
      {trend.some((p) => p.kvs !== null || p.r2p !== null || p.oepe !== null) && (
        <div className="monthTimes__chart">
          <ServiceTrendChart
            points={trend}
            objectives={objectives}
            month={month}
            partialDays={axisMode === "month" ? partialDays : null}
            axisMode={axisMode}
          />
        </div>
      )}
    </div>
  );
}

function Chip({
  label,
  value,
  objective,
}: {
  label: string;
  value: number | null;
  objective: number | null | undefined;
}) {
  // Se juzga la cifra REDONDEADA, que es la que se enseña: `secs()` imprime
  // "81" tanto para 80,6 como para 81,3, y con el valor crudo el mismo número
  // salía verde una vez y ámbar la otra. Igual que en las franjas.
  const redondeado = value === null ? null : Math.round(value);
  const l: Light = serviceLight(redondeado, objective);
  return (
    <div className={`time time--${l}`}>
      <span className="time__label">{label}</span>
      <span className="time__value">{redondeado === null ? DASH : secs(redondeado)}</span>
    </div>
  );
}

/**
 * El pie del bloque de tiempos, en una línea.
 *
 * Los objetivos ya no se enumeran aquí: cada franja lleva el suyo escrito y
 * dibujado. Lo que sí hay que decir es que la escalera punteada es el objetivo
 * de CADA mes y no una raya fija, porque baja a lo largo del año y sin eso
 * parecería un dibujo raro.
 *
 * Lo demás se DERIVA de lo que hay en pantalla en vez de afirmarse siempre: el
 * gris solo se explica si queda algún mes sin objetivo —desde 2027 no quedará
 * ninguno—, y el local sin servicio en vehículo solo se nombra si está a la vista.
 */
function nota({
  locales,
  objectives,
  trendMonths,
  partialDays,
  excludedDays,
  unavailableDays,
  missingDailyCloses,
  missingOfficialSnapshots,
  view,
}: {
  locales: LocalTimes[];
  objectives: Map<string, Map<MonthKey, Objectives>>;
  trendMonths: MonthKey[];
  partialDays: { covered: number; total: number } | null;
  excludedDays: number;
  unavailableDays: number;
  missingDailyCloses: number;
  missingOfficialSnapshots: number;
  view: "current" | "trend";
}): string {
  // Lo primero que hay que decir es de dónde sale cada cifra, porque no todas
  // salen del mismo sitio: R2P y OEPE son la cifra que PUBLICA la fuente de ventas, y el KVS
  // hay que derivarlo de los días porque la fuente de ventas no lo publica mensual. Meterlos
  // en el mismo saco —"media del mes ponderada por clientes", que es lo que
  // decía este pie— daba a entender que los tres eran cálculo nuestro.
  const partes =
    view === "current"
      ? [
          "curva, media acumulada desde el día 1",
          "KVS ponderado por clientes",
          "R2P y OEPE, acumulado mensual oficial capturado cada día de la fuente de ventas",
          "punteado, objetivo del mes",
          "hueco, día sin fotografía oficial",
        ]
      : [
          "R2P y OEPE, la cifra mensual de la fuente de ventas",
          "KVS, media del mes ponderada por clientes (la fuente de ventas no lo publica)",
          "punteado, el objetivo de cada mes",
        ];

  // El gris se explica solo si queda alguno a la vista: hoy son los meses de
  // 2025, que no tienen objetivo guardado, y desde 2027 no quedará ninguno.
  const hayGrises =
    view === "trend" &&
    trendMonths.some((m) => locales.some((l) => !objectives.get(l.restaurant.id)?.has(m)));
  if (hayGrises) partes.push("en gris, los meses sin objetivo guardado");

  if (view === "trend" && partialDays) {
    partes.push(`* mes en curso, ${partialDays.covered} de ${partialDays.total} días`);
  }

  // Sin esto, un restaurante sin servicio en vehículo enseñaría OEPE como
  // ausente sin explicar que la métrica no le aplica.
  const sinDriveThrough = locales.filter((l) => !l.restaurant.has_drive_through);
  if (sinDriveThrough.length > 0) {
    partes.push(`${sinDriveThrough.map((l) => l.restaurant.name).join(" y ")}, sin servicio en vehículo: no hay OEPE`);
  }

  // Solo el KVS se calcula, así que solo él pierde días: decir "días excluidos"
  // a secas señalaría a las tres cifras, y dos de ellas vienen dadas.
  if (excludedDays > 0) {
    partes.push(
      `${excludedDays} ${excludedDays === 1 ? "día excluido" : "días excluidos"} del KVS por tiempo imposible`,
    );
  }

  if (unavailableDays > 0) {
    partes.push(
      `KVS mensual en raya: ${unavailableDays} ${unavailableDays === 1 ? "día no tiene" : "días no tienen"} ponderación 06→06 exacta`,
    );
  }

  if (missingDailyCloses > 0) {
    partes.push(
      missingDailyCloses === 1
        ? "⚠ falta 1 cierre diario de la fuente de ventas"
        : `⚠ faltan ${missingDailyCloses} cierres diarios de la fuente de ventas`,
    );
  }

  if (missingOfficialSnapshots > 0) {
    partes.push(
      missingOfficialSnapshots === 1
        ? "⚠ falta 1 fotografía oficial de la fuente de ventas"
        : `⚠ faltan ${missingOfficialSnapshots} fotografías oficiales de la fuente de ventas`,
    );
  }

  return partes.join(" · ");
}
