"""Đọc báo cáo tồn kho qua giao diện VAOnline, không dùng API nội bộ của website."""
import argparse
import json
import logging
import re
import sys
import time
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

from playwright.sync_api import TimeoutError as PlaywrightTimeout, sync_playwright

from config import DEBUG_DIR, STATE_PATH, TIMEOUT_MS, VA_URL
from database import save_inventory
from models import InventoryItem
from report_options import ReportOptions
from sync_lock import SyncBusy, process_lock

logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s")
log = logging.getLogger("va_stock")


class ScrapeError(RuntimeError):
    pass


class SessionExpired(ScrapeError):
    pass


def norm(value):
    value = unicodedata.normalize("NFD", str(value or "").lower())
    return re.sub(r"\s+", " ", "".join(c for c in value if unicodedata.category(c) != "Mn").replace("đ", "d")).strip()


def parse_quantity(raw):
    value = str(raw).strip().replace("\u00a0", "").replace(" ", "").replace("−", "-")
    if not value:
        raise ValueError("Ô tồn kho rỗng")
    if not re.fullmatch(r"[+-]?[\d.,]+", value):
        raise ValueError(f"Số lượng không hợp lệ: {raw!r}")
    if "," in value and "." in value:
        decimal_mark = "," if value.rfind(",") > value.rfind(".") else "."
        group_mark = "." if decimal_mark == "," else ","
        value = value.replace(group_mark, "").replace(decimal_mark, ".")
    elif "," in value or "." in value:
        mark = "," if "," in value else "."
        pieces = value.lstrip("+-").split(mark)
        if len(pieces) > 2 or (len(pieces) == 2 and len(pieces[1]) == 3 and len(pieces[0]) <= 3 and pieces[0] != "0"):
            value = value.replace(mark, "")
        else:
            value = value.replace(mark, ".")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Số lượng không hợp lệ: {raw!r}") from exc


def artifact(page, label="error", step="Không xác định", error=""):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = DEBUG_DIR / f"{label}_{stamp}"
    try:
        page.screenshot(path=str(stem.with_suffix(".png")), full_page=True, timeout=10000)
    except Exception as exc:
        log.warning("Không chụp được ảnh: %s", exc)
    try:
        stem.with_suffix(".html").write_text(page.content(), encoding="utf-8")
    except Exception as exc:
        log.warning("Không lưu được HTML: %s", exc)
    if label == "error":
        for extension in (".png", ".html"):
            source = stem.with_suffix(extension)
            if source.exists():
                (DEBUG_DIR / f"error{extension}").write_bytes(source.read_bytes())
        try:
            hints = page.evaluate("""() => [...document.querySelectorAll('button,a,[role="button"],[role="menuitem"]')]
                .filter(e => e.getClientRects().length).map(e => (e.innerText || e.getAttribute('aria-label') || '').trim())
                .filter(Boolean).slice(0, 100)""")
        except Exception:
            hints = []
        (DEBUG_DIR / "log.txt").write_text(
            f"Thời điểm: {datetime.now().isoformat()}\nURL: {page.url}\nBước: {step}\nLỗi: {error}\nText/nút: {hints}\n",
            encoding="utf-8")
    log.info("URL: %s | Debug: %s.png, %s.html", page.url, stem, stem)
    return stem


def page_has_report_menu(page):
    try:
        return page.get_by_text(re.compile(r"Báo\s*cáo", re.I)).first.is_visible(timeout=3000)
    except Exception:
        return False


def wait_for_report_menu(page, timeout_ms=20000):
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        if page_has_report_menu(page):
            return True
        time.sleep(0.4)
    return False


