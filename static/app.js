const $ = selector => document.querySelector(selector);
const rowsEl = $('#rows');
const query = $('#query');
const statusEl = $('#status');
const refreshEl = $('#refresh');
const dialog = $('#filter-dialog');
const number = new Intl.NumberFormat('vi-VN');
let inventory = [];
let stockFilter = 'all';
let sortColumn = 'ma_hang';
let sortDescending = false;
let refreshing = false;
let refreshTimer;
let preferences = {interval: '60', theme: 'light'};
try { preferences = {...preferences, ...JSON.parse(localStorage.getItem('va-stock-preferences') || '{}')}; } catch {}
if (!['0', '60', '300', '900'].includes(preferences.interval)) preferences.interval = '60';
if (!['light', 'dark'].includes(preferences.theme)) preferences.theme = 'light';

function fold(value) {
  return String(value).normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/gi, 'd').toLocaleLowerCase('vi');
}
function dateText(value) {
  if (!value) return 'Chưa có';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Chưa có';
  const parts = new Intl.DateTimeFormat('vi-VN', {timeZone: 'Asia/Bangkok', day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit', hourCycle: 'h23'}).formatToParts(date);
  const get = type => parts.find(part => part.type === type)?.value;
  return `${get('day')}/${get('month')}/${get('year')} ${get('hour')}:${get('minute')}`;
}
function reportDate(value) {
  return /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value.split('-').reverse().join('/') : '';
}
function filteredRows() {
  const text = fold(query.value.trim());
  return inventory.filter(item => (fold(item.ma_hang).includes(text) || fold(item.ten_hang).includes(text))
    && (stockFilter === 'all' || (stockFilter === 'available' && item.ton_kho > 0)
    || (stockFilter === 'empty' && item.ton_kho <= 0) || (stockFilter === 'negative' && item.ton_kho < 0)))
    .sort((a, b) => {
      const left = sortColumn === 'ton_kho' ? Number(a[sortColumn]) : fold(a[sortColumn]);
      const right = sortColumn === 'ton_kho' ? Number(b[sortColumn]) : fold(b[sortColumn]);
      return (left < right ? -1 : left > right ? 1 : 0) * (sortDescending ? -1 : 1);
    });
}
function render() {
  const found = filteredRows();
  const fragment = document.createDocumentFragment();
  found.forEach((item, index) => {
    const row = document.createElement('tr');
    if (item.ton_kho === 0) row.className = 'out-of-stock';
    if (item.ton_kho < 0) row.className = 'negative-stock';
    const quantity = item.ton_kho === 0 ? 'Hết hàng' : `${item.ton_kho < 0 ? '⚠ ' : ''}${number.format(item.ton_kho)}`;
    [index + 1, item.ma_hang, item.ten_hang, quantity].forEach(value => {
      const cell = document.createElement('td');
      cell.textContent = value;
      cell.title = String(value);
      row.append(cell);
    });
    fragment.append(row);
  });
  rowsEl.replaceChildren(fragment);
  $('#empty').hidden = found.length !== 0;
  $('#row-count').textContent = `Hiển thị ${number.format(found.length)} / ${number.format(inventory.length)} mặt hàng`;
  document.querySelectorAll('[data-stock]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.stock === stockFilter)));
  const active = stockFilter !== 'all' || query.value.trim();
  $('#filter-summary').hidden = !active;
  const labels = {all: 'Tất cả mặt hàng', available: 'Có tồn kho', empty: 'Hết hàng', negative: 'Tồn kho âm'};
  $('#filter-summary span').textContent = `${labels[stockFilter]}${query.value.trim() ? ` · Tìm “${query.value.trim()}”` : ''}`;
  $('#export').disabled = found.length === 0;
}
function showStatus(message, error = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle('error', error);
}
async function load(manual = false) {
  if (refreshing) return;
  refreshing = true;
  refreshEl.disabled = true;
  if (manual) showStatus('Đang làm mới dữ liệu tồn kho…');
  try {
    const response = await fetch('/api/inventory', {cache: 'no-store'});
    if (!response.ok) throw new Error('Chưa tải được tồn kho. Hãy thử làm mới sau ít phút.');
    const body = await response.json();
    inventory = body.data;
    $('#count').textContent = number.format(inventory.length);
    const available = inventory.filter(item => item.ton_kho > 0).length;
    $('#available-count').textContent = number.format(available);
    $('#empty-count').textContent = number.format(inventory.length - available);
    $('#updated').textContent = `Cập nhật lần cuối: ${dateText(body.updated_at)}`;
    const from = reportDate(body.report?.from_date);
    const to = reportDate(body.report?.to_date);
    $('#from-date').value = from;
    $('#to-date').value = to;
    $('#period-label').textContent = body.report?.period || 'Kỳ đã đồng bộ';
    $('#report-scope').textContent = `Khoảng báo cáo: ${from && to ? `${from} – ${to}` : 'Chưa có thông tin'}`;
    $('#connection').textContent = '● Đã tải dữ liệu';
    $('#connection').classList.add('online');
    showStatus(manual ? 'Đã tải bản tồn kho mới nhất được đồng bộ.' : 'Dữ liệu từ VAOnline. Tìm kiếm, chọn bộ lọc hoặc bấm tiêu đề cột để sắp xếp.');
    render();
  } catch (error) {
    $('#connection').textContent = '● Chưa tải được dữ liệu';
    $('#connection').classList.remove('online');
    showStatus(error.message, true);
  } finally {
    refreshing = false;
    refreshEl.disabled = false;
  }
}
function savePreferences() {
  try { localStorage.setItem('va-stock-preferences', JSON.stringify(preferences)); } catch {}
  document.documentElement.dataset.theme = preferences.theme;
  clearInterval(refreshTimer);
  if (Number(preferences.interval)) refreshTimer = setInterval(() => { if (!document.hidden) load(); }, Number(preferences.interval) * 1000);
}
query.addEventListener('input', render);
refreshEl.addEventListener('click', () => load(true));
document.querySelectorAll('[data-stock]').forEach(button => button.addEventListener('click', () => {
  stockFilter = button.dataset.stock;
  render();
}));
document.querySelectorAll('[data-sort]').forEach(button => button.addEventListener('click', () => {
  sortDescending = sortColumn === button.dataset.sort ? !sortDescending : false;
  sortColumn = button.dataset.sort;
  document.querySelectorAll('[data-sort]').forEach(item => {
    item.parentElement.removeAttribute('aria-sort');
    item.querySelector('.sort-mark').textContent = '';
  });
  button.parentElement.setAttribute('aria-sort', sortDescending ? 'descending' : 'ascending');
  button.querySelector('.sort-mark').textContent = sortDescending ? '↓' : '↑';
  render();
}));
function clearFilters() { stockFilter = 'all'; query.value = ''; render(); }
$('#clear-filters').addEventListener('click', clearFilters);
$('#more-filters').addEventListener('click', () => { $('#stock-filter').value = stockFilter; dialog.showModal(); });
$('#close-filters').addEventListener('click', () => dialog.close());
$('#filter-form').addEventListener('submit', event => { event.preventDefault(); stockFilter = $('#stock-filter').value; dialog.close(); render(); });
$('#reset-filters').addEventListener('click', () => { clearFilters(); dialog.close(); });
$('#export').addEventListener('click', async () => {
  const params = new URLSearchParams({q: query.value.trim(), stock: stockFilter, sort: sortColumn, descending: String(sortDescending)});
  $('#export').disabled = true;
  try {
    const response = await fetch(`/api/export.xlsx?${params}`);
    if (!response.ok) throw new Error('Chưa xuất được Excel. Hãy thử lại sau ít phút.');
    const url = URL.createObjectURL(await response.blob());
    const link = document.createElement('a');
    link.href = url;
    link.download = 'TonKho.xlsx';
    document.body.append(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    showStatus('Đã xuất Excel theo danh sách đang lọc.');
  } catch (error) {
    showStatus(error.message, true);
  } finally {
    $('#export').disabled = filteredRows().length === 0;
  }
});
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click', () => {
  const settings = button.dataset.view === 'settings';
  $('#dashboard').hidden = settings;
  $('#settings').hidden = !settings;
  $('#page-subtitle').textContent = settings ? 'Cài đặt' : 'Tra cứu tồn kho';
  document.querySelectorAll('[data-view]').forEach(item => {
    item.classList.toggle('active', item === button);
    if (item === button) item.setAttribute('aria-current', 'page'); else item.removeAttribute('aria-current');
  });
  if (button.dataset.view === 'inventory') query.focus();
}));
$('#refresh-interval').value = preferences.interval;
$('#theme').value = preferences.theme;
$('#refresh-interval').addEventListener('change', event => { preferences.interval = event.target.value; savePreferences(); });
$('#theme').addEventListener('change', event => { preferences.theme = event.target.value; savePreferences(); });
savePreferences();
load();
