"""Punto de entrada del gate de neutralidad del repositorio."""

import sys
from pathlib import Path


def main() -> int:
    worker_source = Path(__file__).resolve().parents[1] / "worker" / "src"
    sys.path.insert(0, str(worker_source))
    from restaurant_live_ops.repository_hygiene import main as run_hygiene

    return run_hygiene()


if __name__ == "__main__":
    raise SystemExit(main())