def open_home(page):
    log.info("[1/6] Mở VAOnline")
    page.goto(VA_URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
    page.wait_for_timeout(1500)


def login(browser, progress=None):
    context = browser.new_context()
    page = context.new_page()
    open_home(page)
    if progress:
        progress("Trình duyệt đã mở. Hãy đăng nhập VAOnline; ứng dụng sẽ tự nhận biết khi hoàn tất.")
    else:
        print("Hãy tự đăng nhập trong trình duyệt. Chương trình sẽ tự nhận biết khi thấy menu Báo cáo.")
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline and not page.is_closed():
        if page_has_report_menu(page):
            break
        time.sleep(1)
    if not page_has_report_menu(page):
        if not page.is_closed():
            artifact(page, "login_check")
        context.close()
        raise ScrapeError("Chưa xác nhận được đăng nhập (không thấy menu Báo cáo). Xem debug/login_check_*.html.")
    context.storage_state(path=str(STATE_PATH))
    log.info("Đã lưu phiên đăng nhập: %s", STATE_PATH)
    context.close()


def click_named(page, names, label, required=True):
    for name in names:
        pattern = re.compile(name, re.I)
        candidates = [
            page.get_by_role("button", name=pattern),
            page.get_by_role("link", name=pattern),
            page.get_by_role("menuitem", name=pattern),
            page.get_by_text(pattern),
        ]
        for loc in candidates:
            try:
                count = min(loc.count(), 5)
                for index in range(count):
                    item = loc.nth(index)
                    if item.is_visible() and item.is_enabled():
                        item.click(timeout=5000)
                        return True
            except Exception:
                continue
    if required:
        artifact(page, step=label, error=f"Không tìm thấy selector: {names}")
        raise ScrapeError(f"Không tìm thấy hoặc không click được: {label}. Selector đã thử: {names}")
    return False


def report_field(page, label):
    modal = page.locator(".webix_window:visible").last
    name = modal.locator("label.webix_inp_label").filter(has_text=re.compile(rf"^\s*{re.escape(label)}\s*$", re.I))
    field = name.locator("..").locator("input").first
    if not field.count():
        artifact(page, step=f"Điều kiện {label}", error="Không thấy ô nhập")
        raise ScrapeError(f"Không tìm thấy ô {label} trong điều kiện báo cáo.")
    return field


def select_code_filter(page, label, code):
    code = code.strip()
    if not code:
        return
    field = report_field(page, label)
    field.fill(code)
    page.wait_for_timeout(450)
    matches = page.get_by_role("option", name=re.compile(rf"^\s*{re.escape(code)}(?:\b|\s|[-–])", re.I))
    for index in range(min(matches.count(), 10)):
        option = matches.nth(index)
        if option.is_visible():
            option.click()
            return
    artifact(page, step=f"Chọn {label}", error=f"Không tìm thấy mã {code} trong gợi ý")
    raise ScrapeError(f"Không tìm thấy {label} {code} trong VAOnline. Hãy kiểm tra mã đã nhập.")


def select_accounting_year(page, year):
    picker = page.locator('[view_id="cbNamLv"] [role="combobox"]')
    if not picker.count():
        return
    current = picker.first.inner_text().strip()
    if current == str(year):
        return
    picker.first.click()
    target = page.get_by_role("option", name=str(year), exact=True)
    if not target.count():
        raise ScrapeError(f"Năm {year} chưa có trong VAOnline.")
    target.first.click()
    page.wait_for_timeout(1000)


def navigate_report(page, progress=None, report_options=None):
    report_options = report_options or ReportOptions.default()
    select_accounting_year(page, report_options.from_date.year)
    log.info("[3/6] Mở Báo cáo")
    if progress:
        progress("Đang mở báo cáo...")
    click_named(page, [r"^\s*Báo\s*cáo\s*$", r"Báo\s*cáo"], "Báo cáo")
    page.wait_for_timeout(500)
    log.info("[4/6] Mở Nhập - xuất - tồn hàng hóa")
    click_named(page, [r"Nhập\s*[-–]\s*xuất\s*[-–]\s*tồn\s*hàng\s*hóa", r"Nhập\s*[-–]\s*xuất\s*[-–]\s*tồn"], "Nhập - xuất - tồn hàng hóa")
    report_page = page
    deadline = time.monotonic() + TIMEOUT_MS / 1000
    while time.monotonic() < deadline:
        match = next((p for p in reversed(page.context.pages)
                      if not p.is_closed() and p.get_by_text(re.compile(r"Nhận\s*\(F10\)", re.I)).count()
                      and p.get_by_text(re.compile(r"Nhận\s*\(F10\)", re.I)).first.is_visible()), None)
        if match:
            report_page = match
            break
        time.sleep(0.4)
    else:
        artifact(page, step="Mở điều kiện báo cáo", error="Không thấy Nhận (F10)")
        raise ScrapeError("Không mở được cửa sổ điều kiện báo cáo Nhập - xuất - tồn.")
    period = report_page.get_by_role("combobox", name="Thời gian")
    if period.count() and period.first.is_visible():
        period.first.click()
        option = report_page.get_by_role("option", name=re.compile(r"^Cả\s*năm$", re.I))
        if not option.count():
            artifact(report_page, step="Chọn thời gian", error="Không thấy lựa chọn Cả năm")
            raise ScrapeError("Không chọn được thời gian Cả năm cho báo cáo.")
        option.first.click()
        log.info("Đã chọn thời gian Cả năm cho báo cáo")
    for label, value in (("Từ ngày", report_options.from_date.strftime("%d/%m/%Y")),
                         ("Đến ngày", report_options.to_date.strftime("%d/%m/%Y"))):
        field = report_field(report_page, label)
        field.fill(value)
        field.press("Tab")
        if field.input_value() != value:
            artifact(report_page, step=f"Chọn {label}", error=f"Ngày mong muốn: {value}")
            raise ScrapeError(f"VAOnline không nhận ngày {value} ở ô {label}.")
    for label, code in (("Mã tài khoản", report_options.account_code),
                        ("Mã kho", report_options.warehouse_code),
                        ("Mã nhóm HV", report_options.group_code),
                        ("Mã lô hàng", report_options.lot_code),
                        ("Mã nguồn hàng", report_options.source_code)):
        select_code_filter(report_page, label, code)
    if report_options.product_code:
        field = report_field(report_page, "Mã hàng")
        field.fill(report_options.product_code)
        field.press("Tab")
    for label, checked in (("Điều chuyển nội bộ", report_options.include_transfer),
                           ("Theo kho", report_options.by_warehouse),
                           ("Theo lô", report_options.by_lot),
                           ("Theo nguồn hàng", report_options.by_source)):
        checkbox = report_page.get_by_role("checkbox", name=label)
        if checkbox.count():
            checkbox.first.set_checked(checked)
    log.info("Điều kiện báo cáo: %s", report_options.label)
    if progress:
        progress("Đang nhận báo cáo...")
    click_named(report_page, [r"Nhận\s*\(F10\)", r"^\s*Nhận\s*$"], "Nhận (F10)")
    report_page.wait_for_timeout(500)
    return report_page


# Chỉ lấy cấu trúc DOM đang hiển thị. Không gọi endpoint riêng hay dùng F6.
SNAPSHOT_JS = r"""() => {
  const clean = x => (x || '').replace(/\s+/g, ' ').trim();
  const visible = e => !!(e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
  const webix = [...document.querySelectorAll('.webix_dtable[role="grid"]')].filter(visible);
  if (webix.length) return webix.map((grid, index) => {
    const headerCells = [...grid.querySelectorAll('.webix_ss_header tr[section="header"] td[column]')];
    const width = Math.max(Number(grid.getAttribute('aria-colcount') || 0),
      ...headerCells.map(e => Number(e.getAttribute('column')) + 1));
    const parts = Array.from({length: width}, () => []);
    headerCells.forEach(cell => {
      const col = Number(cell.getAttribute('column'));
      const value = clean(cell.innerText);
      if (value && col >= 0 && col < width) parts[col].push(value);
    });
    const headers = parts.map(values => values.join(' > '));
    const byRow = new Map();
    grid.querySelectorAll('.webix_ss_body .webix_column[column]').forEach(column => {
      const col = Number(column.getAttribute('column'));
      [...column.querySelectorAll(':scope > [role="gridcell"][aria-rowindex]')].forEach(cell => {
        const rowIndex = Number(cell.getAttribute('aria-rowindex'));
        if (!byRow.has(rowIndex)) byRow.set(rowIndex, {cells: [], links: []});
        const row = byRow.get(rowIndex);
        row.cells[col] = clean(cell.innerText);
        row.links[col] = !!cell.querySelector('a');
      });
    });
    const rows = [...byRow].sort((a,b) => a[0] - b[0]).map(([rowIndex,row]) => ({...row, rowIndex}));
    return {kind:'webix', index, headers, rows, sample: clean(grid.innerText).slice(0,400)};
  });
  const tables = [...document.querySelectorAll('table, [role="grid"], [role="table"]')].filter(visible);
  return tables.map((table, index) => {
    const headerRows = table.matches('table')
      ? [...table.querySelectorAll('thead tr')]
      : [...table.querySelectorAll('[role="row"]')].filter(r => r.querySelector('[role="columnheader"]'));
    if (!headerRows.length && table.matches('table')) {
      const first = table.querySelector('tr');
      if (first && first.querySelector('th')) headerRows.push(first);
    }
    const grid = [];
    headerRows.forEach((tr, r) => {
      grid[r] ||= [];
      const cells = [...tr.children].filter(e => e.matches('th,td,[role="columnheader"]'));
      let c = 0;
      cells.forEach(cell => {
        while (grid[r][c] !== undefined) c++;
        const cs = Math.max(1, Number(cell.getAttribute('colspan') || 1));
        const rs = Math.max(1, Number(cell.getAttribute('rowspan') || 1));
        for (let rr = r; rr < r + rs; rr++) {
          grid[rr] ||= [];
          for (let cc = c; cc < c + cs; cc++) grid[rr][cc] = clean(cell.innerText);
        }
        c += cs;
      });
    });
    const width = Math.max(0, ...grid.map(r => r.length));
    const headers = Array.from({length: width}, (_, c) => {
      const parts = grid.map(row => row[c]).filter(Boolean);
      return parts.filter((v, i) => i === 0 || v !== parts[i - 1]).join(' > ');
    });
    const bodyRows = table.matches('table')
      ? [...table.querySelectorAll('tbody tr')]
      : [...table.querySelectorAll('[role="row"]')].filter(r => !r.querySelector('[role="columnheader"]'));
    const rows = bodyRows.filter(visible).map(tr => {
      const cells = [...tr.children].filter(e => e.matches('td,th,[role="cell"],[role="gridcell"]'));
      return {cells: cells.map(e => clean(e.innerText)), links: cells.map(e => !!e.querySelector('a'))};
    });
    return {index, headers, rows, sample: clean(table.innerText).slice(0, 400)};
  });
}"""


def columns(headers):
    normalized = [norm(h) for h in headers]
    code = next((i for i, h in enumerate(normalized) if "ma hang" in h), None)
    name = next((i for i, h in enumerate(normalized) if "ten hang" in h), None)
    ending = next((i for i, h in enumerate(normalized)
                   if ("cuoi ky" in h and re.search(r"(?:^|[ >])ton(?:$|[ >])", h)
                       and "gia tri" not in h and "du cuoi" not in h)), None)
    if None in (code, name, ending) or len({code, name, ending}) != 3:
        return None
    return code, name, ending


def report_snapshot(page, diagnostic=True):
    tables = page.evaluate(SNAPSHOT_JS)
    matches = [(t, columns(t["headers"])) for t in tables]
    matches = [(t, col) for t, col in matches if col]
    if len(matches) != 1:
        detail = [(t["index"], t["headers"]) for t in tables]
        if diagnostic:
            artifact(page, step="Xác định cột báo cáo", error=f"Headers: {detail}")
        raise ScrapeError(f"Không xác định duy nhất bảng với cột Cuối kỳ > Tồn. Headers: {detail}")
    return matches[0]


def wait_for_report(page):
    deadline = time.monotonic() + TIMEOUT_MS / 1000
    last_error = None
    while time.monotonic() < deadline:
        try:
            table, _ = report_snapshot(page, diagnostic=False)
            if table["rows"]:
                return
        except ScrapeError as exc:
            last_error = exc
        page.wait_for_timeout(400)
    artifact(page, step="Tải bảng báo cáo", error=str(last_error or "Không có dòng dữ liệu"))
    raise ScrapeError(f"Báo cáo chưa tải được bảng và dòng dữ liệu trong {TIMEOUT_MS // 1000} giây. {last_error or ''}")


def wait_for_report_pages(context):
    deadline = time.monotonic() + TIMEOUT_MS / 1000
    last_error = None
    while time.monotonic() < deadline:
        for candidate in reversed(context.pages):
            if candidate.is_closed():
                continue
            site_error = candidate.get_by_text("The given key was not present in the dictionary.")
            if site_error.count() and site_error.first.is_visible():
                artifact(candidate, step="Nhận báo cáo", error="VAOnline: The given key was not present in the dictionary")
                raise ScrapeError("VAOnline báo lỗi khi tạo báo cáo. Hãy kiểm tra điều kiện Thời gian và thử lại.")
            try:
                table, _ = report_snapshot(candidate, diagnostic=False)
                if table["rows"]:
                    return candidate
            except ScrapeError as exc:
                last_error = exc
        time.sleep(0.4)
    live = next((candidate for candidate in reversed(context.pages) if not candidate.is_closed()), None)
    if live:
        artifact(live, step="Tải bảng báo cáo", error=str(last_error or "Không có dòng dữ liệu"))
    raise ScrapeError(f"Không đọc được bảng báo cáo trong {TIMEOUT_MS // 1000} giây. {last_error or ''}")


def scroll_report(page, index, kind="table"):
    if kind == "webix":
        grid = page.locator('.webix_dtable[role="grid"]:visible').nth(index)
        before = grid.locator('.webix_ss_body .webix_column[column="0"] [aria-rowindex]').first.get_attribute("aria-rowindex")
        grid.hover()
        page.mouse.wheel(0, 450)
        page.wait_for_timeout(250)
        after = grid.locator('.webix_ss_body .webix_column[column="0"] [aria-rowindex]').first.get_attribute("aria-rowindex")
        return before != after
    return page.evaluate("""index => {
      const table = [...document.querySelectorAll('table, [role="grid"], [role="table"]')]
        .filter(e => e.getClientRects().length)[index];
      if (!table) return false;
      let e = table;
      while (e && e !== document.body) {
        if (e.scrollHeight > e.clientHeight + 8 && getComputedStyle(e).overflowY !== 'hidden') {
          const before = e.scrollTop;
          e.scrollTop = Math.min(e.scrollHeight, before + Math.max(e.clientHeight * .85, 300));
          return e.scrollTop > before;
        }
        e = e.parentElement;
      }
      const before = window.scrollY;
      window.scrollBy(0, window.innerHeight * .85);
      return window.scrollY > before;
    }""", index)


def next_page(page, old_rows):
    pager_next = page.locator('[view_id="pagerA"] button[webix_p_id="next"]')
    if pager_next.count():
        button = pager_next.first
        classes = button.get_attribute("class") or ""
        if (not button.is_visible() or not button.is_enabled()
                or button.get_attribute("aria-disabled") == "true"
                or re.search(r"disabled|webix_pager_item_disabled", classes, re.I)):
            return False
        selected = page.locator('[view_id="pagerA"] button.webix_pager_item_selected').first.inner_text()
        button.click(timeout=5000)
        deadline = time.monotonic() + 5000 / 1000
        while time.monotonic() < deadline:
            page.wait_for_timeout(400)
            table, _ = report_snapshot(page, diagnostic=False)
            if table["rows"] and table["rows"] != old_rows:
                return True
        current = page.locator('[view_id="pagerA"] button.webix_pager_item_selected').first.inner_text()
        log.info("Không có trang báo cáo mới (trang trước: %s, hiện tại: %s)", selected.strip(), current.strip())
        return False
    for label in [r"^\s*Trang sau\s*$", r"^\s*Tiếp\s*$", r"^\s*Next(?:\s+page)?\s*$", r"^\s*[>›]\s*$"]:
        candidates = [page.get_by_role(role, name=re.compile(label, re.I))
                      for role in ("button", "link")]
        candidates.append(page.get_by_text(re.compile(label, re.I), exact=True))
        for loc in candidates:
            for i in range(min(loc.count(), 5)):
                candidate = loc.nth(i)
                try:
                    classes = candidate.get_attribute("class") or ""
                    if (candidate.is_visible() and candidate.is_enabled()
                            and candidate.get_attribute("aria-disabled") != "true"
                            and not re.search(r"disabled", classes, re.I)):
                        candidate.click(timeout=5000)
                        for _ in range(12):
                            page.wait_for_timeout(350)
                            try:
                                table, _ = report_snapshot(page, diagnostic=False)
                                if table["rows"] and table["rows"] != old_rows:
                                    return True
                            except ScrapeError:
                                continue
                        return False
                except Exception:
                    continue
    return False


def read_report(page, progress=None, aggregate_duplicates=False):
    log.info("[6/6] Đang đọc tồn kho")
    items = {}
    seen_rows = set()
    prior_signature = None
    for page_no in range(1, 501):
        if progress:
            progress(f"Đang đọc trang {page_no}...")
        stagnant = 0
        last_rows = []
        for scroll_no in range(1001):
            table, (code, name, ending) = report_snapshot(page)
            last_rows = table["rows"]
            before = len(items)
            for row in table["rows"]:
                row_id = (page_no, row["rowIndex"]) if table.get("kind") == "webix" else None
                if row_id is not None and row_id in seen_rows:
                    continue
                cells = row["cells"]
                if len(cells) <= max(code, name, ending):
                    continue
                sku, title, raw = cells[code].strip(), cells[name].strip(), cells[ending].strip()
                normalized_sku = norm(sku).replace(" ", "")
                if (not sku or not title or normalized_sku in
                        ("mahang", "tongcong", "tong", "hanghoa", "hopquatet", "hopqua")):
                    continue
                has_link = row["links"][code] if code < len(row["links"]) else False
                if not has_link and not re.fullmatch(r"[A-Za-z]{1,12}[A-Za-z0-9._-]*\d[A-Za-z0-9._-]*", sku):
                    continue
                try:
                    amount = parse_quantity(raw)
                except ValueError as exc:
                    artifact(page, step=f"Đọc trang {page_no}", error=f"Mã {sku}: {exc}")
                    raise ScrapeError(f"Không đọc được tồn kho của mã {sku}: {exc}") from exc
                current = InventoryItem(sku, title, amount)
                if sku in items and items[sku] != current:
                    previous = items[sku]
                    if aggregate_duplicates and row_id is not None and previous.ten_hang == title:
                        current = InventoryItem(sku, title, previous.ton_kho + amount)
                    else:
                        artifact(page)
                        raise ScrapeError(f"Mã {sku} có dữ liệu mâu thuẫn giữa các dòng/trang")
                elif sku in items and aggregate_duplicates and row_id is not None:
                    previous = items[sku]
                    current = InventoryItem(sku, title, previous.ton_kho + amount)
                items[sku] = current
                if row_id is not None:
                    seen_rows.add(row_id)
            moved = scroll_report(page, table["index"], table.get("kind", "table"))
            page.wait_for_timeout(350)
            stagnant = stagnant + 1 if len(items) == before else 0
            if stagnant >= 4 and not moved:
                break
        else:
            artifact(page)
            raise ScrapeError("Vượt giới hạn cuộn bảng; không thể xác nhận đã đọc hết.")
        signature = (len(items), len(seen_rows), tuple(sorted(items)[-5:]))
        if progress:
            progress(f"Đã lấy {len(items)} sản phẩm...")
        if not next_page(page, last_rows):
            break
        if signature == prior_signature:
            artifact(page)
            raise ScrapeError("Phân trang không tiến tới dữ liệu mới.")
        prior_signature = signature
        log.info("Đã đọc trang %s, tổng %s mặt hàng", page_no, len(items))
    else:
        artifact(page)
        raise ScrapeError("Vượt giới hạn 500 trang báo cáo.")
    if not items:
        artifact(page)
        raise ScrapeError("Không thấy mặt hàng hợp lệ; database chưa được cập nhật.")
    log.info("Đã tìm thấy %s mặt hàng", len(items))
    return list(items.values())


def inspect(page):
    try:
        page = navigate_report(page)
    except ScrapeError as exc:
        log.warning("Chưa tới được báo cáo: %s", exc)
    stem = artifact(page, "inspect")
    info = page.evaluate("""() => ({
      url: location.href,
      buttons: [...document.querySelectorAll('button,[role="button"]')].filter(e => e.getClientRects().length).map(e => e.innerText.trim() || e.getAttribute('aria-label')).slice(0, 100),
      links: [...document.querySelectorAll('a')].filter(e => e.getClientRects().length).map(e => e.innerText.trim()).filter(Boolean).slice(0, 100),
      texts: [...document.querySelectorAll('nav, [role="menuitem"], [role="tab"], h1, h2, h3, label')].filter(e => e.getClientRects().length).map(e => e.innerText.trim()).filter(Boolean).slice(0, 150),
      headers: [...document.querySelectorAll('th,[role="columnheader"]')].filter(e => e.getClientRects().length).map(e => e.innerText.trim()).slice(0, 200),
      tables: document.querySelectorAll('table,[role="grid"],[role="table"]').length
    })""")
    info["table_snapshots"] = page.evaluate(SNAPSHOT_JS)
    stem.with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in info.items() if k != "table_snapshots"}, ensure_ascii=False, indent=2))
    print(f"Đã lưu {stem}.png, {stem}.html, {stem}.json")


