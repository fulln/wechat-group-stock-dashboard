const S = __DATA__;
const people = Object.values(S.speakers).sort((a,b) => b.mentions - a.mentions || a.name.localeCompare(b.name));
let activePerson = people[0]?.name || '';
let activeStockId = '';
let hoverIndex = null;
const canvas = document.getElementById('chart');
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
const stockOf = id => S.stocks[id] || {};

function mentionPointIndex(points, date) {
  if (!points.length) return -1;
  const exact = points.findIndex(point => point.date === date);
  if (exact >= 0) return exact;
  const after = points.findIndex(point => point.date > date);
  return after >= 0 ? after : points.length - 1;
}

function drawChart(stock, mentions, focusIndex = null) {
  const points = stock.dailyK?.points || [];
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 800;
  const height = canvas.clientHeight || 360;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  if (!points.length) {
    ctx.fillStyle = '#657071';
    ctx.font = '14px sans-serif';
    ctx.fillText('没有可用日 K 数据，可能是港股/美股/待确认标的。', 24, 42);
    return;
  }
  const pad = { left: 54, right: 18, top: 18, bottom: 32 };
  const chartW = width - pad.left - pad.right;
  const chartH = height - pad.top - pad.bottom;
  const high = Math.max(...points.map(point => point.high));
  const low = Math.min(...points.map(point => point.low));
  const span = high - low || 1;
  const y = value => pad.top + (high - value) / span * chartH;
  const step = chartW / points.length;
  const bodyW = Math.max(3, Math.min(11, step * 0.55));
  ctx.strokeStyle = '#e1e6de';
  ctx.fillStyle = '#657071';
  ctx.font = '11px sans-serif';
  for (let i = 0; i <= 4; i++) {
    const yy = pad.top + chartH * i / 4;
    const value = high - span * i / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(width - pad.right, yy);
    ctx.stroke();
    ctx.fillText(value.toFixed(value < 10 ? 2 : 0), 6, yy + 4);
  }
  points.forEach((point, index) => {
    const x = pad.left + step * (index + 0.5);
    const up = point.close >= point.open;
    ctx.strokeStyle = up ? '#b8443f' : '#15835b';
    ctx.fillStyle = up ? '#b8443f' : '#15835b';
    ctx.beginPath();
    ctx.moveTo(x, y(point.high));
    ctx.lineTo(x, y(point.low));
    ctx.stroke();
    const top = Math.min(y(point.open), y(point.close));
    const h = Math.max(1, Math.abs(y(point.open) - y(point.close)));
    ctx.fillRect(x - bodyW / 2, top, bodyW, h);
  });
  const markerCountByIndex = new Map();
  mentions.forEach(item => {
    const index = mentionPointIndex(points, item.date);
    if (index < 0) return;
    markerCountByIndex.set(index, (markerCountByIndex.get(index) || 0) + 1);
  });
  markerCountByIndex.forEach((count, index) => {
    const point = points[index];
    const x = pad.left + step * (index + 0.5);
    const yy = y(point.close);
    ctx.fillStyle = '#285f9f';
    ctx.beginPath();
    ctx.arc(x, yy, Math.min(8, 3 + count), 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'center';
    if (count > 1) ctx.fillText(String(count), x, yy + 3);
    ctx.textAlign = 'left';
  });
  ctx.fillStyle = '#657071';
  [0, Math.floor(points.length / 2), points.length - 1].forEach(index => {
    const x = pad.left + step * (index + 0.5);
    ctx.fillText(points[index].date.slice(5), x - 14, height - 10);
  });
  if (focusIndex !== null && points[focusIndex]) {
    const point = points[focusIndex];
    const x = pad.left + step * (focusIndex + 0.5);
    const yy = y(point.close);
    ctx.save();
    ctx.setLineDash([4, 3]);
    ctx.strokeStyle = '#285f9f';
    ctx.beginPath();
    ctx.moveTo(x, pad.top);
    ctx.lineTo(x, pad.top + chartH);
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(width - pad.right, yy);
    ctx.stroke();
    ctx.restore();
  }
}

function focusDetail(stock, mentions, index) {
  const points = stock.dailyK?.points || [];
  const point = points[index];
  const box = document.getElementById('hoverBox');
  if (!point) {
    box.textContent = '没有可用日 K 数据。';
    return;
  }
  const related = mentions.filter(item => mentionPointIndex(points, item.date) === index);
  const change = (point.close / point.open - 1) * 100;
  box.innerHTML = `<b>${point.date} · 收 ${point.close.toFixed(2)} · ${change >= 0 ? '+' : ''}${change.toFixed(2)}%</b>` +
    `<div>开 ${point.open.toFixed(2)} / 高 ${point.high.toFixed(2)} / 低 ${point.low.toFixed(2)} / 量 ${Math.round(point.volume || 0).toLocaleString()}</div>` +
    (related.length ? related.map(item => `<div class="quote">${esc(item.time)} · ${esc(item.signal || '中性')} · ${esc(item.text)}</div>`).join('') : '<div class="quote">该交易日无该人相关发言。</div>');
}

function locateIndex(event, stock) {
  const points = stock.dailyK?.points || [];
  if (!points.length) return null;
  const rect = canvas.getBoundingClientRect();
  const left = 54;
  const right = 18;
  const chartW = rect.width - left - right;
  return Math.max(0, Math.min(points.length - 1, Math.floor((event.clientX - rect.left - left) / chartW * points.length)));
}

function renderPeople() {
  const root = document.getElementById('peopleList');
  root.innerHTML = people.map(person => `
    <button class="person-btn ${person.name === activePerson ? 'active' : ''}" data-person="${esc(person.name)}">
      <span class="person-name"><span>${esc(person.name)}</span><span>${person.mentions}</span></span>
      <span class="person-meta">${person.stockCount} 个股票 · ${Object.keys(person.dates).length} 天</span>
    </button>
  `).join('');
  root.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
    activePerson = button.dataset.person;
    activeStockId = '';
    renderAll();
  }));
}

