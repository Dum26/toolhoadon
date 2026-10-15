const rowsEl = document.querySelector('#rows');
const searchEl = document.querySelector('#query');
const statusEl = document.querySelector('#status');
const refreshEl = document.querySelector('#refresh');
let inventory = [];

function fold(text) {
  return String(text).normalize('NFD').replace(/[\u0300-\u036f]/g, '').replace(/đ/gi, 'd').toLocaleLowerCase('vi');
}
function dateText(value) {
  if (!value) return 'Chưa có';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat('vi-VN', {dateStyle:'short',timeStyle:'short'}).format(date);
}
function render() {
  const q = fold(searchEl.value.trim());
  const found = inventory.filter(item => fold(item.ma_hang).includes(q) || fold(item.ten_hang).includes(q));
  rowsEl.replaceChildren();
  const fragment = document.createDocumentFragment();
  found.forEach((item, index) => {
    const tr = document.createElement('tr');
    [index + 1, item.ma_hang, item.ten_hang, new Intl.NumberFormat('vi-VN').format(item.ton_kho), dateText(item.updated_at)].forEach(value => {
      const td = document.createElement('td');
      td.textContent = value;
      tr.append(td);
    });
    fragment.append(tr);
  });
  rowsEl.append(fragment);
  document.querySelector('#empty').hidden = found.length !== 0;
}
async function load() {
  const response = await fetch('/api/inventory', {cache:'no-store'});
  if (!response.ok) throw new Error('Không tải được dữ liệu tồn kho.');
  const body = await response.json();
  inventory = body.data;
  document.querySelector('#count').textContent = `Tổng số mặt hàng: ${body.count}`;
  document.querySelector('#updated').textContent = `Cập nhật lần cuối: ${dateText(body.updated_at)}`;
  render();
}
searchEl.addEventListener('input', render);
refreshEl.addEventListener('click', async () => {
  refreshEl.disabled = true;
  statusEl.classList.remove('error');
  statusEl.textContent = 'Đang làm mới dữ liệu...';
  try {
    await load();
    statusEl.textContent = 'Đã làm mới dữ liệu.';
  } catch (error) {
    statusEl.classList.add('error');
    statusEl.textContent = error.message;
  } finally { refreshEl.disabled = false; }
});
load().catch(error => {statusEl.classList.add('error');statusEl.textContent = error.message;});
