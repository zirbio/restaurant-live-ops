import { DASH, num, pct, signedNum } from "../lib/format";
import type { Restaurant } from "../lib/types";

/**
 * La venta del mes de cada restaurante: cuánto, frente al objetivo, frente al
 * año pasado y frente a España.
 *
 * SOLO euros. Los clientes tenían aquí una segunda rejilla con los tres locales
 * repetidos, y en la pestaña de uno enseñaba también los otros dos; ahora van en
 * el titular, que sí responde a la pestaña que se está mirando (`GuestStrip`).
 */

export interface MonthRowData {
  restaurant: Restaurant;
  net: number | null;
  targetDiff: number | null;
  yoy: number | null;
  vsEs: number | null;
}

export interface MonthTotalRow {
  net: number | null;
  targetDiff: number | null;
  yoy: number | null;
  vsEs: number | null;
}

export function MonthTable({
  rows,
  total,
  note,
}: {
  rows: MonthRowData[];
  total: MonthTotalRow;
  note: string;
}) {
  return (
    <section className="monthTables">
      <div className="monthTable">
        <div className="monthTable__head">
          <span className="monthTable__kpi">VENTA €</span>
          <span className="ta-r">REAL €</span>
          <span className="ta-r">Δ OBJ €</span>
          <span className="ta-r">YoY</span>
          <span className="ta-r">vs ES</span>
        </div>
        {rows.map((r) => (
          <div className="monthTable__row" key={`v${r.restaurant.id}`}>
            <span className="monthTable__name">{r.restaurant.name}</span>
            <span className="ta-r strong">{num(r.net)}</span>
            <Delta value={r.targetDiff} fuerte />
            <Porcentaje value={r.yoy} />
            <Puntos value={r.vsEs} />
          </div>
        ))}
        <div className="monthTable__foot">
          <span className="monthTable__name">Total</span>
          <span className="ta-r">{num(total.net)}</span>
          <Delta value={total.targetDiff} />
          <Porcentaje value={total.yoy} />
          <Puntos value={total.vsEs} />
        </div>

        <p className="monthTable__note">{note}</p>
      </div>
    </section>
  );
}

function Delta({ value, fuerte }: { value: number | null; fuerte?: boolean }) {
  if (value === null) return <span className="ta-r dim">{DASH}</span>;
  return (
    <span className={`ta-r ${fuerte ? "strong" : ""} ${value >= 0 ? "is-pos" : "is-neg"}`}>
      {signedNum(value)}
    </span>
  );
}

function Porcentaje({ value }: { value: number | null }) {
  if (value === null) return <span className="ta-r dim">{DASH}</span>;
  return <span className={`ta-r ${value >= 0 ? "is-pos" : "is-neg"}`}>{pct(value)}</span>;
}

function Puntos({ value }: { value: number | null }) {
  if (value === null) return <span className="ta-r dim">{DASH}</span>;
  return (
    <span className={`ta-r ${value >= 0 ? "is-pos" : "is-neg"}`}>
      {pct(value).replace(" %", "")} pp
    </span>
  );
}
