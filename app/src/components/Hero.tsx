import { eur, pct, signedEur } from "../lib/format";
import { deviation } from "../lib/metrics";
import type { DayTotals, HourRow } from "../lib/types";
import { YoyStrip } from "./YoyStrip";

/**
 * Cifra grande: venta acumulada, desviación y barra de progreso del día.
 *
 * Todo se mide contra la previsión de personal: la barra llega hasta la previsión del día completo y la
 * marca negra es la previsión acumulada hasta la hora en curso. Una dice a
 * dónde toca llegar al cierre; la otra, por dónde tocaría ir a estas horas.
 *
 * El número grande se cierra en la última hora completa. La hora en curso se
 * muestra aparte para no contaminar la comparación con una fracción de hora.
 */
export function Hero({
  label,
  totals,
  currentHour,
  reference,
  yoy,
  national,
  difference,
  yoyNote,
}: {
  label: string;
  totals: DayTotals;
  currentHour?: { hour: number; row: HourRow } | null;
  /**
   * Previsión del día completo, ya restringida a los locales que cuentan.
   *
   * Llega calculada de fuera y no se toma de `totals` porque en un día cerrado
   * un restaurante sin captura de la fuente de ventas tiene previsión pero no venta, y contarla
   * pintaría la barra al 77 % de un día que fue normal. Nula si no se puede
   * componer; entonces se cae a la del conjunto.
   */
  reference?: number | null;
  yoy?: number | null;
  national?: number | null;
  difference?: number | null;
  /** Por qué el interanual sale como sale, o por qué no sale. */
  yoyNote?: string | null;
}) {
  const desv = deviation(totals.net, totals.projToNow);
  const positivo = (desv.euros ?? 0) >= 0;

  const referencia = reference ?? totals.projDay;

  const anchoBarra =
    totals.net !== null && referencia
      ? `${Math.min(100, (totals.net / referencia) * 100).toFixed(1)}%`
      : "0%";
  const anchoMarca =
    totals.projToNow !== null && referencia
      ? `${Math.min(100, (totals.projToNow / referencia) * 100).toFixed(1)}%`
      : "0%";

  return (
    <section className="hero">
      <div className="hero__row">
        <div className="hero__main">
          <div className="hero__label">{label}</div>
          <div className="hero__value">{eur(totals.net)}</div>
        </div>
        <div className="hero__delta">
          <div className={`hero__deltaValue ${positivo ? "is-pos" : "is-neg"}`}>
            {signedEur(desv.euros)}
          </div>
          <div className="hero__deltaPct">{pct(desv.pct)} vs proy.</div>
        </div>
      </div>

      <div className="hero__bar">
        <div className="hero__barTrack">
          <div className="hero__barFill" style={{ width: anchoBarra }} />
          <div className="hero__barMark" style={{ left: anchoMarca }} />
        </div>
        <div className="hero__barLabels">
          <span>
            PREVISIÓN DÍA {eur(referencia, { decimales: 0 })}
          </span>
          <span>PROY. HASTA CIERRE DE HORA {eur(totals.projToNow, { decimales: 0 })}</span>
        </div>
      </div>

      {currentHour && (
        <div className="hero__live">
          <span className="hero__liveLabel">
            HORA EN CURSO {String(currentHour.hour).padStart(2, "0")}:00 · PARCIAL
          </span>
          <span className="hero__liveValue">
            {eur(currentHour.row.net, { decimales: 0 })} de{" "}
            {eur(currentHour.row.proj_sales, { decimales: 0 })} previstos
          </span>
        </div>
      )}

      {yoy !== undefined && (
        <>
          <YoyStrip own={yoy} national={national ?? null} difference={difference ?? null} />
          {yoyNote && <p className="yoyStrip__note">{yoyNote}</p>}
        </>
      )}
    </section>
  );
}
