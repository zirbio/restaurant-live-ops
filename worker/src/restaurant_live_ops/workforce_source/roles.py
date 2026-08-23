"""Quién es dotación de turno y quién es dirección.

La columna F/A responde a una pregunta operativa —¿está cubierto el turno?— y
la dirección la ensucia: el gerente y el supervisor entran en el cuadrante con
una jornada que no es un puesto en la línea. Descontarlos deja el recuento
hablando de quien sirve, que es lo que se mira para decidir.

**El rol no viaja con el fichaje ni con el cuadrante.** Ni ``clockguards`` ni
``assignments`` traen más que el código de empleado, así que la categoría hay
que leerla del contrato vigente de cada persona, uno a uno: esta integración
no dispone de un endpoint que los entregue en bloque.

Nada de esto se guarda. Las categorías se resuelven en memoria dentro del
ciclo, sirven para decidir a quién se cuenta y se van con el proceso: en la
base de datos siguen entrando solo cifras.

**El nombre solo entra para las exclusiones nominales.** Una exclusión puede
compartir categoría con personas que sí hacen turno, y el código de empleado
puede cambiar. Se resuelve por nombre contra el endpoint de empleados en cada
ciclo, se usa el código resultante y se descarta todo lo demás. Los nombres
viven en ``STAFFING_EXCLUDED_PEOPLE``, nunca en el repositorio, y no se
escriben en logs ni en la base de datos.
"""

from __future__ import annotations

import unicodedata
from collections.abc import Callable, Iterable, Sequence
from datetime import date
from typing import Any

from restaurant_live_ops.workforce_source.client import WorkforceSourceClient

MAX_PEOPLE_PER_CYCLE = 500

# Categorías de ``person-categories`` que no cuentan como dotación de turno.
# Los asistentes y los encargados (004-007) cuentan porque forman parte del
# turno operativo; las tres categorías de dirección quedan fuera.
MANAGEMENT_CATEGORIES = frozenset({"001", "002", "003"})  # Supervisor, Franquiciado, Gerente


def employees_path(business_id: str, restaurant_id: str) -> str:
    """Fichas de empleado de un restaurante."""
    return f"/importer/api/v2/businesses/{business_id}/services/{restaurant_id}/employees"


def contracts_path(business_id: str, person_id: str) -> str:
    """Contratos de una persona, vigentes y pasados."""
    return f"/importer/api/v2/businesses/{business_id}/people/{person_id}/contracts"


def _parse_day(raw: Any) -> date | None:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def active_person_category(contracts: Iterable[dict[str, Any]], *, on: date) -> str | None:
    """Categoría del contrato en vigor en ``on``. ``None`` si no hay ninguno.

    Un contrato está en vigor cuando ya empezó y todavía no ha terminado. Los
    que empiezan en el futuro se descartan aunque no tengan fin: un indefinido
    firmado para septiembre, si se acepta, secuestra el rol de hoy. Cuando
    varios se solapan gana el de comienzo más reciente.

    Sin contrato vigente se devuelve ``None``, nunca una categoría de relleno:
    quien no se puede clasificar no se cuenta, y eso tiene que notarse.
    """
    vigentes: list[tuple[date, str]] = []
    for contrato in contracts:
        categoria = contrato.get("personCategory")
        if categoria is None:
            continue
        inicio = _parse_day(contrato.get("from"))
        fin = _parse_day(contrato.get("to"))
        if inicio is not None and inicio > on:
            continue
        if fin is not None and fin < on:
            continue
        vigentes.append((inicio or date.min, str(categoria)))
    if not vigentes:
        return None
    vigentes.sort(key=lambda par: par[0])
    return vigentes[-1][1]


def _normalise(texto: str) -> str:
    """Minúsculas, sin tildes y con los espacios colapsados."""
    plano = unicodedata.normalize("NFKD", texto)
    plano = "".join(c for c in plano if not unicodedata.combining(c))
    return " ".join(plano.lower().split())


