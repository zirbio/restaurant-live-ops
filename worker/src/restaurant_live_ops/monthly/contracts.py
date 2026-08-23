"""Contrato opcional para integrar datos mensuales de una fuente externa."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class MonthlySnapshot:
    restaurant_id: str
    year: int
    month: int
    covers_through: date
    net_sales: Decimal
    labor_cost: Decimal

    @property
    def period(self) -> str:
        return f"{self.year:04d}-{self.month:02d}"


class MonthlySource(Protocol):
    def read_month(self, *, year: int, month: int) -> Sequence[MonthlySnapshot]: ...