function renderStocks(person) {
  const strip = document.getElementById('stockStrip');
  if (!activeStockId && person.stocks[0]) activeStockId = person.stocks[0].stockId;
  strip.innerHTML = person.stocks.map(item => {
    const stock = stockOf(item.stockId);
    return `<button class="stock-btn ${item.stockId === activeStockId ? 'active' : ''}" data-stock="${esc(item.stockId)}">
      <b>${esc(stock.name || item.stockId)}</b>
      <small>${esc(stock.market)} ${esc(stock.code)} · ${item.mentions} 次</small>
    </button>`;
  }).join('');
  strip.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {
    activeStockId = button.dataset.stock;
    hoverIndex = null;
    renderAll(false);
  }));
}

function renderDetail(person) {
  const stockRow = person.stocks.find(item => item.stockId === activeStockId) || person.stocks[0];
  if (!stockRow) {
    document.getElementById('stockTitle').textContent = '暂无股票提及';
    document.getElementById('messageList').innerHTML = '<div class="empty">这个人没有股票上下文。</div>';
    drawChart({ dailyK: { points: [] } }, []);
    return;
  }
  const stock = stockOf(stockRow.stockId);
  const points = stock.dailyK?.points || [];
  document.getElementById('stockTitle').textContent = stock.name || stockRow.stockId;
  document.getElementById('stockMeta').textContent = `${stock.market || '--'} ${stock.code || '--'} · ${stockRow.mentions} 次提及 · ${Object.keys(stockRow.dates).join('、')}`;
  document.getElementById('chartStatus').textContent = points.length ? `${stock.dailyK.symbol} · ${points.length} 根日 K` : '无日 K 映射';
  document.getElementById('messageList').innerHTML = stockRow.items.map(item => `
    <div class="msg">
      <time>${esc(item.date)} ${esc(item.time)}</time>
      <span class="signal">${esc(item.signal || '中性')}</span>
      <span>${esc(item.text)}</span>
    </div>
  `).join('');
  drawChart(stock, stockRow.items, hoverIndex);
  const defaultIndex = points.length ? mentionPointIndex(points, stockRow.items[stockRow.items.length - 1]?.date || points[points.length - 1].date) : null;
  if (defaultIndex !== null && defaultIndex >= 0) focusDetail(stock, stockRow.items, defaultIndex);
}

function renderAll(rebuildPeople = true) {
  const person = S.speakers[activePerson] || people[0];
  if (!person) return;
  document.getElementById('speakerName').textContent = person.name;
  document.getElementById('speakerSub').textContent = `覆盖 ${Object.keys(person.dates).length} 天，按提及次数排序。`;
  document.getElementById('speakerMetrics').innerHTML = `<span>${person.mentions} 次提及</span><span>${person.stockCount} 个股票</span><span>偏多 ${person.signals.bullish || 0}</span><span>偏空 ${person.signals.bearish || 0}</span>`;
  if (rebuildPeople) renderPeople();
  renderStocks(person);
  renderDetail(person);
}

canvas.addEventListener('mousemove', event => {
  const person = S.speakers[activePerson];
  const stockRow = person?.stocks.find(item => item.stockId === activeStockId);
  const stock = stockOf(activeStockId);
  const index = locateIndex(event, stock);
  if (index === null || !stockRow) return;
  hoverIndex = index;
  drawChart(stock, stockRow.items, hoverIndex);
  focusDetail(stock, stockRow.items, hoverIndex);
});
canvas.addEventListener('mouseleave', () => { hoverIndex = null; renderDetail(S.speakers[activePerson]); });
addEventListener('resize', () => renderDetail(S.speakers[activePerson]));
renderAll();