def match_people_by_name(
    employees: Iterable[dict[str, Any]], names: Sequence[str]
) -> tuple[set[str], tuple[int, ...]]:
    """Códigos de empleado de las personas nombradas en ``names``.

    Devuelve también las POSICIONES de los nombres que no casaron con nadie
    —posiciones, no nombres: el aviso acaba en los logs del ciclo, y ahí no
    puede ir el nombre de nadie—. Una exclusión que deja de casar porque
    la fuente de personal reescribió la ficha tiene que verse; si no, el excluido vuelve al
    recuento sin que nadie se entere.
    """
    buscados = [_normalise(n) for n in names]
    encontrados: set[str] = set()
    casados: set[int] = set()

    for ficha in employees:
        if ficha.get("virtual"):
            continue
        completo = _normalise(f"{ficha.get('name') or ''} {ficha.get('surname') or ''}")
        for indice, buscado in enumerate(buscados):
            if buscado and completo == buscado:
                encontrados.add(str(ficha.get("employeeId")))
                casados.add(indice)

    sin_casar = tuple(i for i in range(len(buscados)) if i not in casados)
    return encontrados, sin_casar


def crew_filter(categories: dict[str, str], *, excluded: Iterable[str]) -> Callable[[str], bool]:
    """Predicado "esta persona cuenta como dotación de turno".

    Lanza ``KeyError`` con quien no tenga categoría resuelta: adivinarla
    colaría a un gerente en el recuento de equipo, o dejaría fuera a alguien de
    la línea. Es mejor que el ciclo falle y se vea.
    """
    fuera = set(excluded)

    def es_dotacion(person: str) -> bool:
        if person in fuera:
            return False
        return categories[person] not in MANAGEMENT_CATEGORIES

    return es_dotacion


def resolve_crew(
    categories: dict[str, str], *, people: Iterable[str], excluded: Iterable[str]
) -> tuple[Callable[[str], bool] | None, int]:
    """Predicado de dotación, o ``None`` si no se pudo clasificar a todos.

    Devuelve además cuánta gente quedó sin categoría. Pasa de verdad —un
    contrato caducado, un fallo a mitad del endpoint—, y ninguna de las dos
    salidas fáciles vale: contar a quien no se ha podido clasificar se inventa
    su rol, y tumbar el restaurante entero se llevaría por delante los
    recuentos totales, que sí son buenos. Se renuncia solo al recuento de
    equipo de ese local, la pantalla enseña una raya y el hueco se cuenta para
    que salga en el log del ciclo.
    """
    fuera = set(excluded)
    sin_clasificar = {p for p in people if p not in fuera and p not in categories}
    if sin_clasificar:
        return None, len(sin_clasificar)
    return crew_filter(categories, excluded=fuera), 0


async def fetch_person_categories(
    client: WorkforceSourceClient,
    *,
    business_id: str,
    people: Iterable[str],
    on: date,
) -> dict[str, str]:
    """Categoría vigente de cada persona. Una petición por cabeza.

    Se piden solo las personas que aparecen ese día en el cuadrante o en los
    fichajes. Quien no tenga contrato vigente queda fuera del mapa para que
    ``crew_filter`` lo cante en vez de suponerle un rol.
    """
    categorias: dict[str, str] = {}
    unique_people: list[str] = []
    seen: set[str] = set()
    for person in people:
        if person in seen:
            continue
        if len(unique_people) == MAX_PEOPLE_PER_CYCLE:
            raise ValueError("la respuesta supera el límite de personas")
        seen.add(person)
        unique_people.append(person)
    for persona in unique_people:  # sin repetir, en orden estable
        contratos = await client.get_json(contracts_path(business_id, persona))
        categoria = active_person_category(list(contratos or []), on=on)
        if categoria is not None:
            categorias[persona] = categoria
    return categorias


async def fetch_named_exclusions(
    client: WorkforceSourceClient,
    *,
    business_id: str,
    restaurant_id: str,
    names: Sequence[str],
) -> tuple[set[str], tuple[int, ...]]:
    """Códigos de las exclusiones nominales en un restaurante.

    Es la ÚNICA llamada de todo el proyecto al endpoint de empleados, que
    devuelve nombre, correo, fecha de nacimiento y género. De la respuesta solo
    sale el código de quien está en ``names``; el resto se descarta al volver.
    """
    if not names:
        return set(), ()
    fichas = await client.get_json(employees_path(business_id, restaurant_id))
    return match_people_by_name(list(fichas or []), names)
