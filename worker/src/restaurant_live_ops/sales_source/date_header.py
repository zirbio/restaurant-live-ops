"""Lectura y verificación de la fecha que muestra la fuente de ventas.

La fuente puede abrir una fecha diferente de la solicitada. Ninguna captura se
acepta sin comparar antes el encabezado con el día objetivo.
"""

from __future__ import annotations

import re
from datetime import date

_MONTHS_EN = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "sept": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}
_DATE_LABEL_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3,4})")


class StaleDateError(RuntimeError):
    """La fuente no se pudo posicionar en el día correcto."""


class UnverifiableDateError(StaleDateError):
    """El día pedido está tan atrás que su encabezado no se puede verificar."""


# El encabezado de la fuente no lleva año, así que el par (día, mes) solo
# identifica un día sin ambigüedad dentro de una ventana de menos de un año.
# Más atrás, el encabezado de hoy coincidiría con el día pedido y se aceptaría
# como verificada una captura del día equivocado si coincide el día y mes de
# otro año. Fuera de la ventana inequívoca se rechaza.
MAX_VERIFIABLE_DAYS = 364


def assert_verifiable(target: date, today: date) -> None:
    """Falla si el encabezado no puede verificar ``target`` sin ambigüedad."""
    dias = (today - target).days
    if dias < 0:
        raise UnverifiableDateError(
            f"{target.isoformat()} está en el futuro: no hay nada que capturar"
        )
    if dias > MAX_VERIFIABLE_DAYS:
        raise UnverifiableDateError("la fecha queda fuera de la ventana verificable")


# JS que lee el encabezado dentro de la página.
DATE_HEADER_JS = """
() => {
  const els = Array.from(document.querySelectorAll('div,span,label'));
  for (const e of els) {
    const t = (e.textContent || '').trim();
    if (t.length <= 80
        && /\\b\\d{1,2}\\s+[A-Za-z]{3,4}\\b/.test(t)
        && /(Yesterday|Today|day|Mon|Tue|Wed|Thu|Fri|Sat|Sun)/i.test(t)) {
      return t;
    }
  }
  return '';
}
"""


def parse_date_label(label: str) -> tuple[int, int] | None:
    """Extrae ``(día, mes)`` del encabezado.

    Recorre las coincidencias del final hacia atrás para que un prefijo como
    "2 days ago" no gane a la fecha real que viene después.
    """
    for day_s, mon_s in reversed(_DATE_LABEL_RE.findall(label or "")):
        month = _MONTHS_EN.get(mon_s.lower())
        if month is not None:
            return int(day_s), month
    return None


def matches_date(label: str, target: date) -> bool:
    """¿El encabezado muestra exactamente ``target``? Un encabezado ilegible es un no.

    El encabezado no lleva año, así que se comparan día y mes. Para
    el ciclo del día en curso el objetivo es hoy; para la recuperación de
    huecos, el día que se ha pedido.
    """
    shown = parse_date_label(label)
    return shown is not None and shown == (target.day, target.month)
