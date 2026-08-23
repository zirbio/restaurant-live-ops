import { DASH, dec, pct, pctPlain, roundsToZero, signedDec } from "../lib/format";
import type { Restaurant } from "../lib/types";

/** Productividad y cierre del mes, unidos por restaurante en una sola tabla. */
export interface PerformanceRowData {
  restaurant: Restaurant;
  vphh: number | null;
  /** Interanual del VPHH contra los mismos días de la semana del año pasado. */
  vphhYoy: number | null;
  laborPct: number | null;
  /** Puntos porcentuales sobre el objetivo del mes. Negativo es bueno. */
  laborDiff: number | null;
}

export interface PerformanceTotalRow {
  vphh: number | null;
  vphhYoy: number | null;
  laborPct: number | null;
  laborDiff: number | null;
}

/**
 * Una sola lectura operativa por local.
 *
 * Productividad y cierre conservan sus fuentes y periodos propios; compartir
 * fila permite compararlos sin presentar dos listados de restaurantes. Las
 * cabeceras agrupadas y las dos notas mantienen explícita esa diferencia.
 */
export function MonthPerformance({
  rows,
  total,
  productivityNote,
  closingTitle,
  closingNote,
}: {
  rows: PerformanceRowData[];
  total: PerformanceTotalRow;
  productivityNote: string;
  closingTitle: string | null;
  closingNote: string | null;
}) {
  const hasClosing = closingTitle !== null;

  return (
    <section className="monthTables">
      <div
        className={`monthTable monthTable--performance ${
          hasClosing ? "" : "monthTable--performanceOnly"
        }`}
      >
        <div className="monthPerformance__groups">
          <span aria-hidden="true" />
          <span className="monthPerformance__group">PRODUCTIVIDAD</span>
          {hasClosing && <span className="monthPerformance__group">{closingTitle}</span>}
        </div>
        <div className="monthTable__head monthTable__head--performance">
          <span>LOCAL</span>
          <span className="ta-r">VPHH €</span>
          <span className="ta-r">YoY</span>
          {hasClosing && (
            <>
              <span className="ta-r">% MO</span>
              <span className="ta-r">Δ OBJ</span>
            </>
          )}
        </div>
        {rows.map((row) => (
          <PerformanceRow key={row.restaurant.id} row={row} hasClosing={hasClosing} />
        ))}
        <PerformanceRow total row={{ ...total, restaurant: null }} hasClosing={hasClosing} />

        <p className="monthTable__note monthPerformance__note">
          <span>PRODUCTIVIDAD · {productivityNote}</span>
          {hasClosing && closingNote !== null && (
            <span>
              {closingTitle} · {closingNote}
            </span>
          )}
        </p>
      </div>
    </section>
  );
}

function PerformanceRow({
  row,
  total = false,
  hasClosing,
}: {
  row: Omit<PerformanceRowData, "restaurant"> & { restaurant: Restaurant | null };
  total?: boolean;
  hasClosing: boolean;
}) {
  return (
    <div className={total ? "monthTable__foot" : "monthTable__row"}>
      <span className="monthTable__name">{row.restaurant?.name ?? "Total"}</span>
      <Cifra value={row.vphh} fuerte={!total} />
      <Interanual value={row.vphhYoy} />
      {hasClosing && (
        <>
          <Porcentaje value={row.laborPct} fuerte={!total} />
          <ManoDeObra value={row.laborDiff} />
        </>
      )}
    </div>
  );
}

function Cifra({ value, fuerte }: { value: number | null; fuerte?: boolean }) {
  if (value === null) return <span className="ta-r dim">{DASH}</span>;
  return <span className={`ta-r ${fuerte ? "strong" : ""}`}>{dec(value)}</span>;
}

/** Interanual del VPHH: producir más por hora que el año pasado es bueno. */
function Interanual({ value }: { value: number | null }) {
  if (value === null) return <span className="ta-r dim">{DASH}</span>;
  return <span className={`ta-r ${value >= 0 ? "is-pos" : "is-neg"}`}>{pct(value)}</span>;
}

function Porcentaje({ value, fuerte }: { value: number | null; fuerte?: boolean }) {
  if (value === null) return <span className="ta-r dim">{DASH}</span>;
  return (
    <span className={`ta-r ${fuerte ? "strong" : ""}`}>{pctPlain(value).replace(" %", "")}</span>
  );
}

function ManoDeObra({ value }: { value: number | null }) {
  if (value === null) return <span className="ta-r dim">{DASH}</span>;
  const cumple = value <= 0 || roundsToZero(value);
  return <span className={`ta-r ${cumple ? "is-pos" : "light-warn"}`}>{signedDec(value)}</span>;
}
