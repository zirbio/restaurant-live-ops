import { DASH, pct } from "../lib/format";

/**
 * Comparable interanual propio, el de España y su diferencial.
 *
 * Las tres celdas responden a una sola pregunta: si el mes ha ido mal, ¿ha ido
 * mal el restaurante o ha ido mal el país? Sin el dato nacional esa pregunta no
 * se puede contestar, y entonces salen dos rayas: media España inventada no
 * hay ninguna.
 */
export function YoyStrip({
  own,
  national,
  difference,
}: {
  own: number | null;
  national: number | null;
  difference: number | null;
}) {
  return (
    <div className="yoyStrip">
      <div className="yoyStrip__cell">
        <span className="yoyStrip__label">YoY COMPARABLE</span>
        <span className={`yoyStrip__value ${signo(own)}`}>{pct(own)}</span>
      </div>
      <div className="yoyStrip__cell">
        <span className="yoyStrip__label">ESPAÑA</span>
        {/* El nacional va en gris: es contexto, no un resultado propio. */}
        <span className={`yoyStrip__value ${national === null ? "dim" : ""}`}>
          {national === null ? DASH : pct(national)}
        </span>
      </div>
      <div className="yoyStrip__cell">
        <span className="yoyStrip__label">DIFERENCIAL</span>
        <span className={`yoyStrip__value ${signo(difference)}`}>
          {difference === null ? DASH : `${pct(difference).replace(" %", "")} pp`}
        </span>
      </div>
    </div>
  );
}

function signo(n: number | null): string {
  if (n === null) return "dim";
  return n >= 0 ? "is-pos" : "is-neg";
}
