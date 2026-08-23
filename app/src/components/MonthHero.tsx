import { eur, pct, pctPlain, signedEur } from "../lib/format";
import { deviation } from "../lib/metrics";
import { GuestStrip } from "./GuestStrip";
import { YoyStrip } from "./YoyStrip";

/**
 * Cifra grande del mes: venta, desviación frente al objetivo y comparables.
 *
 * El objetivo es la previsión de personal, la misma referencia que en la
 * pantalla diaria.
 *
 * En un mes en curso, el objetivo que se enseña es el de los mismos días que
 * llevan venta: comparar lo acumulado a día 5 contra el objetivo de 31 daría
 * un desplome que no existe.
 */
export function MonthHero({
  label,
  net,
  target,
  yoy,
  national,
  difference,
  targetLabel,
  guests,
}: {
  label: string;
  net: number | null;
  target: number | null;
  yoy: number | null;
  national: number | null;
  difference: number | null;
  /** `OBJETIVO MES` en un mes cerrado; en uno vivo dice hasta qué día cuenta. */
  targetLabel: string;
  /** Los clientes del ámbito seleccionado. */
  guests: { count: number | null; targetDiff: number | null; yoy: number | null };
}) {
  const desv = deviation(net, target);
  const positivo = (desv.euros ?? 0) >= 0;

  const cumplimiento = net !== null && target ? (net / target) * 100 : null;
  const ancho = cumplimiento === null ? "0%" : `${Math.min(100, cumplimiento).toFixed(1)}%`;

  return (
    <section className="hero">
      <div className="hero__row">
        <div className="hero__main">
          <div className="hero__label">{label}</div>
          <div className="hero__value">{eur(net, { decimales: 0 })}</div>
        </div>
        <div className="hero__delta">
          <div className={`hero__deltaValue ${positivo ? "is-pos" : "is-neg"}`}>
            {signedEur(desv.euros, { decimales: 0 })}
          </div>
          <div className="hero__deltaPct">{pct(desv.pct)} vs obj.</div>
        </div>
      </div>

      <div className="hero__bar">
        <div className="hero__barTrack">
          <div className="hero__barFill" style={{ width: ancho }} />
          {/* La marca es el 100 % del objetivo: la meta, no una previsión. */}
          <div className="hero__barMark" style={{ left: "100%" }} />
        </div>
        <div className="hero__barLabels">
          <span>
            {targetLabel} {eur(target, { decimales: 0 })}
          </span>
          <span>REAL {pctPlain(cumplimiento)}</span>
        </div>
      </div>

      <YoyStrip own={yoy} national={national} difference={difference} />
      <GuestStrip count={guests.count} targetDiff={guests.targetDiff} yoy={guests.yoy} />
    </section>
  );
}
