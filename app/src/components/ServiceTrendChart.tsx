import { monthAxisLabel, type MonthKey } from "../lib/month";
import type { TrendPoint } from "../lib/monthly";
import {
  serviceBands,
  trendSegments,
  type Band,
  type Hueco,
  type SegmentPoint,
} from "../lib/serviceBands";
import type { Light, Objectives } from "../lib/types";

/**
 * Tendencia mensual de los tiempos de servicio: una franja por métrica.
 *
 * Compartir un único eje aplasta métricas con recorridos distintos. Separadas,
 * cada una usa su propia escala y conserva legibles todos los meses.
 *
 * Cada franja lleva su objetivo dibujado como una escalera, porque puede
 * cambiar a lo largo del año. Con una sola raya horizontal se juzgarían meses
 * con la vara equivocada. Las cifras se colorean contra el objetivo de SU mes, y el mes sin
 * objetivo guardado —2025 no tiene— se queda en gris: no se juzga lo que no
 * tiene contra qué medirse.
 *
 * Un mes sin dato NO se une con una recta al siguiente: la línea se corta. Unir
 * por encima de un hueco dibuja una evolución que nadie ha medido.
 *
 * El color y la tipografía salen de la hoja de estilos (`.trendChart`), no de
 * constantes aquí: la paleta del proyecto vive en `styles.css` y un segundo
 * juego de hexadecimales se separa del primero en cuanto alguien toca uno.
 */

const ANCHO = 344;
/** Margen lateral: media cifra de tres dígitos, para que no se salga la del borde. */
const IZQUIERDA = 9;
const DERECHA = 335;
const CABECERA_FRANJA = 11;
const ALTO_AREA = 46;
const SEPARACION = 9;
const ALTO_EJE = 13;
const MARGEN_ARRIBA = 2;

/** Tamaño de la cifra de cada mes y cuánto se sube por encima de su punto. */
const CIFRA = 8.5;
const CIFRA_SOBRE_PUNTO = 5.5;
/**
 * El aire que hay que reservar arriba para esa cifra, en píxeles del `viewBox`.
 *
 * Se lo damos a `serviceBands` en vez de dejar que adivine una fracción: el
 * tamaño de la letra y su desplazamiento se deciden AQUÍ, y cuando el hueco se
 * calculaba allí, subir la letra medio punto metía la cifra dentro del rótulo
 * de la cabecera sin que fallara ni un test. `0.7` es la altura de mayúsculas
 * de IBM Plex Mono relativa a su cuerpo.
 */
const HUECO: Hueco = { areaPx: ALTO_AREA, headroomPx: CIFRA_SOBRE_PUNTO + CIFRA * 0.7 };

export function ServiceTrendChart({
  points,
  objectives,
  month,
  partialDays,
  axisMode = "month",
}: {
  points: TrendPoint[];
  /** Objetivos de ESE restaurante, mes a mes. Los de 2025 no existen. */
  objectives: Map<MonthKey, Objectives>;
  /** El mes que se está mirando: es su objetivo el que va en la cabecera. */
  month: MonthKey;
  /** Días de la ventana y del mes cuando el último punto aún no ha cerrado. */
  partialDays: { covered: number; total: number } | null;
  /** Meses históricos o días cerrados del mes en curso. */
  axisMode?: "month" | "day";
}) {
  // En la media acumulada todos los puntos se juzgan con el objetivo del mes
  // que se está mirando. La clave horizontal es una fecha completa, por eso
  // se construye aquí el mapa equivalente en vez de fingir meses distintos.
  const objetivoActual = objectives.get(month);
  const objetivosDeSerie: Map<MonthKey, Objectives> =
    axisMode === "month"
      ? objectives
      : new Map(
          objetivoActual === undefined
            ? []
            : points.map((p) => [p.month, objetivoActual] as const),
        );
  const bandas = serviceBands(points, objetivosDeSerie, HUECO);
  if (bandas.length === 0) return null;

  const alto =
    MARGEN_ARRIBA +
    bandas.length * (CABECERA_FRANJA + ALTO_AREA) +
    (bandas.length - 1) * SEPARACION +
    ALTO_EJE;

  const paso =
    points.length === 1 ? DERECHA - IZQUIERDA : (DERECHA - IZQUIERDA) / (points.length - 1);
  const x = (i: number) => (points.length === 1 ? (IZQUIERDA + DERECHA) / 2 : IZQUIERDA + i * paso);
  const medioPaso = paso / 2;
  // Las fronteras de año, todas: con trece meses solo hay una, pero la ventana
  // la fija una constante de otro fichero y un `findIndex` se quedaría con la
  // primera sin avisar de nada.
  const cambiosDeAnio: number[] = [];
  if (axisMode === "month") {
    for (let i = 1; i < points.length; i += 1) {
      if (points[i]!.month.slice(0, 4) !== points[i - 1]!.month.slice(0, 4)) {
        cambiosDeAnio.push(i);
      }
    }
  }

  return (
    // La caja de fuera reserva la altura con `padding-bottom` en porcentaje —que
    // se mide sobre el ANCHO— porque Safari de iOS no la deduce del `viewBox`
    // cuando el contenedor no da altura: colapsaba la gráfica a cero píxeles en
    // el móvil mientras en el ordenador se veía. La regla sigue entera en
    // `styles.css`; de aquí solo sale la proporción, que depende de cuántas
    // franjas haya: un restaurante sin servicio en vehículo se queda en dos.
    <div
      className="trendChart"
      style={{ "--trend-aspect": alto / ANCHO } as React.CSSProperties}
    >
      <svg viewBox={`0 0 ${ANCHO} ${alto}`}>
        {bandas.map((banda, n) => (
          <Franja
            key={banda.key}
            banda={banda}
            arriba={MARGEN_ARRIBA + n * (CABECERA_FRANJA + ALTO_AREA + SEPARACION)}
            x={x}
            medioPaso={medioPaso}
            cambiosDeAnio={cambiosDeAnio}
            objetivoDelMes={objectives.get(month)?.[banda.key] ?? null}
            ultimoParcial={axisMode === "month" && partialDays !== null}
            mostrarCifra={(i) =>
              axisMode === "month" || etiquetaEje(points[i]!.month, i, points.length, "day") !== ""
            }
          />
        ))}

        {points.map((p, i) => (
          <text
            key={p.month}
            x={x(i)}
            y={alto - 3}
            textAnchor="middle"
            fontSize="7.5"
            fontWeight={i === points.length - 1 ? 600 : 400}
            className={i === points.length - 1 ? "trendChart__mes" : "trendChart__mesTenue"}
          >
            {etiquetaEje(p.month, i, points.length, axisMode)}
            {/* El mes en curso lleva días de menos: la marca lo dice aquí y el
                pie del bloque explica cuántos. Sin ella, dos días de agosto se
                leen como un mes entero al lado de doce que sí lo son. */}
            {axisMode === "month" && i === points.length - 1 && partialDays !== null ? "*" : ""}
          </text>
        ))}
      </svg>
    </div>
  );
}

