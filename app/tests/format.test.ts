import { describe, expect, it } from "vitest";

import {
  DASH,
  dec,
  eur,
  fechaCorta,
  num,
  pct,
  pctPlain,
  roundsToZero,
  secs,
  signedDec,
  signedEur,
  signedNum,
  staffing,
} from "../src/lib/format";

describe("formato español", () => {
  it("usa punto de millar y coma decimal", () => {
    expect(eur(1234.56)).toBe("1.234,56 €");
    expect(eur(1234567.89)).toBe("1.234.567,89 €");
  });

  it("no abrevia nunca a k€ ni M€", () => {
    expect(eur(1234567.89)).not.toMatch(/k|M/);
  });

  it("redondea a euros enteros si se piden sin decimales", () => {
    expect(eur(1234.56, { decimales: 0 })).toBe("1.235 €");
  });

  it("marca el signo de las desviaciones en euros", () => {
    expect(signedEur(120.5)).toBe("+120,50 €");
    expect(signedEur(-120.5)).toBe("−120,50 €");
  });

  it("marca el signo de las desviaciones en unidades", () => {
    expect(signedNum(15)).toBe("+15");
    expect(signedNum(-15)).toBe("−15");
    expect(signedNum(0)).toBe("+0");
  });

  it("da los porcentajes con coma y signo", () => {
    expect(pct(12.34)).toBe("+12,3 %");
    expect(pct(-4.5)).toBe("−4,5 %");
  });

  it("da los tiempos en segundos enteros", () => {
    expect(secs(116)).toBe('116"');
    expect(secs(116.7)).toBe('117"');
  });

  it("agrupa los millares también en los números sueltos", () => {
    expect(num(1085)).toBe("1.085");
  });

  it("devuelve raya para lo que no existe, nunca cero", () => {
    expect(eur(null)).toBe(DASH);
    expect(num(null)).toBe(DASH);
    expect(secs(null)).toBe(DASH);
    expect(pct(null)).toBe(DASH);
  });

  it("el porcentaje que no es desviación va sin signo", () => {
    // Un 27,5 % de mano de obra no va "hacia arriba": con signo se leería como
    // un crecimiento, que es otra cosa.
    expect(pctPlain(27.53)).toBe("27,5 %");
    expect(pctPlain(-3.2)).toBe("−3,2 %");
    expect(pctPlain(null)).toBe(DASH);
    expect(signedEur(null)).toBe(DASH);
    expect(signedNum(null)).toBe(DASH);
    expect(DASH).not.toBe("0");
  });

  it("distingue un cero real de un dato ausente", () => {
    expect(eur(0)).toBe("0,00 €");
    expect(eur(null)).toBe(DASH);
  });
});

describe("personal fichado y asignado", () => {
  it("muestra los dos números separados por barra", () => {
    expect(staffing(8, 9)).toBe("8/9");
  });

  it("marca la cifra corregida cuando hay un fichaje ignorado", () => {
    // Enseña 2 de 3 porque a alguien no le cerraron el marcaje: sin la marca,
    // esa fila parece una ausencia de verdad y no lo es.
    expect(staffing(2, 3, 1)).toBe("2/3\u00A0⚠");
  });

  it("separa la marca con un espacio duro, que no es punto de corte", () => {
    // Con un espacio normal, la celda estrecha de la tabla partía la cifra y
    // su marca en dos líneas, y la fila crecía justo donde estrena el aviso.
    expect(staffing(12, 14, 1)).not.toContain(" ");
    expect(staffing(12, 14, 1)).toBe("12/14\u00A0⚠");
  });

  it("no marca nada cuando no se ha corregido ninguna hora", () => {
    expect(staffing(2, 3, 0)).toBe("2/3");
    expect(staffing(2, 3, null)).toBe("2/3");
  });

  it("deja raya en los fichados cuando la hora aún no ha empezado", () => {
    expect(staffing(null, 12)).toBe(`${DASH}/12`);
  });

  it("distingue no haber nadie dentro de no tener el dato", () => {
    // Un 0 es una afirmación: no hay nadie. La raya es la ausencia de dato.
    expect(staffing(0, 5)).toBe("0/5");
    expect(staffing(null, null)).toBe(DASH);
  });

  it("sin cuadrante no hay nada que comparar", () => {
    expect(staffing(4, null)).toBe(DASH);
  });
});

describe("decimales de la tabla de productividad", () => {
  it("da un decimal con coma y sin unidad: la unidad la pone la cabecera", () => {
    expect(dec(68.04)).toBe("68,0");
    expect(dec(1234.56)).toBe("1.234,6");
    expect(dec(null)).toBe(DASH);
  });

  it("con signo para las desviaciones, y menos tipográfico", () => {
    expect(signedDec(7.11)).toBe("+7,1");
    expect(signedDec(-2.705)).toBe("−2,7");
  });

  it("una desviación que redondea a cero sale sin signo", () => {
    // Mismo criterio que `pct`: a un decimal, tres centésimas es estar en el
    // objetivo, y un "−0,0" parece un despiste de la pantalla.
    expect(signedDec(-0.03)).toBe("0,0");
    expect(signedDec(0)).toBe("0,0");
  });
});

describe("redondeo a cero", () => {
  it("detecta lo que se IMPRIME como cero, no lo que vale", () => {
    // El color de una desviación tiene que decir lo mismo que su cifra. Con
    // +0,024 pp la pantalla escribe "0,0" —estás en el objetivo— y pintarlo de
    // ámbar avisaría de un exceso que la cifra ya no enseña.
    expect(roundsToZero(0.024)).toBe(true);
    expect(roundsToZero(-0.04)).toBe(true);
    expect(roundsToZero(0)).toBe(true);
    expect(roundsToZero(0.05)).toBe(false);
    expect(roundsToZero(-1.2)).toBe(false);
    expect(roundsToZero(null)).toBe(false);
  });
});

describe("fechaCorta: cuándo se calculó un dato importado", () => {
  it("rellena con cero el día y el mes de un solo dígito", () => {
    // 08:03 UTC de un 5 de enero (invierno en Madrid, UTC+1) son las 09:03 del
    // día 05 del mes 01. Sin el relleno a mano esto sale "5/1 9:03": es lo
    // que devolvía `.format()` directo en este mismo runtime — comprobado en
    // Node 26 que `resolvedOptions()` ignora `day`/`month: "2-digit"` en este
    // combo de campos y cae a "numeric" — y es justo lo que este formateador
    // existe para evitar.
    expect(fechaCorta("2026-01-05T08:03:00Z")).toBe("05/01 09:03");
  });

  it("Europe/Madrid explícito: verano (UTC+2), partiendo de una marca UTC", () => {
    // Una marca UTC se presenta convertida a Europe/Madrid, con independencia
    // del huso del dispositivo que ejecute la app.
    expect(fechaCorta("2026-08-11T13:55:17.427678+00:00")).toBe("11/08 15:55");
  });

  it("Europe/Madrid explícito: invierno (UTC+1), partiendo de una marca UTC", () => {
    // 10:00 UTC de un 3 de diciembre tienen que llegar como las 11:00 de
    // Madrid, un huso distinto del caso de verano: sin `timeZone` explícito,
    // el móvil de un gerente en otro huso horario enseñaría otra hora.
    expect(fechaCorta("2026-12-03T10:00:00Z")).toBe("03/12 11:00");
  });
});
