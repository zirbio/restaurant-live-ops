import { useState } from "react";

import { clearPending, readPending, savePending } from "../lib/pendingSignIn";
import { clockMadrid } from "../lib/tz";
import { supabase } from "../lib/supabase";
import { Logo } from "./Logo";

/**
 * Acceso por código de un solo uso.
 *
 * El correo lleva un código de un solo uso, de la longitud que emita Supabase
 * (en este proyecto, ocho dígitos). El campo NO impone longitud: darla por
 * supuesta cortaba el código y hacía imposible entrar. El código es
 * el único camino: el correo no lleva enlace porque algunos sistemas de seguridad corporativos lo
 * abre solo para escanearlo y, al compartir token con el código, lo gastaba
 * antes de que nadie pudiera usarlo.
 *
 * No hay registro abierto: aunque alguien reciba el código, si no está dado de
 * alta en `app_user_access` no verá ni una fila.
 */
export function Login() {
  // Si quedó un código pendiente, se retoma justo donde estaba: es lo que
  // salva el caso de salir al correo y que el navegador descarte la página.
  const pendiente = readPending();
  const [email, setEmail] = useState(pendiente?.email ?? "");
  const [codigo, setCodigo] = useState("");
  const [paso, setPaso] = useState<"email" | "codigo">(pendiente ? "codigo" : "email");
  const [pedidoA, setPedidoA] = useState<Date | null>(pendiente?.requestedAt ?? null);
  const [ocupado, setOcupado] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function pedirCodigo(e: React.FormEvent) {
    e.preventDefault();
    setOcupado(true);
    setError(null);
    const { error: fallo } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: { emailRedirectTo: window.location.origin },
    });
    setOcupado(false);
    if (fallo) {
      setError(traducir(fallo.message));
      return;
    }
    savePending(email.trim());
    setPedidoA(new Date());
    setPaso("codigo");
  }

  async function reenviar() {
    setOcupado(true);
    setError(null);
    const { error: fallo } = await supabase.auth.signInWithOtp({
      email: email.trim(),
      options: { emailRedirectTo: window.location.origin },
    });
    setOcupado(false);
    if (fallo) {
      setError(traducir(fallo.message));
      return;
    }
    savePending(email.trim());
    setPedidoA(new Date());
    setCodigo("");
  }

  async function entrar(e: React.FormEvent) {
    e.preventDefault();
    setOcupado(true);
    setError(null);
    const { error: fallo } = await supabase.auth.verifyOtp({
      email: email.trim(),
      token: codigo.trim(),
      type: "email",
    });
    setOcupado(false);
    if (fallo) {
      setError(traducir(fallo.message, pedidoA));
      return;
    }
    clearPending();
    // Si va bien, onAuthStateChange en App.tsx se encarga del resto.
  }

  return (
    <div className="login">
      <Logo size={56} />
      <h1 className="login__title">Restaurant Live Ops</h1>
      <p className="login__sub">OPERACIÓN DIARIA</p>

      {paso === "email" ? (
        <form onSubmit={(e) => void pedirCodigo(e)} className="login__form">
          <label htmlFor="email" className="login__label">
            Correo electrónico
          </label>
          <input
            id="email"
            type="email"
            inputMode="email"
            autoComplete="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="login__input"
            placeholder="nombre@example.com"
          />
          <button type="submit" className="login__button" disabled={ocupado}>
            {ocupado ? "Enviando…" : "Enviarme el código"}
          </button>
        </form>
      ) : (
        <form onSubmit={(e) => void entrar(e)} className="login__form">
          <p className="login__ok">
            Código enviado a <strong>{email}</strong>
            {pedidoA && <> a las <strong>{clockMadrid(pedidoA)}</strong></>}.
          </p>
          <p className="login__hint">
            Usa el del <strong>último</strong> correo. Si tienes otros anteriores, ya no valen.
          </p>
          <label htmlFor="codigo" className="login__label">
            Código del correo
          </label>
          <input
            id="codigo"
            type="text"
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern="[0-9]*"
            maxLength={12}
            required
            autoFocus
            value={codigo}
            onChange={(e) => setCodigo(e.target.value.replace(/\D/g, ""))}
            className="login__input login__input--code"
            placeholder="Pégalo o tecléalo"
          />
          <button type="submit" className="login__button" disabled={ocupado || codigo.length < 4}>
            {ocupado ? "Comprobando…" : "Entrar"}
          </button>
          <button type="button" className="login__link" onClick={() => void reenviar()}>
            No me ha llegado · Enviar otro
          </button>
          <button
            type="button"
            className="login__link"
            onClick={() => {
              clearPending();
              setPaso("email");
              setCodigo("");
              setError(null);
            }}
          >
            Usar otro correo
          </button>
        </form>
      )}

      {error && <p className="login__error">{error}</p>}
    </div>
  );
}

/**
 * Los mensajes de Supabase vienen en inglés; los más habituales se traducen.
 *
 * El caso de "código gastado" se explica distinto según el tiempo transcurrido:
 * si acaba de pedirse, casi siempre es que se ha tecleado el código de un
 * correo anterior porque el nuevo todavía no había llegado.
 */
function traducir(mensaje: string, pedidoA?: Date | null): string {
  const m = mensaje.toLowerCase();
  if (m.includes("expired") || m.includes("invalid")) {
    const segundos = pedidoA ? (Date.now() - pedidoA.getTime()) / 1000 : Infinity;
    if (segundos < 120) {
      return (
        "Ese código no vale. Suele pasar por teclear el de un correo anterior: " +
        "espera al correo que acaba de salir y usa ese."
      );
    }
    return "El código ha caducado o ya se usó. Pulsa «Enviar otro».";
  }
  if (m.includes("rate limit") || m.includes("too many")) {
    return "Demasiados intentos seguidos. Espera un minuto y vuelve a probar.";
  }
  return mensaje;
}