function etiquetaEje(
  periodo: string,
  indice: number,
  total: number,
  mode: "month" | "day",
): string {
  if (mode === "month") return monthAxisLabel(periodo);
  const dia = Number(periodo.slice(8));
  // Con hasta 31 puntos, rotularlos todos sería una mancha. El primero, cada
  // quinto y el último bastan para ubicar la evolución sin perder el cierre.
  return indice === 0 || indice === total - 1 || dia % 5 === 0 ? String(dia) : "";
}

function Franja({
  banda,
  arriba,
  x,
  medioPaso,
  cambiosDeAnio,
  objetivoDelMes,
  ultimoParcial,
  mostrarCifra,
}: {
  banda: Band;
  arriba: number;
  x: (i: number) => number;
  medioPaso: number;
  cambiosDeAnio: number[];
  /**
   * El objetivo del mes que se está MIRANDO, no el del último punto de la
   * serie: cuando la tendencia no llega hasta el mes en pantalla —un mes con
   * días cerrados pero sin ninguna captura de la fuente de ventas—, el último punto es de otro
   * mes y su objetivo contradiría a las pastillas de aquí encima.
   */
  objetivoDelMes: number | null;
  ultimoParcial: boolean;
  /** En una serie diaria evita que 31 cifras de tres dígitos se solapen. */
  mostrarCifra: (indice: number) => boolean;
}) {
  const suelo = arriba + CABECERA_FRANJA + ALTO_AREA;
  const techo = arriba + CABECERA_FRANJA;
  const y = (v: number) => suelo - ((v - banda.min) / (banda.max - banda.min)) * ALTO_AREA;
  const ultimo = banda.values.length - 1;
  // Vacío cuando ningún mes de la franja tiene objetivo guardado: 2025 entero,
  // por ejemplo. Un `<path>` sin `d` no pinta nada, pero tampoco pinta nada.
  const escalones = banda.objectiveOffScale ? "" : escalera(banda, x, y, medioPaso);

  return (
    <g>
      <text x={0} y={arriba + 7} fontSize="8.5" fontWeight="600" className="trendChart__metrica">
        {banda.label}
      </text>
      {objetivoDelMes !== null && (
        <text x={ANCHO} y={arriba + 7} textAnchor="end" fontSize="7.5" className="trendChart__obj">
          obj ≤ {objetivoDelMes}&quot;
        </text>
      )}

      {cambiosDeAnio.map((i) => (
        <line
          key={`a${i}`}
          x1={x(i) - medioPaso}
          y1={techo}
          x2={x(i) - medioPaso}
          y2={suelo}
          className="trendChart__anio"
          strokeDasharray="2 3"
        />
      ))}

      {/* La escalera del objetivo, en un solo trazo: un peldaño por mes, con su
          contrahuella donde el objetivo cambia, y cortada donde no hay objetivo
          guardado. Una raya horizontal única sería mentira —el objetivo baja a
          lo largo del año—, y un `<line>` por tramo eran hasta veinticinco
          nodos por franja para dibujar lo mismo.

          Si el objetivo queda tan lejos que no cabe sin aplastar la serie, no
          se dibuja: pegarlo al borde lo pondría a una altura que no es la suya.
          El número exacto sigue en la cabecera. */}
      {escalones !== "" && (
        <path d={escalones} fill="none" className="trendChart__objLinea" strokeDasharray="3 2.5" />
      )}

      {trendSegments(banda.values).map((tramo, i) => (
        <path
          key={`r${i}`}
          d={`${curva(tramo, x, y)} L${x(tramo[tramo.length - 1]!.i)},${suelo} L${x(tramo[0]!.i)},${suelo} Z`}
          className="trendChart__area"
        />
      ))}
      {trendSegments(banda.values).map((tramo, i) => (
        <path key={`l${i}`} d={curva(tramo, x, y)} fill="none" className="trendChart__linea" />
      ))}

      {banda.values.map((v, i) => {
        if (v.value === null) return null;
        const esUltimo = i === ultimo;
        return (
          <circle
            key={`c${v.month}`}
            cx={x(i)}
            cy={y(v.value)}
            r={esUltimo ? 2.8 : 1.7}
            // El mes en curso va HUECO mientras no cierre: el punto relleno es
            // el de un mes completo, y dos días de agosto no lo son.
            fill={esUltimo && ultimoParcial ? "#fff" : esUltimo ? colorDeLuz(v.light) : undefined}
            stroke={esUltimo && ultimoParcial ? colorDeLuz(v.light) : esUltimo ? "#fff" : undefined}
            className={esUltimo ? undefined : "trendChart__punto"}
            strokeWidth="1.2"
          />
        );
      })}

      {/* La cifra de los trece meses, coloreada contra el objetivo de SU mes.
          El halo blanco no es adorno: la escalera del objetivo pasa por donde
          caen las cifras cuando el mes anda cerca de cumplir, que es justo
          cuando hay que leerlas bien. */}
      {banda.values.map((v, i) =>
        v.value === null || !mostrarCifra(i) ? null : (
          <text
            key={`v${v.month}`}
            x={x(i)}
            y={y(v.value) - CIFRA_SOBRE_PUNTO}
            textAnchor="middle"
            fontSize={CIFRA}
            fontWeight="600"
            fill={colorDeLuz(v.light)}
            className="trendChart__cifra"
          >
            {v.value}
          </text>
        ),
      )}
    </g>
  );
}

