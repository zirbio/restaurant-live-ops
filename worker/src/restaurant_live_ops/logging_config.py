"""Configuración común de logs del worker."""

from __future__ import annotations

import logging


def configure_logging() -> None:
    """Activa los logs propios sin exponer peticiones HTTP completas."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
