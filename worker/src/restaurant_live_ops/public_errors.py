"""Mensajes externos estables que nunca incorporan payloads ni excepciones."""

SALES_PUBLIC_ERROR = "captura de ventas no disponible"
WORKFORCE_PUBLIC_ERROR = "previsión no disponible"
STAFFING_PUBLIC_ERROR = "personal no disponible"
BACKFILL_PUBLIC_ERROR = "recaptura de ventas no disponible"
WORKFORCE_SNAPSHOT_ERROR = "snapshot de personal incompleto"


def public_error_for_source(source: str) -> str:
    normalized = source.casefold()
    if "backfill" in normalized or "recaptura" in normalized:
        return BACKFILL_PUBLIC_ERROR
    if "staff" in normalized or normalized == "personal":
        return STAFFING_PUBLIC_ERROR
    if "workforce" in normalized or "personal" in normalized:
        return WORKFORCE_PUBLIC_ERROR
    return SALES_PUBLIC_ERROR
