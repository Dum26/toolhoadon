"""Điều kiện báo cáo do người dùng chọn trong ứng dụng desktop."""
from dataclasses import asdict, dataclass
from datetime import date, timedelta


PRESETS = ("Cả năm", "Tháng này", "Tháng trước", "Tùy chọn")


def preset_dates(name: str, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    if name == "Cả năm":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    first_this_month = date(today.year, today.month, 1)
    if name == "Tháng này":
        return first_this_month, today
    if name == "Tháng trước":
        last_previous = first_this_month - timedelta(days=1)
        return date(last_previous.year, last_previous.month, 1), last_previous
    raise ValueError("Hãy chọn một khoảng thời gian hợp lệ.")


@dataclass(frozen=True)
class ReportOptions:
    from_date: date
    to_date: date
    period: str = "Cả năm"
    account_code: str = ""
    warehouse_code: str = ""
    group_code: str = ""
    product_code: str = ""
    lot_code: str = ""
    source_code: str = ""
    include_transfer: bool = False
    by_warehouse: bool = False
    by_lot: bool = False
    by_source: bool = False

    def __post_init__(self):
        if self.from_date > self.to_date:
            raise ValueError("Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.")
        if self.from_date.year != self.to_date.year:
            raise ValueError("Báo cáo VAOnline chỉ hỗ trợ chọn ngày trong cùng một năm kế toán.")
        if self.period not in PRESETS:
            raise ValueError("Khoảng thời gian không hợp lệ.")

    @property
    def label(self):
        return f"{self.from_date:%d/%m/%Y} – {self.to_date:%d/%m/%Y}"

    def to_dict(self):
        data = asdict(self)
        data["from_date"] = self.from_date.isoformat()
        data["to_date"] = self.to_date.isoformat()
        return data

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict):
            return cls.default()
        try:
            allowed = cls.__dataclass_fields__
            values = {key: value for key, value in data.items() if key in allowed}
            values["from_date"] = date.fromisoformat(values["from_date"])
            values["to_date"] = date.fromisoformat(values["to_date"])
            return cls(**values)
        except (KeyError, TypeError, ValueError):
            return cls.default()

    @classmethod
    def default(cls):
        start, end = preset_dates("Cả năm")
        return cls(start, end)
