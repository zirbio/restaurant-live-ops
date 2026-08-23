"""Reparto de la presencia de personal en horas civiles de Madrid.

Dos reglas gobiernan este módulo:

1. **Nada que no haya ocurrido cuenta.** El final efectivo de un fichaje es
   ``min(salida o ahora, ahora)``. La misma fórmula sirve para el que sigue
   dentro (sin salida) y para el que tiene la salida cuadrada por adelantado
   con la hora prevista, que la fuente de personal devuelve sin marcarla de ninguna forma:
   una salida posterior al instante actual, sencillamente, no ha ocurrido.
2. **Se cuentan personas, no tramos.** Quien cambia de tarea dentro de la misma
   hora —de Iniciador a Cajero, por ejemplo— sigue siendo una persona.

**Toda la aritmética se hace en UTC, y solo la etiqueta de la hora sale del
reloj de Madrid.** No es una manía: restar dos fechas que comparten el mismo
objeto de zona horaria da la diferencia de reloj de pared, no el tiempo real
transcurrido, así que el 25 de octubre —el día de 25 horas— saldría de 24 y la
hora repetida contaría la mitad de lo que duró. El error no levanta ninguna
excepción; simplemente publica horas de menos dos veces al año.

Con las ventanas resueltas en UTC, la hora inexistente de marzo queda a cero y
la repetida de octubre suma 120 minutos, que es justo lo que se quiere.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from restaurant_live_ops.tz import BUSINESS_DAY_CUTOFF_HOUR, MADRID

# Cortesía acotada sobre la salida prevista para no recortar un turno que se
# alarga ligeramente.
SHIFT_END_GRACE = timedelta(minutes=30)

# Tope para un fichaje abierto sin salida prevista. Impide que un marcaje
# arrastrado siga sumando indefinidamente.
OPEN_PUNCH_CAP = timedelta(hours=10)

# Hueco por debajo del cual dos tramos consecutivos del cuadrante de una misma
# persona son la MISMA jornada y se fusionan antes de leer su salida prevista.
#
# La fuente entrega un tramo por marco de tarea, no por turno. Este límite
# configurable fusiona pausas acotadas sin unir turnos partidos separados.
SEGMENT_MERGE_GAP = timedelta(hours=2)


@dataclass(frozen=True)
class Interval:
    """Tramo de presencia de una persona, en hora de Madrid.

    ``end`` nulo significa fichaje abierto: la persona sigue dentro.
    """

    person: str
    start: datetime
    end: datetime | None


def merge_intervals(intervals: Iterable[Interval]) -> list[Interval]:
    """Fusiona tramos solapados o contiguos por instante real.

    Conserva los límites originales —incluido ``fold``—, pero toda decisión
    se toma en UTC para distinguir las dos apariciones de una hora repetida.
    """

    def instant(value: datetime) -> datetime:
        return value.astimezone(UTC)

    by_person: dict[str, list[Interval]] = defaultdict(list)
    for interval in intervals:
        by_person[interval.person].append(interval)

    merged: list[Interval] = []
    for person, person_intervals in by_person.items():
        ordered = sorted(person_intervals, key=lambda interval: instant(interval.start))
        if not ordered:
            continue
        current = ordered[0]
        for following in ordered[1:]:
            if current.end is None or instant(following.start) <= instant(current.end):
                if current.end is None or following.end is None:
                    merged_end = None
                else:
                    merged_end = max(current.end, following.end, key=instant)
                current = Interval(person=person, start=current.start, end=merged_end)
                continue
            merged.append(current)
            current = following
        merged.append(current)

    return sorted(merged, key=lambda interval: (instant(interval.start), interval.person))


@dataclass(frozen=True)
class HourlyStaffing:
    """Recuentos de una hora civil.

    ``clocked_count`` nulo significa que la hora todavía no ha empezado. Un
    cero diría "no fichó nadie", que es una afirmación distinta y falsa.

    ``open_anomalies`` cuenta las PERSONAS con un fichaje abierto que se están
    ignorando en esa hora porque su corte ya ha pasado. No es un aviso
    decorativo: dice que la cifra de al lado se ha corregido a la baja.

    Los campos ``crew_*`` son los mismos recuentos sin la dirección: es la
    cifra que se enseña, porque responde a si el turno está cubierto. Nulos
    cuando no se pudo saber quién es quién —ahí la pantalla muestra una raya,
    que es lo honesto—; los totales, en cambio, se guardan siempre enteros
    porque el VPHH se calcula con las horas brutas de todo el mundo.

    ``crew_open_anomalies`` es el aviso que acompaña a esa cifra: cuenta solo
    los recortados de turno. El aviso tiene que hablar de la MISMA cifra que
    se pinta, o miente al revés: un encargado de dirección con el fichaje
    abierto marcaría una hora en la que falta de verdad alguien del equipo, y
    se leería "esto no es una ausencia" justo donde sí lo es.
    """

    hour: int
    clocked_count: int | None
    assigned_count: int
    clocked_minutes: int | None
    assigned_minutes: int
    open_anomalies: int
    crew_clocked_count: int | None = None
    crew_assigned_count: int | None = None
    crew_clocked_minutes: int | None = None
    crew_assigned_minutes: int | None = None
    crew_open_anomalies: int | None = None


@dataclass(frozen=True)
class _Window:
    """Una hora civil: su etiqueta y sus límites reales, ya en UTC."""

    hour: int
    start: datetime
    end: datetime


def _hour_windows(day: date) -> list[_Window]:
    """Las horas del día de NEGOCIO, con sus límites resueltos en UTC.

    La rejilla corre de las 06:00 de ``day`` a las 06:00 del día civil
    siguiente, igual que la grid de ventas de la fuente de ventas: la fila 23 es la noche de
    ``day`` y las filas 0 a 5 su madrugada, la que cierra ese mismo turno. Las
    etiquetas salen del reloj de pared de Madrid (06…23 y 00…05, saltándose la
    que no existe en marzo); la duración de cada una sale de UTC, que es la
    única que dice la verdad los días de cambio de hora.
    """
    apertura = datetime(day.year, day.month, day.day, BUSINESS_DAY_CUTOFF_HOUR, tzinfo=MADRID)
    siguiente = apertura + timedelta(days=1)
    fin_dia = siguiente.astimezone(UTC)

    marcas: list[datetime] = []
    cursor = apertura
    while cursor.astimezone(UTC) < fin_dia:
        marcas.append(cursor)
        cursor += timedelta(hours=1)

    ventanas: list[_Window] = []
    for indice, marca in enumerate(marcas):
        limite = marcas[indice + 1] if indice + 1 < len(marcas) else siguiente
        ventanas.append(
            _Window(hour=marca.hour, start=marca.astimezone(UTC), end=limite.astimezone(UTC))
        )
    return ventanas


def hours_settled_by(day: date, moment: datetime) -> set[int]:
    """Horas del día de negocio ``day`` que ya habían cerrado en ``moment``.

    Contesta a "¿esto ya debería haber ocurrido?" sin que quien pregunta tenga
    que saber que la fila 2 de un día es la madrugada del día civil siguiente,
    ni que en octubre hay una hora que dura el doble. En el día de 25 horas,
    una hora solo cuenta como cerrada cuando lo están sus dos ventanas.
    """
    limite = moment.astimezone(UTC)
    ventanas = _hour_windows(day)
    abiertas = {v.hour for v in ventanas if v.end > limite}
    return {v.hour for v in ventanas if v.end <= limite} - abiertas


def _overlap_minutes(start: datetime, end: datetime, lo: datetime, hi: datetime) -> float:
    """Minutos de solape entre dos tramos. Todo debe llegar ya en UTC."""
    solape = min(end, hi) - max(start, lo)
    return max(0.0, solape.total_seconds() / 60)


def _effective_end(
    entrada: datetime,
    salida: datetime | None,
    *,
    ahora: datetime,
    prevista: datetime | None,
    siguiente: datetime | None,
) -> datetime:
    """Cuándo deja de contar un fichaje. Todo debe llegar ya en UTC.

    El fichaje CERRADO no se recorta: su salida es la buena. Solo se le aplica
    la regla de siempre —nada que no haya ocurrido cuenta—, que también cubre
    la salida cuadrada por adelantado con la hora prevista.

    El ABIERTO es el que miente en cuanto la persona se va sin ficharla, así
    que se corta en el primero de cuatro momentos: ahora, la salida prevista de
    ESE fichaje más la cortesía, el tope de duración y la entrada del siguiente
    fichaje de esa misma persona. Gana el más temprano.
    """
    if salida is not None:
        return min(salida, ahora)
    tope = entrada + OPEN_PUNCH_CAP
    if prevista is not None:
        tope = min(tope, prevista + SHIFT_END_GRACE)
    if siguiente is not None:
        tope = min(tope, siguiente)
    return min(ahora, tope)


def hourly_staffing(
    clocked: list[Interval],
    assigned: list[Interval],
    *,
    day: date,
    now: datetime,
    crew: Callable[[str], bool] | None = None,
) -> list[HourlyStaffing]:
    """Recuentos de personal fichado y asignado por hora del día de negocio.

    ``crew`` decide quién es dotación de turno y quién dirección. Sin él los
    recuentos ``crew_*`` salen nulos: no se sabe quién es quién, y repetir el
    total ahí colaría a la dirección haciéndola pasar por equipo.
    """
    ventanas = _hour_windows(day)
    ahora = now.astimezone(UTC)

    # Se convierte una sola vez, fuera del bucle de horas.
    fichajes = [
        (t.person, t.start.astimezone(UTC), t.end.astimezone(UTC) if t.end else None)
        for t in clocked
    ]
    cuadrante: list[tuple[str, datetime, datetime]] = []
    for tramo in merge_intervals(t for t in assigned if t.end is not None):
        if tramo.end is not None:
            cuadrante.append((tramo.person, tramo.start.astimezone(UTC), tramo.end.astimezone(UTC)))

    # La salida prevista se lee POR FICHAJE: es el final del BLOQUE de
    # cuadrante que contiene la entrada de ese fichaje —o el primero que
    # termina después de ella—, no el del último tramo del día.
    #
    # Un fichaje abierto se vincula al bloque de cuadrante que le corresponde, no
    # al último tramo del día. Así un turno partido no atraviesa su pausa y un
    # cambio de tarea no corta una jornada continua. Los tramos cercanos se
    # fusionan antes mediante ``SEGMENT_MERGE_GAP``.
    #
    # Sigue siendo "la salida prevista de esa persona", que es la regla
    # aprobada; lo que cambia es que se lee de la jornada que le toca a cada
    # fichaje. Los tramos de fuera de la rejilla no cuentan, que el ciclo pide
    # días civiles adyacentes para cubrir un solo día de negocio.
    apertura, cierre = ventanas[0].start, ventanas[-1].end
    tramos_cuadrante: dict[str, list[tuple[datetime, datetime]]] = defaultdict(list)
    for persona, inicio, fin in cuadrante:
        if fin <= apertura or inicio >= cierre:
            continue
        tramos_cuadrante[persona].append((inicio, fin))

    # Los finales de los bloques ya fusionados, en orden. Salen ordenados
    # solos: los tramos se recorren por hora de inicio y cada bloque termina
    # antes de que empiece el siguiente, que es lo que los separa.
    finales_cuadrante: dict[str, list[datetime]] = {}
    for persona, tramos in tramos_cuadrante.items():
        tramos.sort()
        finales: list[datetime] = []
        fin_bloque = tramos[0][1]
        for inicio, fin in tramos[1:]:
            if inicio - fin_bloque < SEGMENT_MERGE_GAP:
                # Mismo bloque. ``max`` porque un tramo puede quedar contenido
                # en el anterior —dos tareas solapadas— y no debe acortarlo.
                fin_bloque = max(fin_bloque, fin)
                continue
            finales.append(fin_bloque)
            fin_bloque = fin
        finales.append(fin_bloque)
        finales_cuadrante[persona] = finales

    def salida_prevista(persona: str, entrada: datetime) -> datetime | None:
        """Final del primer bloque de cuadrante que termina tras ``entrada``.

        Con los tramos ya fusionados, ese bloque es la jornada que contiene la
        entrada siempre que la haya: los bloques anteriores terminaron antes de
        que empezara el suyo, y el suyo no puede terminar antes que ella.

        Nulo cuando esa persona no tiene ningún bloque que acabe después de esa
        entrada: ahí no hay salida prevista de la que colgar el corte y manda
        el tope de duración, como con quien no figura en el cuadrante.
        """
        finales = finales_cuadrante.get(persona)
        if not finales:
            return None
        # ``bisect_right`` deja fuera el bloque que termina EXACTAMENTE en la
        # entrada: ese ya se cerró y no dice nada de este fichaje.
        indice = bisect_right(finales, entrada)
        return finales[indice] if indice < len(finales) else None

    # La entrada del SIGUIENTE fichaje de cada persona. Un fichaje abierto no
    # puede seguir contando cuando esa misma persona ya ha vuelto a fichar:
    # volver a fichar prueba que había salido, y contar los dos a la vez le
    # daría a una hora de 60 minutos más de 60, que es físicamente imposible y
    # va al denominador del VPHH. Con la salida prevista leída por fichaje este
    # límite muerde menos, pero sigue haciendo falta cuando un solo tramo de
    # cuadrante cubre los dos marcajes —quien ficha, se deja el marcaje abierto
    # y vuelve a fichar dentro de su propio turno—.
    # El fichaje CERRADO no se toca: dos tramos seguidos del mismo día —salir a
    # comer y volver— son legítimos y no se pisan.
    entradas: dict[str, list[datetime]] = defaultdict(list)
    for persona, entrada, _salida in fichajes:
        entradas[persona].append(entrada)

    def siguiente_entrada(persona: str, entrada: datetime) -> datetime | None:
        posteriores = [otra for otra in entradas[persona] if otra > entrada]
        return min(posteriores) if posteriores else None

    # El final efectivo de cada fichaje, calculado una sola vez: de aquí salen
    # tanto el reparto de minutos por hora como los fichajes recortados, en
    # vez de recalcularlo en cada una de las 24 ventanas.
    fichajes_efectivos = [
        (
            persona,
            entrada,
            _effective_end(
                entrada,
                salida,
                ahora=ahora,
                prevista=salida_prevista(persona, entrada),
                siguiente=siguiente_entrada(persona, entrada),
            ),
            salida,
        )
        for persona, entrada, salida in fichajes
    ]

    fichajes_contables: list[tuple[str, datetime, datetime]] = []
    for tramo in merge_intervals(
        Interval(person=persona, start=entrada, end=final)
        for persona, entrada, final, _salida in fichajes_efectivos
    ):
        if tramo.end is not None:
            fichajes_contables.append((tramo.person, tramo.start, tramo.end))

    # Los fichajes abiertos que ya no cuentan, con el instante en que dejaron
    # de contar. Los que siguen dentro no salen de aquí: no se ha corregido
    # nada mientras la persona está trabajando.
    recortados: list[tuple[str, datetime]] = [
        (persona, final)
        for persona, _entrada, final, salida in fichajes_efectivos
        if salida is None and final < ahora
    ]

    personas_fichadas: dict[int, set[str]] = defaultdict(set)
    minutos_fichados: dict[int, float] = defaultdict(float)
    anomalias: dict[int, set[str]] = defaultdict(set)
    equipo_anomalias: dict[int, set[str]] = defaultdict(set)
    personas_asignadas: dict[int, set[str]] = defaultdict(set)
    minutos_asignados: dict[int, float] = defaultdict(float)
    equipo_fichado: dict[int, set[str]] = defaultdict(set)
    equipo_minutos_fichados: dict[int, float] = defaultdict(float)
    equipo_asignado: dict[int, set[str]] = defaultdict(set)
    equipo_minutos_asignados: dict[int, float] = defaultdict(float)

    for indice, ventana in enumerate(ventanas):
        # En una hora ya empezada, el cuadrante se recorta a ahora igual que
        # los marcajes: quien entra a las 20:45 no falta a las 20:03. En una
        # hora futura no se recorta nada, porque ahí la plantilla planificada
        # entera es justo lo que se quiere ver del día que queda.
        empezada = ahora > ventana.start
        for persona, entrada, final in fichajes_contables:
            if final <= entrada:
                continue  # aún no ha empezado, o la salida precede a la entrada
            minutos = _overlap_minutes(entrada, final, ventana.start, ventana.end)
            if minutos <= 0:
                continue
            personas_fichadas[indice].add(persona)
            minutos_fichados[indice] += minutos
            if crew is not None and crew(persona):
                equipo_fichado[indice].add(persona)
                equipo_minutos_fichados[indice] += minutos

        # Se marca cada hora empezada desde el corte: a partir de ese instante
        # la persona deja de sumar, y la propia hora del corte cuenta solo
        # hasta él, no la hora entera.
        for persona, corte in recortados:
            if ventana.end > corte and empezada:
                anomalias[indice].add(persona)
                if crew is not None and crew(persona):
                    equipo_anomalias[indice].add(persona)

        for persona, inicio, fin in cuadrante:
            hasta = min(fin, ahora) if empezada else fin
            if hasta <= inicio:
                continue  # su tramo de esta hora todavía no ha llegado
            minutos = _overlap_minutes(inicio, hasta, ventana.start, ventana.end)
            if minutos <= 0:
                continue
            personas_asignadas[indice].add(persona)
            minutos_asignados[indice] += minutos
            if crew is not None and crew(persona):
                equipo_asignado[indice].add(persona)
                equipo_minutos_asignados[indice] += minutos

    filas: list[HourlyStaffing] = []
    for indice, ventana in enumerate(ventanas):
        # Una hora sin nadie fichado ni asignado igual necesita fila si lleva
        # una anomalía: es la única forma de que el corte se vea en pantalla.
        if (
            indice not in personas_fichadas
            and indice not in personas_asignadas
            and indice not in anomalias
        ):
            continue
        empezada = ahora > ventana.start
        con_equipo = crew is not None
        clocked_count = len(personas_fichadas[indice]) if empezada else None
        assigned_count = len(personas_asignadas[indice])
        clocked_minutes = round(minutos_fichados[indice]) if empezada else None
        assigned_minutes = round(minutos_asignados[indice])
        crew_clocked_count = len(equipo_fichado[indice]) if con_equipo and empezada else None
        crew_assigned_count = len(equipo_asignado[indice]) if con_equipo else None
        crew_clocked_minutes = (
            round(equipo_minutos_fichados[indice]) if con_equipo and empezada else None
        )
        crew_assigned_minutes = round(equipo_minutos_asignados[indice]) if con_equipo else None
        window_minutes = round((ventana.end - ventana.start).total_seconds() / 60)
        for minutes, count in (
            (clocked_minutes, clocked_count),
            (assigned_minutes, assigned_count),
            (crew_clocked_minutes, crew_clocked_count),
            (crew_assigned_minutes, crew_assigned_count),
        ):
            if minutes is not None and (count is None or minutes > count * window_minutes):
                raise ValueError("staffing-minutes-invariant")
        filas.append(
            HourlyStaffing(
                hour=ventana.hour,
                clocked_count=clocked_count,
                assigned_count=assigned_count,
                clocked_minutes=clocked_minutes,
                assigned_minutes=assigned_minutes,
                open_anomalies=len(anomalias[indice]),
                crew_clocked_count=crew_clocked_count,
                crew_assigned_count=crew_assigned_count,
                crew_clocked_minutes=crew_clocked_minutes,
                crew_assigned_minutes=crew_assigned_minutes,
                crew_open_anomalies=len(equipo_anomalias[indice]) if con_equipo else None,
            )
        )
    return filas
