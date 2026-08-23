import { addMonths, monthLabel, type MonthKey } from "../lib/month";

/**
 * Navegador de meses.
 *
 * Solo flechas: un calendario de meses sería un control nuevo para once
 * destinos, y las flechas ya llevan a todos. Los extremos se bloquean —ni
 * meses que aún no han cerrado ningún día, ni anteriores al primero con
 * datos—, igual que en el selector de día.
 */
export function MonthNav({
  month,
  latest,
  earliest,
  onChange,
}: {
  month: MonthKey;
  latest: MonthKey;
  earliest: MonthKey;
  onChange: (key: MonthKey) => void;
}) {
  const atras = month > earliest;
  const adelante = month < latest;

  return (
    <div className="monthNav">
      <button
        type="button"
        className="monthNav__arrow"
        aria-label="Mes anterior"
        disabled={!atras}
        onClick={() => onChange(addMonths(month, -1))}
      >
        ‹
      </button>
      <span className="monthNav__label">{monthLabel(month)}</span>
      <button
        type="button"
        className="monthNav__arrow"
        aria-label="Mes siguiente"
        disabled={!adelante}
        onClick={() => onChange(addMonths(month, 1))}
      >
        ›
      </button>
    </div>
  );
}
