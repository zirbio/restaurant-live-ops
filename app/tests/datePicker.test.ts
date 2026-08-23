import { describe, expect, it } from "vitest";

import { openDatePicker } from "../src/lib/datePicker";

describe("openDatePicker", () => {
  it("abre el calendario nativo del campo", () => {
    let abierto = 0;
    const input = { showPicker: () => void abierto++ };

    expect(openDatePicker(input)).toBe(true);
    expect(abierto).toBe(1);
  });

  it("no falla si el navegador no soporta showPicker", () => {
    // Safari antiguo: el campo sigue funcionando a mano, solo no se abre solo.
    expect(openDatePicker({})).toBe(false);
  });

  it("no propaga el error si el navegador se niega a abrirlo", () => {
    const input = {
      showPicker: () => {
        throw new Error("NotAllowedError");
      },
    };

    expect(openDatePicker(input)).toBe(false);
  });

  it("tolera que no haya campo", () => {
    expect(openDatePicker(null)).toBe(false);
  });
});
