/**
 * Abrir el calendario nativo de un `input[type=date]`.
 *
 * En el móvil basta con tocar el campo, pero en el escritorio el navegador solo
 * lo enfoca: el calendario se abre con su icono, que aquí está oculto porque el
 * campo se superpone invisible sobre la fecha. `showPicker()` lo abre a mano.
 *
 * Si el navegador no lo soporta o se niega a abrirlo, el campo sigue siendo un
 * campo de fecha normal (se puede teclear): se devuelve `false` y no se rompe
 * nada. No hay dato que falsear aquí — es navegación, no cifras.
 */

type DatePickerInput = { showPicker?: () => void };

export function openDatePicker(input: DatePickerInput | null): boolean {
  if (input === null || typeof input.showPicker !== "function") return false;
  try {
    input.showPicker();
    return true;
  } catch {
    // El navegador exige un gesto del usuario, o el calendario ya está abierto
    // (el móvil lo abre él solo al tocar). Ninguno de los dos casos es un fallo.
    return false;
  }
}
