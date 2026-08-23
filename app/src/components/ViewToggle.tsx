/**
 * Conmutador entre la vista del día y la del mes.
 *
 * Va pegado al borde inferior, que es donde llega el pulgar sin recolocar el
 * teléfono: es el control que más se usa y el único que cambia de pantalla
 * entera.
 */

export type View = "day" | "month";

export function ViewToggle({ view, onChange }: { view: View; onChange: (v: View) => void }) {
  return (
    <div className="viewToggle">
      <div className="viewToggle__track" role="tablist" aria-label="Día o mes">
        <button
          type="button"
          role="tab"
          aria-selected={view === "day"}
          className={`viewToggle__option ${view === "day" ? "is-active" : ""}`}
          onClick={() => onChange("day")}
        >
          DÍA
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={view === "month"}
          className={`viewToggle__option ${view === "month" ? "is-active" : ""}`}
          onClick={() => onChange("month")}
        >
          MES
        </button>
      </div>
    </div>
  );
}
