import type { HourRow } from "../lib/types";

/**
 * Barras de previsto contra real, hora a hora.
 *
 * Gris el previsto, verde o rojo el real según supere o no la previsión. Las
 * horas sin venta todavía se quedan sin barra de color, no con una barra a
 * cero: no es lo mismo "no ha vendido" que "aún no ha pasado".
 *
 * `currentHour` llega de fuera y es nulo en un día cerrado: marcar ahí la hora
 * del reloj señalaría como "en curso" una hora de un día que terminó hace meses.
 */
export function HourlyChart({
  rows,
  currentHour,
}: {
  rows: HourRow[];
  currentHour: number | null;
}) {
  const maximo = Math.max(
    1,
    ...rows.map((r) => Math.max(r.proj_sales ?? 0, r.net ?? 0)),
  );

  return (
    <div className="chart">
      <div className="chart__header">
        <span className="chart__title">VENTA POR HORA</span>
        <span className="chart__legend">
          <span className="chart__key chart__key--proj" /> PROY
          <span className="chart__key chart__key--real" /> REAL
        </span>
      </div>

      <div className="chart__bars">
        {rows.map((r) => {
          const alturaProy = `${Math.max(2, ((r.proj_sales ?? 0) / maximo) * 100).toFixed(1)}%`;
          const alturaReal =
            r.net === null ? "0%" : `${Math.max(2, (r.net / maximo) * 100).toFixed(1)}%`;
          const porDebajo = r.net !== null && r.proj_sales !== null && r.net < r.proj_sales;

          return (
            <div key={r.hour} className="chart__slot" title={`${r.hour}:00`}>
              <div className="chart__bar chart__bar--proj" style={{ height: alturaProy }} />
              <div
                className={`chart__bar ${porDebajo ? "chart__bar--neg" : "chart__bar--pos"}`}
                style={{ height: alturaReal }}
              />
              {r.hour === currentHour && <span className="chart__now" />}
            </div>
          );
        })}
      </div>

      <div className="chart__axis">
        {rows.length > 0 &&
          [rows[0], rows[Math.floor(rows.length / 2)], rows[rows.length - 1]].map((r, i) =>
            r ? <span key={i}>{String(r.hour).padStart(2, "0")}</span> : null,
          )}
      </div>
    </div>
  );
}