/**
 * La escalera del objetivo como un único `d`.
 *
 * Cada mes aporta su peldaño, de medio paso a cada lado de su punto y recortado
 * al área —el primer mes y el último están en el borde—. Dos meses seguidos con
 * objetivos distintos se unen con la contrahuella; un mes sin objetivo arranca
 * un subtrazo nuevo, así que el punteado se reinicia igual que cuando eran
 * líneas sueltas.
 */
function escalera(
  banda: Band,
  x: (i: number) => number,
  y: (v: number) => number,
  medioPaso: number,
): string {
  let d = "";
  let previo: number | null = null;

  banda.values.forEach((v, i) => {
    if (v.objective === null) {
      previo = null;
      return;
    }
    const izquierda = Math.max(IZQUIERDA, x(i) - medioPaso);
    const derecha = Math.min(DERECHA, x(i) + medioPaso);
    if (previo === null) d += `M${izquierda},${y(v.objective)}`;
    else if (previo !== v.objective) d += `M${izquierda},${y(previo)} L${izquierda},${y(v.objective)}`;
    d += ` L${derecha},${y(v.objective)}`;
    previo = v.objective;
  });

  return d;
}

/** Curva suave con los controles a media distancia, como en el diseño. */
function curva(tramo: SegmentPoint[], x: (i: number) => number, y: (v: number) => number): string {
  const primero = tramo[0]!;
  let d = `M${x(primero.i)},${y(primero.value)}`;
  // Un mes suelto entre dos huecos no traza línea: su punto lo pinta el círculo.
  for (let n = 1; n < tramo.length; n++) {
    const a = tramo[n - 1]!;
    const b = tramo[n]!;
    const medio = (x(a.i) + x(b.i)) / 2;
    d += ` C${medio},${y(a.value)} ${medio},${y(b.value)} ${x(b.i)},${y(b.value)}`;
  }
  return d;
}

/** Los mismos colores de estado que el resto de la app, por su token. */
function colorDeLuz(light: Light): string {
  if (light === "ok") return "var(--pos)";
  if (light === "warn") return "var(--warn)";
  if (light === "bad") return "var(--neg)";
  return "var(--dim)";
}
