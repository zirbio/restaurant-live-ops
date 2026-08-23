/** Identidad visual neutral compartida por acceso, cabeceras y pie. */
export function Logo({ size = 30 }: { size?: number }) {
  return (
    <img
      src="/icon.svg"
      alt="Restaurant Live Ops"
      width={size}
      height={size}
      className="logo"
      style={{ width: size, height: size }}
    />
  );
}

export function LogoLockup() {
  return (
    <span className="lockup">
      <Logo size={32} />
      <span>Restaurant Live Ops</span>
    </span>
  );
}
