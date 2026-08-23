import { daysInMonth, monthLabel, type MonthKey } from "../lib/month";

/** Estado y cobertura temporal del mes; la fuente de MO se declara en su tabla. */
export function MonthStatus({
  month,
  windowEnd,
}: {
  month: MonthKey;
  windowEnd: string | null;
}) {
  const total = daysInMonth(month);
  const cerrados = windowEnd === null ? 0 : Number(windowEnd.slice(8));
  const cerrado = cerrados === total;

  return (
    <div className="freshness">
      <span className="freshness__dot" />
      <span>
        {cerrado
          ? `Mes cerrado · ${total} días completos`
          : `${monthLabel(month)} en curso · ${cerrados} de ${total} días cerrados`}{" "}
        · cobertura hasta el último día cerrado
      </span>
    </div>
  );
}
