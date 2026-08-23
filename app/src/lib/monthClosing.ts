/** Describe con precisión de qué fuente sale el cierre de mano de obra. */
export function closedLaborNote({
  actual,
  estimated,
  unavailable,
  restaurants,
}: {
  actual: number;
  estimated: number;
  unavailable: number;
  restaurants: number;
}): string {
  if (actual === restaurants) return "P&L cerrado de la fuente mensual";
  const partes: string[] = [];
  if (actual > 0) partes.push(`P&L real en ${actual} de ${restaurants} locales`);
  if (estimated > 0) {
    partes.push(
      `${estimated} ${estimated === 1 ? "local estimado" : "locales estimados"} por horas fichadas`,
    );
  }
  if (unavailable > 0) {
    partes.push(
      `⚠ ${unavailable} ${unavailable === 1 ? "local sin P&L ni estimación completa" : "locales sin P&L ni estimación completa"}`,
    );
  }
  return partes.join(" · ");
}