def run(mode, progress=None, report_options=None):
    def emit(message):
        log.info("%s", message)
        if progress:
            progress(message)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=(mode == "sync"))
        try:
            if mode == "login":
                login(browser, progress)
                return None
            if not STATE_PATH.exists():
                raise SessionExpired("Chưa kết nối VAOnline. Hãy bấm Kết nối VAOnline để đăng nhập.")
            context = browser.new_context(storage_state=str(STATE_PATH))
            page = context.new_page()
            try:
                emit("Đang kết nối VAOnline...")
                open_home(page)
                log.info("[2/6] Kiểm tra đăng nhập")
                if not wait_for_report_menu(page):
                    raise SessionExpired("Phiên đăng nhập VAOnline đã hết hạn.")
                log.info("Đã đăng nhập")
                if mode == "inspect":
                    inspect(page)
                    return None
                active_options = report_options or ReportOptions.default()
                navigate_report(page, progress, active_options)
                log.info("[5/6] Tải dữ liệu")
                emit("Đang tải tồn kho...")
                page = wait_for_report_pages(context)
                grouped = active_options.by_warehouse or active_options.by_lot or active_options.by_source
                items = read_report(page, progress, aggregate_duplicates=grouped)
                emit("Đang lưu dữ liệu...")
                count = save_inventory(items, filters=active_options.to_dict())
                log.info("Đã cập nhật database: %s mặt hàng", count)
                emit("Hoàn tất ✓")
                return count
            finally:
                context.close()
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description="Đăng nhập, kiểm tra DOM và đồng bộ tồn kho VAOnline")
    modes = parser.add_mutually_exclusive_group(required=True)
    modes.add_argument("--login", action="store_true")
    modes.add_argument("--inspect", action="store_true")
    modes.add_argument("--sync", action="store_true")
    args = parser.parse_args()
    mode = "login" if args.login else "inspect" if args.inspect else "sync"
    try:
        if mode == "sync":
            with process_lock():
                return run_cli_sync()
        run(mode)
    except SessionExpired as exc:
        log.error("%s", exc)
        if mode == "inspect":
            try:
                log.info("Mở trình duyệt để đăng nhập lại")
                run("login")
                run(mode)
                return 0
            except (ScrapeError, PlaywrightTimeout, OSError, EOFError) as retry_exc:
                log.error("%s", retry_exc)
        return 2
    except (ScrapeError, PlaywrightTimeout, OSError, SyncBusy) as exc:
        log.error("%s", exc)
        return 1
    return 0


def run_cli_sync():
    try:
        run("sync")
    except SessionExpired as exc:
        log.error("%s", exc)
        log.info("Mở trình duyệt để đăng nhập lại")
        run("login")
        run("sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
