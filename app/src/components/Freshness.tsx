import { freshnessLabel, longDateFromIso } from "../lib/tz";
import { provenanceLabel, provenanceTimestampLead } from "../lib/provenance";
import type {
  DayProvenance,
  IngestRun,
  Restaurant,
  DailyStatus,
} from "../lib/types";
import {
  buildIngestRunFreshness,
  rebucketedNotes,
  type RestaurantFreshnessIssue,
} from "../lib/sourceFreshness";

const SPANISH_LIST = new Intl.ListFormat("es", { type: "conjunction" });

/**
 * Marca de frescura y aviso de fallos.
 *
 * Nada de esto es tiempo real: la fuente de ventas se refresca cada 10-15 minutos. Aquí se
 * dice exactamente cuándo se capturó el dato y, si el último ciclo falló, se
 * avisa con su motivo y con la hora del último dato bueno. Un dato viejo
 * presentado como fresco es peor que no tener dato.
 */
export function Freshness({
  runs,
  restaurants,
  dailyStatusByRestaurant,
  sinPrevision,
  closed,
  provenance,
}: {
  runs: IngestRun[];
  restaurants: Restaurant[];
  dailyStatusByRestaurant: Map<string, DailyStatus>;
  /** No hay ni una hora de previsión para el día: la comparación no es posible. */
  sinPrevision?: boolean;
  /** Se está mirando un día ya cerrado, no el día en curso. */
  closed?: boolean;
  /** De dónde salió ese día, si consta. */
  provenance?: DayProvenance | null;
}) {
  const qualityNotes = rebucketedNotes(restaurants, dailyStatusByRestaurant);

  // Un día cerrado no tiene frescura que medir: lo que importa es cuándo se
  // capturó y de dónde salió. "Actualizado hace 4 min" hablaría del ciclo de
  // HOY mientras en pantalla hay otro día, así que aquí no se enseña nunca.
  // Si la procedencia no consta, se dice: es preferible al dato prestado.
  if (closed) {
    return (
      <div className="freshness">
        <span className="freshness__dot" />
        <span>
          Día cerrado
          {provenance ? (
            <>
              {/* El corte a 10 caracteres da el día en UTC. Aquí solo se
                  comunica cuándo se capturó, aproximadamente, no una fecha de
                  negocio: la hora de diferencia en la madrugada no cambia lo
                  que el usuario entiende. */}
              {` · ${provenanceTimestampLead(provenance.source)} `}
              {longDateFromIso(provenance.capturedAt.slice(0, 10))}
              <span className="freshness__reason"> · {provenanceLabel(provenance.source)}</span>
              {provenance.pendingRestaurantNames.length > 0 && (
                <span className="freshness__reason">
                  {" "}· cierre POS pendiente en{" "}
                  {SPANISH_LIST.format(provenance.pendingRestaurantNames)}
                  : venta provisional en esos locales
                </span>
              )}
            </>
          ) : (
            <span className="freshness__reason"> · procedencia no registrada</span>
          )}
          {sinPrevision && (
            <span className="freshness__reason"> · sin previsión: no se puede comparar</span>
          )}
          {qualityNotes.map((note) => (
            <span key={note} className="freshness__reason"> · {note}</span>
          ))}
        </span>
      </div>
    );
  }

  const restaurantModel = buildIngestRunFreshness(
    restaurants,
    runs,
    dailyStatusByRestaurant,
  );

  return (
    <div className={`freshness ${restaurantModel.bad ? "freshness--bad" : ""}`}>
      <span className="freshness__dot" />
      <span>
        {restaurantModel.issues.length > 0 ? (
          <>
            {restaurantModel.issues.map(issueLabel).join(" · ")}. Último dato bueno conjunto{" "}
            {freshnessLabel(restaurantModel.updatedAt)}.
          </>
        ) : (
          <>
            Actualizado {freshnessLabel(restaurantModel.updatedAt)} · {restaurants.length}{" "}
            {restaurants.length === 1 ? "local" : "locales"}
          </>
        )}
        {restaurantModel.capturingRestaurantNames.length > 0 && (
          <span className="freshness__reason">
            {" "}· capturando {SPANISH_LIST.format(restaurantModel.capturingRestaurantNames)}…
          </span>
        )}
        {restaurantModel.notes.map((note) => (
          <span key={note} className="freshness__reason"> · {note}</span>
        ))}
        {sinPrevision && (
          <span className="freshness__reason">
            {" "}· sin previsión de hoy: no se puede comparar
          </span>
        )}
      </span>
    </div>
  );
}

function issueLabel(issue: RestaurantFreshnessIssue): string {
  const state = issue.status === "failed" ? "captura fallida" : "captura no registrada";
  return `${issue.restaurantName}: ${state} (${resumir(issue.reason)})`;
}

/** Los errores del worker pueden ser largos: se muestra la primera línea. */
function resumir(error: string): string {
  const primera = error.split("\n")[0] ?? error;
  return primera.length > 120 ? `${primera.slice(0, 117)}…` : primera;
}
