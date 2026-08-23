import { eur, num, pct, secs, signedEur, signedNum, staffing } from "../lib/format";
import { aggregate, deviation, liveStaffing, serviceLight, ticketMedio } from "../lib/metrics";
import { serviceRibbons } from "../lib/serviceRibbons";
import type { HourRow, Objectives, Restaurant, ServiceTimes } from "../lib/types";

/**
 * Tarjeta de un restaurante en la vista de conjunto: cómo va, en cuatro cifras
 * y tres tiempos, más la miniatura de la curva del día.
 *
 * Bajo la curva van las cintas de tiempos, una por métrica y una celda por
 * hora, en el mismo orden que las barras de venta: el mismo tramo del día se
 * lee arriba en euros y abajo en servicio, así que una tarde floja con la
 * cocina en rojo se ve sin entrar al local. El cálculo, en `serviceRibbons`.
 */
export function LocalCard({
  restaurant,
  rows,
  objectives,
  times,
  currentHour,
  yoy,
  vsEs,
  onSelect,
}: {
  restaurant: Restaurant;
  rows: HourRow[];
  objectives: Objectives | null;
  /** Los del día que da la fuente de ventas. Nulo si de este día no hay fila de totales. */
  times: ServiceTimes | null;
  /** Nulo en un día cerrado: allí entra el día entero, sin excluir nada. */
  currentHour: number | null;
  /** Interanual del día. Nulo en el día vivo: la comparación sería parcial. */
  yoy?: number | null;
  /** Diferencia en puntos contra España, cuando hay dato nacional. */
  vsEs?: number | null;
  onSelect: () => void;
}) {
  // Igual que el titular: la hora en curso va a medias y no entra en la
  // comparación, aunque sí se ve en la miniatura de la curva. En un día
  // cerrado no hay hora a medias, y descontar una restaría venta real.
  const t = aggregate(rows, currentHour === null ? {} : { excludeHour: currentHour });
  const desv = deviation(t.net, t.projToNow);
  const dGc = t.gc !== null && t.projGcToNow !== null ? t.gc - Math.round(t.projGcToNow) : null;
  const positivo = (desv.euros ?? 0) >= 0;
  const oepe = restaurant.has_drive_through ? (times?.oepe ?? null) : null;

  const maximo = Math.max(1, ...rows.map((r) => Math.max(r.proj_sales ?? 0, r.net ?? 0)));
  const cintas = serviceRibbons(rows, objectives, restaurant.has_drive_through);
  // El personal va de la hora en curso, no del acumulado: la pregunta es
  // cuánta gente hay dentro ahora, no cuánta pasó en todo el día.
  const personal = liveStaffing(rows, currentHour);

  return (
    <button
      type="button"
      className={`card ${positivo ? "card--pos" : "card--neg"}`}
      onClick={onSelect}
    >
      <div className="card__top">
        <div className="card__name">
          <span className="card__title">Restaurante {restaurant.name}</span>
          <span className="card__meta">
            TICKET {eur(ticketMedio(t.net, t.gc))} · GC {num(t.gc)}
            {yoy !== null && yoy !== undefined && (
              <>
                {" · "}
                {/* El "YoY" y su cifra no se separan: sueltos, el porcentaje
                    de la línea de abajo parece pertenecer a los guest counts. */}
                <span className={`nowrap strong ${yoy >= 0 ? "is-pos" : "is-neg"}`}>
                  YoY {pct(yoy)}
                  {vsEs !== null && vsEs !== undefined && ` (${pct(vsEs).replace(" %", "")} pp)`}
                </span>
              </>
            )}
          </span>
        </div>
        <span className={`card__delta ${positivo ? "is-pos" : "is-neg"}`}>
          {signedEur(desv.euros, { decimales: 0 })}
        </span>
      </div>

      <div className="card__grid">
        <Dato etiqueta="REAL" valor={eur(t.net, { decimales: 0 })} fuerte />
        <Dato etiqueta="PROY" valor={eur(t.projToNow, { decimales: 0 })} />
        <Dato etiqueta="Δ GC" valor={signedNum(dGc)} clase={dGc === null ? "dim" : positivoClase(dGc)} />
        <Dato
          etiqueta="PERS F/A"
          valor={staffing(
            personal?.clocked ?? null,
            personal?.assigned ?? null,
            personal?.clipped ?? null,
          )}
          clase={personal === null ? "dim" : ""}
        />
      </div>

      <div className={`card__curve ${cintas.length > 0 ? "card__curve--withRibbons" : ""}`}>
        <div className="card__spark">
          {rows.map((r) => {
            const valor = r.net ?? r.proj_sales ?? 0;
            const altura = `${Math.max(2, (valor / maximo) * 100).toFixed(1)}%`;
            const clase =
              r.net === null
                ? "spark--none"
                : r.proj_sales !== null && r.net < r.proj_sales
                  ? "spark--neg"
                  : "spark--pos";
            return <div key={r.hour} className={`spark ${clase}`} style={{ height: altura }} />;
          })}
        </div>

        {cintas.map((cinta) => (
          <div key={cinta.metric} className="ribbon">
            <span className="ribbon__label">{cinta.metric.toUpperCase()}</span>
            <div className="ribbon__cells">
              {cinta.cells.map((celda) => (
                <div
                  key={celda.hour}
                  className={`ribbon__cell ribbon__cell--${celda.light}`}
                />
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="card__times">
        <Tiempo etiqueta="KVS" valor={times?.kvs ?? null} objetivo={objectives?.kvs} />
        <Tiempo etiqueta="R2P" valor={times?.r2p ?? null} objetivo={objectives?.r2p} />
        <Tiempo etiqueta="OEPE" valor={oepe} objetivo={objectives?.oepe} />
      </div>
    </button>
  );
}

function positivoClase(n: number): string {
  return n >= 0 ? "is-pos" : "is-neg";
}

function Dato({
  etiqueta,
  valor,
  fuerte,
  clase,
}: {
  etiqueta: string;
  valor: string;
  fuerte?: boolean;
  clase?: string;
}) {
  return (
    <div className="card__cell">
      <span className="card__cellLabel">{etiqueta}</span>
      <span className={`card__cellValue ${fuerte ? "strong" : ""} ${clase ?? ""}`}>{valor}</span>
    </div>
  );
}

function Tiempo({
  etiqueta,
  valor,
  objetivo,
}: {
  etiqueta: string;
  valor: number | null;
  objetivo: number | null | undefined;
}) {
  const l = serviceLight(valor, objetivo);
  return (
    <div className={`time time--${l}`}>
      <span className="time__label">{etiqueta}</span>
      <span className="time__value">{secs(valor)}</span>
    </div>
  );
}
