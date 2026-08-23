/** Tipos de las filas que sirve Supabase. */

/** Una hora del día: venta real, previsión y dotación. */
export interface HourRow {
  hour: number;
  net: number | null;
  gc: number | null;
  drive_through_net: number | null;
  /** Coches de servicio en vehículo de esa hora: su parte de los guest counts. */
  drive_through_cars: number | null;
  delivery_net: number | null;
  /** Pedidos de Delivery de esa hora: su parte de los guest counts. */
  delivery_count: number | null;
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
  proj_sales: number | null;
  proj_gc: number | null;
  /**
   * Personas de turno fichadas en esa hora, SIN la dirección: el gerente y el
   * supervisor entran en el cuadrante con una jornada que no es un puesto en
   * la línea, y mezclarlos enturbia la pregunta que se hace quien mira esto.
   * Nulo = la hora aún no ha empezado, o no se pudo saber quién era quién.
   */
  clocked: number | null;
  /** Personas de turno asignadas para esa hora, sin la dirección. */
  assigned: number | null;
  /**
   * Personas DE EQUIPO con el fichaje abierto que se ignoran en esa hora porque
   * ya pasó su salida prevista. Cuenta sobre la misma población que `clocked`,
   * sin la dirección: si contara sobre todos, un encargado con el marcaje
   * abierto marcaría una hora en la que falta de verdad alguien del equipo.
   * Mayor que cero significa que `clocked` va corregido a la baja; nulo, que no
   * se pudo saber quién es quién.
   */
  clipped: number | null;
}

export interface Restaurant {
  id: string;
  name: string;
  sort_order: number;
  /** Si es falso, el canal y su métrica asociada no aplican. */
  has_drive_through: boolean;
}

/** Objetivos de tiempos de servicio del mes en curso. OEPE nulo = no aplica. */
export interface Objectives {
  restaurant_id: string;
  kvs: number;
  r2p: number;
  oepe: number | null;
}

/** Último ciclo de cada fuente: es lo que da la marca de frescura. */
export interface IngestRun {
  id: number;
  restaurant_id: string;
  source: "sales" | "sales_backfill" | "workforce" | "staffing";
  started_at: string;
  finished_at: string | null;
  status: "running" | "ok" | "error";
  rows_written: number;
  error: string | null;
}

/** De dónde salió el día que se está mirando. */
export type DaySource = "live" | "import" | "backfill" | "pos";
export type DayProvenanceSource = DaySource | "mixed";

/** Calidad del día después de llevar cada hora a la ventana común 06→06. */
export type DailyQuality = "legacy" | "clean" | "rebucketed";

/** Estado de la fila diaria efectiva, ya adaptado al dominio de la app. */
export interface DailyStatus {
  restaurantId: string;
  capturedAt: string;
  source: DaySource;
  quality: DailyQuality;
  contributingCaptures: number;
}

export interface DayProvenance {
  source: DayProvenanceSource;
  /** Cuándo se capturó de verdad, en ISO con zona. */
  capturedAt: string;
  /** Locales visibles cuyo cierre todavía no está confirmado. */
  pendingRestaurantNames: string[];
}

export interface DayTotals {
  net: number | null;
  gc: number | null;
  /** Previsión de las horas que ya tienen venta real. */
  projToNow: number | null;
  /** Previsión del día completo, para la barra de progreso. */
  projDay: number | null;
  projGcToNow: number | null;
}

/**
 * Tiempos de servicio del día, tal como los da la fila de totales de la fuente de ventas.
 *
 * No se calculan aquí: la fuente de ventas los pondera por pedidos y coches, y
 * una media propia sobre las horas puede ser distinta. OEPE es nulo cuando el
 * restaurante no tiene servicio en vehículo.
 */
export interface ServiceTimes {
  kvs: number | null;
  r2p: number | null;
  oepe: number | null;
}

export type Light = "ok" | "warn" | "bad" | "none";
