"""Configuración del worker, leída de variables de entorno.

Las credenciales nunca viven en el repositorio: en local vienen de un fichero
``.env.local`` que no se commitea, y en producción de las variables de entorno
del servicio.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import parse_qsl, urlsplit, urlunsplit


def _required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"falta la variable de entorno {name}")
    return value


def _source_url(name: str) -> str:
    raw = _required(name).rstrip("/")
    try:
        parsed = urlsplit(raw)
        _ = parsed.port
    except ValueError:
        raise RuntimeError(f"{name} no es una URL de fuente segura") from None
    hostname = parsed.hostname.casefold() if parsed.hostname else None
    allow_local_http = os.getenv("ALLOW_INSECURE_LOCAL_SOURCE_URLS_FOR_TESTS") == "true"
    local_http = (
        parsed.scheme == "http"
        and hostname in {"127.0.0.1", "::1", "localhost"}
        and allow_local_http
    )
    if (
        parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or (parsed.scheme != "https" and not local_http)
    ):
        raise RuntimeError(f"{name} no es una URL de fuente segura")
    return raw


def _hourly_endpoint(base_url: str) -> tuple[str, str, str]:
    path = _required("SALES_SOURCE_HOURLY_PATH")
    query = _required("SALES_SOURCE_HOURLY_QUERY")
    if not path.startswith("/") or "?" in path or "#" in path or path.startswith("//"):
        raise RuntimeError("SALES_SOURCE_HOURLY_PATH no es una ruta exacta válida")
    pairs = parse_qsl(query, keep_blank_values=True)
    if (
        not pairs
        or any(not key for key, _value in pairs)
        or len({key for key, _ in pairs}) != len(pairs)
    ):
        raise RuntimeError("SALES_SOURCE_HOURLY_QUERY no es una query exacta válida")
    parsed_base = urlsplit(base_url)
    endpoint = urlunsplit((parsed_base.scheme, parsed_base.netloc, path, query, ""))
    return path, query, endpoint


@dataclass(frozen=True)
class SalesSourceSettings:
    base_url: str
    username: str
    password: str
    hourly_path: str | None = None
    hourly_query: str | None = None
    view_label: str | None = None

    @property
    def hourly_endpoint_url(self) -> str | None:
        if self.hourly_path is None or self.hourly_query is None:
            return None
        parsed_base = urlsplit(self.base_url)
        return urlunsplit(
            (parsed_base.scheme, parsed_base.netloc, self.hourly_path, self.hourly_query, "")
        )

    @classmethod
    def from_env(cls) -> SalesSourceSettings:
        base_url = _source_url("SALES_SOURCE_BASE_URL")
        hourly_path, hourly_query, _endpoint = _hourly_endpoint(base_url)
        return cls(
            base_url=base_url,
            username=_required("SALES_SOURCE_USERNAME"),
            password=_required("SALES_SOURCE_PASSWORD"),
            hourly_path=hourly_path,
            hourly_query=hourly_query,
            view_label=_required("SALES_SOURCE_VIEW_LABEL"),
        )


@dataclass(frozen=True)
class WorkforceSourceSettings:
    base_url: str
    business_id: str
    username: str
    password: str
    api_key: str | None

    @classmethod
    def from_env(cls) -> WorkforceSourceSettings:
        return cls(
            base_url=_source_url("WORKFORCE_SOURCE_BASE_URL"),
            business_id=_required("WORKFORCE_SOURCE_BUSINESS_ID"),
            username=_required("WORKFORCE_SOURCE_USERNAME"),
            password=_required("WORKFORCE_SOURCE_PASSWORD"),
            api_key=os.getenv("WORKFORCE_SOURCE_API_KEY"),
        )


@dataclass(frozen=True)
class StaffingSettings:
    """Ajustes del recuento de personal.

    ``excluded_people`` son nombres completos que no cuentan como dotación de
    turno aunque su categoría en la fuente diga que sí. Van en la
    variable de entorno ``STAFFING_EXCLUDED_PEOPLE``, separados por ``;``, y
    nunca en el repositorio: son nombres de personas.

    Vacía por defecto. Sin nadie configurado el recuento sale igual, solo que
    sin descontar a quien no se puede distinguir por su categoría.
    """

    excluded_people: tuple[str, ...]

    @classmethod
    def from_env(cls) -> StaffingSettings:
        crudo = os.getenv("STAFFING_EXCLUDED_PEOPLE", "")
        return cls(
            excluded_people=tuple(n.strip() for n in crudo.split(";") if n.strip()),
        )


@dataclass(frozen=True)
class DbSettings:
    url: str

    @classmethod
    def from_env(cls) -> DbSettings:
        return cls(url=_required("SUPABASE_DB_URL"))
