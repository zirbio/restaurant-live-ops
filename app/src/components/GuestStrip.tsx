import { DASH, num, pct, signedNum } from "../lib/format";

/**
 * Los clientes del mes: cuántos, frente al objetivo y frente al año pasado.
 *
 * Va en el titular y NO en una tabla aparte porque responde a lo que se está
 * mirando: en una pestaña son los de ese restaurante y en TODOS se agregan
 * los tres. No se muestra una segunda rejilla que mezcle locales ajenos a la
 * selección activa.
 *
 * No lleva celda de España: el dato nacional que publica la fuente de ventas es un único
 * porcentaje de VENTA, sin clientes. Por eso son tres celdas y no cuatro —aquí
 * no falta nada, sencillamente no existe—.
 */
export function GuestStrip({
  count,
  targetDiff,
  yoy,
}: {
  count: number | null;
  targetDiff: number | null;
  yoy: number | null;
}) {
  return (
    // Comparte la chapa de `yoyStrip`: es la misma rejilla de tres celdas y
    // duplicarla en CSS solo daría dos sitios donde tocar el mismo borde.
    <div className="yoyStrip">
      <div className="yoyStrip__cell">
        <span className="yoyStrip__label">CLIENTES</span>
        {/* El recuento va en tinta neutra, como el de España: es la cifra, no
            un veredicto. El color lo llevan las dos celdas que comparan. */}
        <span className={`yoyStrip__value ${count === null ? "dim" : ""}`}>{num(count)}</span>
      </div>
      <div className="yoyStrip__cell">
        <span className="yoyStrip__label">Δ OBJ</span>
        <span className={`yoyStrip__value ${signo(targetDiff)}`}>
          {targetDiff === null ? DASH : signedNum(targetDiff)}
        </span>
      </div>
      <div className="yoyStrip__cell">
        <span className="yoyStrip__label">YoY</span>
        <span className={`yoyStrip__value ${signo(yoy)}`}>{pct(yoy)}</span>
      </div>
    </div>
  );
}

function signo(n: number | null): string {
  if (n === null) return "dim";
  return n >= 0 ? "is-pos" : "is-neg";
}
