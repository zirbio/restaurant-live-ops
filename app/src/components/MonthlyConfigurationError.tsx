export function MonthlyConfigurationError() {
  return (
    <aside className="configurationWarning" role="alert">
      <p>Vista mensual no configurada</p>
      <p className="configurationWarning__detail">
        Define VITE_MONTHLY_SOURCE=supabase o desactiva VITE_MONTHLY_ENABLED.
      </p>
    </aside>
  );
}
