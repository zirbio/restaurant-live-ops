import { openDatePicker } from "../lib/datePicker";
import { canGoBack, canGoForward } from "../lib/salesDate";
import { addDaysMadrid, longDateFromIso } from "../lib/tz";

/**
 * Navegador de días.
 *
 * Flechas para moverse de uno en uno y, pinchando la fecha, el calendario que el
 * móvil ya sabe usar (`input[type=date]`), en vez de uno propio. En el
 * escritorio hay que abrirlo a mano: ver `openDatePicker`. Los extremos se
 * bloquean: ni futuro, ni antes del primer día con datos.
 */
export function DayNav({
  salesDate,
  today,
  earliest,
  onChange,
}: {
  salesDate: string;
  today: string;
  earliest: string;
  onChange: (iso: string) => void;
}) {
  const atras = canGoBack(salesDate, earliest);
  const adelante = canGoForward(salesDate, today);

  return (
    <div className="dayNav">
      <button
        type="button"
        className="dayNav__arrow"
        aria-label="Día anterior"
        disabled={!atras}
        onClick={() => onChange(addDaysMadrid(salesDate, -1))}
      >
        ‹
      </button>

      <label className="dayNav__date">
        <span className="dayNav__label">{longDateFromIso(salesDate)}</span>
        <input
          type="date"
          className="dayNav__input"
          aria-label="Elegir día"
          value={salesDate}
          min={earliest}
          max={today}
          // El clic se atiende aquí, no en la etiqueta: el que cae en el margen
          // táctil de 44 px llega igual (la etiqueta lo reenvía al campo), y así
          // no se abre el calendario dos veces por un solo toque.
          onClick={(e) => openDatePicker(e.currentTarget)}
          onChange={(e) => {
            // El calendario nativo no deja salirse de min/max, pero el valor
            // puede llegar vacío si se borra: entonces no se cambia de día.
            if (e.target.value) onChange(e.target.value);
          }}
        />
      </label>

      <button
        type="button"
        className="dayNav__arrow"
        aria-label="Día siguiente"
        disabled={!adelante}
        onClick={() => onChange(addDaysMadrid(salesDate, 1))}
      >
        ›
      </button>

      {salesDate !== today && (
        <button type="button" className="dayNav__today" onClick={() => onChange(today)}>
          HOY
        </button>
      )}
    </div>
  );
}
