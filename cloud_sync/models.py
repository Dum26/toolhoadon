from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class InventoryItem:
    ma_hang: str
    ten_hang: str
    ton_kho: Decimal
