import { useState } from "react";

import { DASH, eur, num, pct, secs, signedEur, signedNum, staffing } from "../lib/format";
import { counterGc, deviation, serviceLight, ticketMedio } from "../lib/metrics";
import type { DayTotals, HourRow, Objectives, Restaurant, ServiceTimes } from "../lib/types";

/**
 * Tabla densa hora a hora, con el panel de detalle que se despliega al tocar.
 *
 * La columna F/A son las personas fichadas y las asignadas en esa hora, de
 * la fuente de personal. En las horas que aún no han empezado el lado de fichados va con
 * raya: un 0 diría que no hay nadie dentro, que no es lo mismo que "todavía no
 * ha pasado".
 *
 * Los tiempos de la fila TOT son los del día que da la fuente de ventas, no una media de la
 * columna: la fuente de ventas los pondera por pedidos y coches.
 */
export function HourlyTable({
  rows,
  totals: totales,
  restaurant,
  objectives,
  times,
  currentHour,
}: {
  rows: HourRow[];
  /**
   * Los mismos totales que enseña el resumen de arriba, calculados sobre
   * TODAS las horas del día. Recalcularlos aquí sobre las filas visibles
   * descontaría la previsión de las horas escondidas y el pie contradiría
   * al resumen.
   */
  totals: DayTotals;
  restaurant: Restaurant | null;
  objectives: Objectives | null;
  /** Los del día que da la fuente de ventas. Nulo si de este día no hay fila de totales. */
  times: ServiceTimes | null;
  /** Nulo en un día cerrado: allí ninguna hora está "en curso". */
  currentHour: number | null;
}) {
  const [abierta, setAbierta] = useState<number | null>(null);
  const sinDriveThrough = restaurant !== null && !restaurant.has_drive_through;
  // Un restaurante sin servicio en vehículo tampoco tiene OEPE del día.
  const oepeDelDia = sinDriveThrough ? null : (times?.oepe ?? null);

  return (
    <div className="table">
      <div className="table__head">
        <span>H</span>
        <span className="ta-r">PROY</span>
        <span className="ta-r">REAL</span>
        <span className="ta-r">Δ €</span>
        <span className="ta-r">Δ GC</span>
        <span className="ta-r table__sep">F/A</span>
        <span className="ta-r table__sep">KVS</span>
        <span className="ta-r">R2P</span>
        <span className="ta-r">OEPE</span>
      </div>

      {rows.map((r) => {
        const enCurso = r.hour === currentHour;
        const desv = deviation(r.net, r.proj_sales);
        const dGc = r.gc !== null && r.proj_gc !== null ? r.gc - Math.round(r.proj_gc) : null;
        // Sin servicio en vehículo, OEPE no existe: no es un cero.
        const oepe = sinDriveThrough ? null : r.oepe;

        return (
          <div key={r.hour} className="table__group">
            <button
              type="button"
              className={`table__row ${enCurso ? "is-live" : ""} ${abierta === r.hour ? "is-open" : ""}`}
              onClick={() => setAbierta(abierta === r.hour ? null : r.hour)}
            >
              <span className={`table__hour ${enCurso ? "is-live" : ""}`}>
                {String(r.hour).padStart(2, "0")}
              </span>
              <span className="ta-r muted">{num(r.proj_sales)}</span>
              <span className="ta-r strong">{num(r.net)}</span>
              <span className={`ta-r strong ${color(desv.euros)}`}>{signedNum(desv.euros)}</span>
              <span className={`ta-r ${color(dGc)}`}>{signedNum(dGc)}</span>
              <span className="ta-r table__sep muted">
                {staffing(r.clocked, r.assigned, r.clipped)}
              </span>
              <span className={`ta-r table__sep strong ${luz(r.kvs, objectives?.kvs)}`}>
                {secs(r.kvs)}
              </span>
              <span className={`ta-r strong ${luz(r.r2p, objectives?.r2p)}`}>{secs(r.r2p)}</span>
              <span className={`ta-r strong ${luz(oepe, objectives?.oepe)}`}>{secs(oepe)}</span>
            </button>

            {abierta === r.hour && (
              <div className="detail">
                <Celda etiqueta="VENTA REAL" valor={eur(r.net)} />
                <Celda etiqueta="DESVIACIÓN" valor={signedEur(desv.euros)} clase={color(desv.euros)} />
                <Celda etiqueta="% vs PROY" valor={pct(desv.pct)} clase={color(desv.pct)} />
                <Celda
                  etiqueta="GC REAL / PROY"
                  valor={`${num(r.gc)} / ${num(r.proj_gc)}`}
                  clase={color(dGc)}
                />
                <Celda etiqueta="TICKET MEDIO" valor={eur(ticketMedio(r.net, r.gc))} />
                {/*
                  El desglose por canal, que el diseño no muestra arriba, va en
                  CLIENTES y no en euros: los coches de servicio en vehículo y los pedidos de
                  Delivery son transacciones y suman dentro del guest count de
                  la fila, así que las tres cifras cuadran con el GC REAL de
                  arriba. Mostrador+kiosko es la resta, igual que en euros.
                */}
                <Celda etiqueta="MOSTRADOR+KIOSKO" valor={num(counterGc(r))} />
                <Celda
                  etiqueta="SERVICIO EN VEHÍCULO"
                  valor={sinDriveThrough ? DASH : num(r.drive_through_cars)}
                />
                <Celda etiqueta="DELIVERY" valor={num(r.delivery_count)} />
              </div>
            )}
          </div>
        );
      })}

      <div className="table__foot">
        <span>TOT</span>
        <span className="ta-r muted">{num(totales.projToNow)}</span>
        <span className="ta-r strong">{num(totales.net)}</span>
        <span className={`ta-r ${color(deviation(totales.net, totales.projToNow).euros)}`}>
          {signedNum(deviation(totales.net, totales.projToNow).euros)}
        </span>
        <span className="ta-r">
          {signedNum(
            totales.gc !== null && totales.projGcToNow !== null
              ? totales.gc - Math.round(totales.projGcToNow)
              : null,
          )}
        </span>
        <span className="ta-r table__sep muted">{DASH}</span>
        <span className={`ta-r table__sep ${luz(times?.kvs, objectives?.kvs)}`}>
          {secs(times?.kvs ?? null)}
        </span>
        <span className={`ta-r ${luz(times?.r2p, objectives?.r2p)}`}>{secs(times?.r2p ?? null)}</span>
        <span className={`ta-r ${luz(oepeDelDia, objectives?.oepe)}`}>{secs(oepeDelDia)}</span>
      </div>

      <p className="table__note">
        Objetivos del mes: KVS ≤ {secs(objectives?.kvs)} · R2P ≤ {secs(objectives?.r2p)} · OEPE ≤{" "}
        {secs(objectives?.oepe)}. F/A = personal fichado y asignado en esa hora. El ⚠ marca una
        hora con algún fichaje sin cerrar: ahí los fichados van corregidos a la baja, y parte de
        la diferencia puede no ser una ausencia.
      </p>
    </div>
  );
}

function Celda({
  etiqueta,
  valor,
  clase,
}: {
  etiqueta: string;
  valor: string;
  clase?: string;
}) {
  return (
    <div className="detail__cell">
      <span className="detail__label">{etiqueta}</span>
      <span className={`detail__value ${clase ?? ""}`}>{valor}</span>
    </div>
  );
}

function color(n: number | null | undefined): string {
  if (n === null || n === undefined) return "dim";
  return n >= 0 ? "is-pos" : "is-neg";
}

function luz(valor: number | null | undefined, objetivo: number | null | undefined): string {
  const l = serviceLight(valor, objetivo);
  return l === "none" ? "dim" : `light-${l}`;
}
