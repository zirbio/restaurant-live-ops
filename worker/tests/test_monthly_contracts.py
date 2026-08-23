from datetime import date
from decimal import Decimal

from restaurant_live_ops.monthly.contracts import MonthlySnapshot


def test_monthly_snapshot_exposes_period() -> None:
    snapshot = MonthlySnapshot(
        restaurant_id="R001",
        year=2026,
        month=1,
        covers_through=date(2026, 1, 31),
        net_sales=Decimal("10000.00"),
        labor_cost=Decimal("2500.00"),
    )
    assert snapshot.period == "2026-01"
