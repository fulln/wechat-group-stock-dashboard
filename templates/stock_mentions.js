const S = __DATA__;
function esc(v) {
  return String(v ?? '').replace(/[&<>"']/g, ch => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}
function normalizeHistoryHref(href) {
  if (!href || href.startsWith('#') || href.startsWith('http://') || href.startsWith('https://') || href.startsWith('/')) return href || '#';
  const isDateSegment = part => part.length === 10 && part[4] === '-' && part[7] === '-' &&
    Number.isFinite(Number(part.slice(0, 4))) && Number.isFinite(Number(part.slice(5, 7))) && Number.isFinite(Number(part.slice(8, 10)));
  if (window.location.protocol === 'file:' && window.location.pathname.split('/').some(isDateSegment)) {
    return `../${href}`;
  }
  if (window.location.protocol === 'file:') return href;
  const cleanHref = href.startsWith('./') ? href.slice(2) : href;
  return `/${cleanHref}`;
}
function versionedHref(item) {
  const href = normalizeHistoryHref(item.href || '#');
  if (!item.version || href.includes('?') || href.startsWith('#')) return href;
  return `${href}?v=${encodeURIComponent(item.version)}`;
}
function pageHistoryUrl() {
  if (window.location.protocol === 'file:') {
    const isDateSegment = part => part.length === 10 && part[4] === '-' && part[7] === '-';
    return window.location.pathname.split('/').some(isDateSegment) ? '../page_history.json' : 'page_history.json';
  }
  return '/page_history.json';
}
async function loadLatestPageHistory(fallbackItems) {
  try {
    const response = await fetch(pageHistoryUrl(), { cache: 'no-store' });
    if (!response.ok) return fallbackItems;
    const data = await response.json();
    return Array.isArray(data?.items) ? data.items : fallbackItems;
  } catch (_err) {
    return fallbackItems;
  }
}
function signalClass(score) {
  if (score > 0) return 'bullish';
  if (score < 0) return 'bearish';
  return 'neutral';
}
function gfSignal(direction) {
  if (direction === 'up') return 'bullish';
  if (direction === 'down') return 'bearish';
  return 'neutral';
}
function stockKey(item) {
  return `${item.market || ''}:${item.code || ''}`;
}
function shortText(value, limit) {
  const chars = Array.from(String(value || ''));
  return chars.length > limit ? `${chars.slice(0, limit).join('')}...` : chars.join('');
}
let activeStockKey = '';
let activeStockName = '';
let renderGfDetailFn = null;
function setActiveStock(item) {
  activeStockKey = stockKey(item);
  activeStockName = item.displayName || item.stockName || item.name || item.code || '';
  applyTrendFilter();
}
function syncStockControls(item) {
  const key = stockKey(item);
  document.querySelectorAll('.stock-control').forEach(button => {
    button.classList.toggle('active', button.dataset.stockKey === key);
  });
}
function selectDashboardStock(item) {
  setActiveStock(item);
  syncStockControls(item);
  if (renderGfDetailFn) renderGfDetailFn(item);
}
function renderStockControls(items) {
  const root = document.getElementById('stockControls');
  root.innerHTML = '';
  const groups = [
    ['up', '上涨'],
    ['down', '下跌'],
    ['neutral', '平盘 / 未取价'],
  ];
  const bucketed = { up: [], down: [], neutral: [] };
  items.forEach(item => {
    const direction = item.changeDirection === 'up' || item.changeDirection === 'down' ? item.changeDirection : 'neutral';
    bucketed[direction].push(item);
  });
  groups.forEach(([key, label]) => {
    const rows = bucketed[key];
    if (!rows.length) return;
    const group = document.createElement('div');
    group.className = 'stock-control-group';
    group.innerHTML = `
      <div class="stock-control-group-head">
        <span>${label}</span>
        <span class="count">${rows.length} 个</span>
      </div>
      <div class="stock-control-grid"></div>
    `;
    const grid = group.querySelector('.stock-control-grid');
    rows.forEach((item, index) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `stock-control ${key}`;
      button.dataset.stockKey = stockKey(item);
      const price = item.price || `${item.market || ''} ${item.code || ''}`.trim();
      const change = item.changePercent || `${item.count ?? 0} 次提及`;
      const signal = gfSignal(item.changeDirection);
      const labelText = item.marketSentiment?.label || item.sentiment?.label || '未计算';
      button.innerHTML = `
        <span class="stock-control-title">${esc(item.displayName || item.stockName || item.name)}</span>
        <span class="stock-control-sub">${esc(price)} · <span class="${signal}">${esc(change)}</span> · ${esc(labelText)}</span>
      `;
      button.addEventListener('click', () => selectDashboardStock(item));
      grid.appendChild(button);
    });
    root.appendChild(group);
  });
}
function applyTrendFilter() {
  const root = document.getElementById('trendCharts');
  if (!root) return;
  const cards = [...root.querySelectorAll('.trend-card')];
  if (!cards.length) return;
  let matched = false;
  cards.forEach(card => {
    const isActive = !activeStockKey || card.dataset.stockKey === activeStockKey;
    card.hidden = !isActive;
    card.classList.toggle('active', Boolean(activeStockKey && isActive));
    if (isActive) matched = true;
  });
  if (!matched) {
    cards.forEach(card => {
      card.hidden = false;
      card.classList.remove('active');
    });
  }
  const scope = document.getElementById('trendScope');
  if (scope) {
    scope.textContent = matched && activeStockName
      ? `当前选择：${activeStockName}。十字线跟随鼠标并吸附到折线交点，交点旁显示涨跌幅和附近发言；点击圆点可定位原文。`
      : '折线为分钟收盘价，圆点为群内提到该标的的时间；点击左侧股票卡片可切换对应折线图';
  }
}
document.getElementById('summaryBadge').textContent = `${S.stocks.length} 个标的 / ${S.stocks.reduce((n, s) => n + s.count, 0)} 次提及`;
document.getElementById('sectorMetric').textContent = `${S.sectors.length} 个板块 · 横向滚动查看全部`;
S.sectors.forEach(sec => {
  const item = document.createElement('div');
  item.className = 'sector-summary-item';
  const leaders = sec.leaders.slice(0, 2).map(([name, n]) => `${name}×${n}`).join('、');
  item.innerHTML = `
    <span class="sector-summary-name">${esc(sec.name)}</span>
    <span class="sector-summary-meta">${esc(sec.count)} 次${leaders ? ` · ${esc(leaders)}` : ''}</span>
  `;
  document.getElementById('sectorList').appendChild(item);
});
const gf = S.google_finance;
const marketSourceName = gf?.source || 'Google Finance';

document.getElementById('stockMetric').innerHTML = `${S.stocks.length} <small>标的</small>`;
document.getElementById('stockMini').textContent = `${S.stocks.reduce((n, s) => n + s.count, 0)} 次提及${S.google_finance ? ` · ${marketSourceName} 选择联动` : ''}`;

const speakerHistoryLink = document.getElementById('speakerHistoryLink');
if (S.speaker_dashboard_href) {
  speakerHistoryLink.href = normalizeHistoryHref(S.speaker_dashboard_href);
  speakerHistoryLink.hidden = false;
}
function renderPageHistory(pageHistory) {
  if (!pageHistory.length) return;
  const section = document.getElementById('historySection');
  const rootHistory = document.getElementById('pageHistory');
  const toggle = document.getElementById('historyToggle');
  section.hidden = false;
  if (!toggle.dataset.bound) {
    toggle.addEventListener('click', () => section.classList.toggle('open'));
    toggle.dataset.bound = '1';
  }
  rootHistory.replaceChildren();
  pageHistory.slice(0, 15).forEach(item => {
    const link = document.createElement('a');
    link.className = `history-link ${item.date === S.page_history?.current_date ? 'active' : ''}`;
    link.href = versionedHref(item);
    link.innerHTML = `
      <div class="history-date">${esc(item.date || '未知日期')}</div>
      <div class="history-meta">${esc(item.stock_count ?? '--')} 标的 · ${esc(item.mention_count ?? '--')} 次提及 · 大盘 ${esc(item.market_count ?? '--')} 条</div>
    `;
    rootHistory.appendChild(link);
  });
}
loadLatestPageHistory(S.page_history?.items || []).then(renderPageHistory);

if (gf?.items?.length) {
  const section = document.getElementById('gfSection');
  const detail = document.getElementById('gfDetail');
  section.hidden = false;
  document.getElementById('gfEntry').href = gf.betaEntryUrl || 'https://www.google.com/finance/beta';
  const updated = gf.generatedAt ? new Date(gf.generatedAt).toLocaleString('zh-CN', { hour12: false }) : '未知时间';
  document.getElementById('gfMeta').textContent = `${marketSourceName} · 采集 ${gf.items.length} 个结果 · 更新时间 ${updated} · 非投资建议`;

  renderGfDetailFn = function renderGfDetail(item) {
    const group = item.group || {};
    const marketSentiment = item.marketSentiment || {};
    const itemSourceName = item.sourceLabel || marketSourceName;
    const statKeys = ['昨收', '开盘价', '最高价', '最低价', '市值', '成交量', '成交额', '平均成交量', '52 周最高价', '52 周最低价'];
    const statsHtml = statKeys
      .filter(k => item.stats && item.stats[k])
      .map(k => `<div class="gf-stat"><b>${esc(k)}</b>${esc(item.stats[k])}</div>`)
      .join('');
    const factorHtml = (marketSentiment.factors || []).map(n => `<div class="section-item">${esc(n)}</div>`).join('');
    const newsHtml = (item.news || []).slice(0, 3).map(n => `<div class="section-item">${esc(n)}</div>`).join('');
    const profileHtml = (item.profile || []).slice(0, 2).map(n => `<div class="section-item">${esc(n)}</div>`).join('');
    detail.innerHTML = `
      <div class="gf-detail">
        <div class="gf-detail-top">
          <div>
            <div class="gf-title">${esc(item.displayName || item.stockName)} <span class="code">${esc(item.symbol)}</span></div>
            <div class="meta">${esc(item.googleName || '')} · ${esc(item.timestamp || '时间未解析')}${item.ambiguity ? ' · ' + esc(item.ambiguity) : ''}</div>
          </div>
          <div>
            <div class="gf-price">${esc(item.price || '--')}</div>
            <div class="signal ${gfSignal(item.changeDirection)}">${esc(item.changePercent || '--')} ${esc(item.changeAmountLine || '')}</div>
          </div>
        </div>
        <div class="meta" style="margin-top:8px">${esc(itemSourceName)} 情绪：<span class="signal ${signalClass(marketSentiment.score || 0)}">${esc(marketSentiment.label || '未计算')} ${(marketSentiment.score || 0) > 0 ? '+' : ''}${esc(marketSentiment.score ?? 0)}</span></div>
        <div class="gf-takeaway">${esc(item.takeaway || '')}</div>
        <div class="meta" style="margin-top:8px">聊天来源：${esc(group.count ?? 0)} 次提及（不参与本段情绪判断） · <a class="gf-link" href="${esc(item.sourceUrl)}" target="_blank" rel="noopener">${esc(itemSourceName)} 页面</a></div>
        <div class="gf-grid">${statsHtml}</div>
        ${factorHtml ? `<div class="section-list" style="margin-top:10px"><div class="meta">${esc(itemSourceName)} 判断因子</div>${factorHtml}</div>` : ''}
        ${profileHtml ? `<div class="section-list" style="margin-top:10px">${profileHtml}</div>` : ''}
        ${newsHtml ? `<div class="section-list" style="margin-top:10px"><div class="meta">页面新闻线索</div>${newsHtml}</div>` : ''}
      </div>
    `;
  };
}
const selectorItems = gf?.items?.length ? gf.items : S.stocks;
renderStockControls(selectorItems);
if (selectorItems.length) selectDashboardStock(selectorItems[0]);

function minuteValue(time) {
  const [h, m] = String(time || '').split(':').map(Number);
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null;
}
function pathFromPoints(points, xOf, yOf, field) {
  return points
    .filter(p => Number.isFinite(p[field]))
    .map((p, i) => `${i ? 'L' : 'M'}${xOf(p)} ${yOf(p[field])}`)
    .join(' ');
}
function nearestPoint(points, time) {
  const target = minuteValue(time);
  if (target == null || !points.length) return null;
  let best = points[0], bestDelta = Infinity;
  points.forEach(p => {
    const mv = minuteValue(p.time);
    if (mv == null) return;
    const delta = Math.abs(mv - target);
    if (delta < bestDelta) {
      best = p;
      bestDelta = delta;
    }
  });
  return best;
}
function priceBase(item, points) {
  const explicit = Number(item.preClose);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  const first = points.find(p => Number.isFinite(p.close) && p.close > 0);
  return first ? first.close : null;
}
function pctChange(value, base) {
  if (!Number.isFinite(value) || !Number.isFinite(base) || base <= 0) return null;
  return ((value - base) / base) * 100;
}
function pctText(value) {
  if (!Number.isFinite(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
}
function pctTone(value) {
  if (!Number.isFinite(value) || Math.abs(value) < 0.005) return 'flat';
  return value > 0 ? 'up' : 'down';
}
function nearestPointByMinute(points, targetMinute) {
  let best = points[0], bestDelta = Infinity;
  points.forEach(point => {
    const minute = minuteValue(point.time);
    if (minute == null) return;
    const delta = Math.abs(minute - targetMinute);
    if (delta < bestDelta) {
      best = point;
      bestDelta = delta;
    }
  });
  return best;
}
function markerSummaryNear(markers, point) {
  const pointMinute = minuteValue(point?.time);
  if (pointMinute == null) return '';
  let best = null, bestDelta = Infinity;
  (markers || []).forEach(marker => {
    const markerMinute = minuteValue(marker.time);
    if (markerMinute == null) return;
    const delta = Math.abs(markerMinute - pointMinute);
    if (delta < bestDelta) {
      best = marker;
      bestDelta = delta;
    }
  });
  if (!best || bestDelta > 2) return '';
  return `${best.sender || '未知'}：${shortText(best.text || '', 18)}`;
}
function markerNoteHtml(marker, noteId, point, base) {
  const text = String(marker.text || '');
  const isLong = Array.from(text).length > 42;
  const pct = point ? pctChange(point.close, base) : null;
  const priceMeta = point
    ? ` · 价格 ${esc(point.close)} · <span class="trend-pct ${pctTone(pct)}">${esc(pctText(pct))}</span>`
    : '';
  const head = `${esc(marker.time || '')} ${esc(marker.sender || '未知')} <span class="signal ${esc(marker.signal_key || 'neutral')}">${esc(marker.signal || '中性')}</span>${priceMeta}`;
  if (isLong) {
    return `
      <details class="trend-note" data-note-id="${esc(noteId)}">
        <summary>${head}：${esc(shortText(text, 42))}</summary>
        <div class="trend-note-full">${esc(text)}</div>
      </details>
    `;
  }
  return `<div class="trend-note" data-note-id="${esc(noteId)}">${head}：${esc(text || '无文本')}</div>`;
}
function renderTrendCharts() {
  const root = document.getElementById('trendCharts');
  const items = (S.stock_trends?.items || []).filter(item => item.points?.length);
  if (!items.length) {
    root.innerHTML = '<div class="meta">暂无分钟线数据</div>';
    return;
  }
  items.forEach((item, index) => {
    const points = item.points;
    const basePrice = priceBase(item, points);
    const prices = points.flatMap(p => [p.close, p.avg]).concat([basePrice]).filter(Number.isFinite);
    const minPrice = Math.min(...prices);
    const maxPrice = Math.max(...prices);
    const padPrice = Math.max((maxPrice - minPrice) * 0.08, maxPrice * 0.002);
    const yMin = minPrice - padPrice;
    const yMax = maxPrice + padPrice;
    const w = 820, h = 260, left = 44, right = 14, top = 16, bottom = 28;
    const minMinute = minuteValue(points[0].time);
    const maxMinute = minuteValue(points[points.length - 1].time);
    const xOf = p => {
      const mv = minuteValue(p.time);
      return left + ((mv - minMinute) / Math.max(1, maxMinute - minMinute)) * (w - left - right);
    };
    const yOf = value => top + ((yMax - value) / Math.max(0.0001, yMax - yMin)) * (h - top - bottom);
    const linePath = pathFromPoints(points, xOf, yOf, 'close');
    const avgPath = pathFromPoints(points, xOf, yOf, 'avg');
    const endPct = pctChange(points[points.length - 1].close, basePrice);
    const baseLine = Number.isFinite(basePrice) && basePrice >= yMin && basePrice <= yMax
      ? `<line class="trend-base" x1="${left}" y1="${yOf(basePrice).toFixed(1)}" x2="${w - right}" y2="${yOf(basePrice).toFixed(1)}"></line>`
      : '';
    const notePrefix = `trend-note-${stockKey(item).replace(/[^a-z0-9]/gi, '-')}`;
    const markerGroups = (item.markers || []).map((m, markerIndex) => {
      const point = nearestPoint(points, m.time);
      if (!point) return '';
      const pct = pctChange(point.close, basePrice);
      const x = xOf(point);
      const y = yOf(point.close);
      const noteId = `${notePrefix}-${markerIndex}`;
      return `
        <g class="trend-marker-group" data-note-id="${esc(noteId)}" tabindex="0">
          <circle class="trend-marker ${esc(m.signal_key || 'neutral')}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="5"></circle>
          <title>${esc(`${m.time} ${m.sender || ''} [${m.signal || ''}] ${m.text || ''} · 价格 ${point.close} · ${pctText(pct)}`)}</title>
        </g>
      `;
    }).join('');
    const noteHtml = (item.markers || []).map((m, markerIndex) => markerNoteHtml(m, `${notePrefix}-${markerIndex}`, nearestPoint(points, m.time), basePrice)).join('');
    const card = document.createElement('div');
    card.className = 'trend-card';
    card.dataset.stockKey = stockKey(item);
    card.innerHTML = `
      <div class="trend-head">
        <div>
          <div class="trend-title">${esc(item.displayName || item.stockName)} <span class="code">${esc(item.code)}</span></div>
          <div class="meta">${esc(item.quoteName || '')} · ${points.length} 个分钟点 · ${(item.markers || []).length} 个发言标记 · 昨收基准 ${basePrice ? basePrice.toFixed(2) : '--'}</div>
        </div>
        <div class="trend-meta">${esc(points[0].time)} - ${esc(points[points.length - 1].time)}<br>低 ${minPrice.toFixed(2)} / 高 ${maxPrice.toFixed(2)} · <span class="trend-pct ${pctTone(endPct)}">${pctText(endPct)}</span></div>
      </div>
      <svg class="trend-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="${esc(item.displayName || item.stockName)} 分时折线图">
        <line class="trend-axis" x1="${left}" y1="${top}" x2="${left}" y2="${h - bottom}"></line>
        <line class="trend-axis" x1="${left}" y1="${h - bottom}" x2="${w - right}" y2="${h - bottom}"></line>
        <line class="trend-crosshair trend-crosshair-v" x1="${left}" y1="${top}" x2="${left}" y2="${h - bottom}"></line>
        <line class="trend-crosshair trend-crosshair-h" x1="${left}" y1="${h - bottom}" x2="${w - right}" y2="${h - bottom}"></line>
        <line class="trend-axis" x1="${left}" y1="${yOf(maxPrice).toFixed(1)}" x2="${w - right}" y2="${yOf(maxPrice).toFixed(1)}" opacity="0.5"></line>
        <line class="trend-axis" x1="${left}" y1="${yOf(minPrice).toFixed(1)}" x2="${w - right}" y2="${yOf(minPrice).toFixed(1)}" opacity="0.5"></line>
        ${baseLine}
        <text class="trend-label" x="6" y="${yOf(maxPrice).toFixed(1)}">${maxPrice.toFixed(2)}</text>
        <text class="trend-label" x="6" y="${yOf(minPrice).toFixed(1)}">${minPrice.toFixed(2)}</text>
        <text class="trend-label" x="${left}" y="${h - 8}">${esc(points[0].time)}</text>
        <text class="trend-label" x="${(w - right - 36)}" y="${h - 8}">${esc(points[points.length - 1].time)}</text>
        <path class="trend-avg" d="${avgPath}"></path>
        <path class="trend-line" d="${linePath}"></path>
        ${markerGroups}
        <text class="trend-cross-label trend-pct flat" x="${left + 8}" y="${top + 14}"></text>
      </svg>
      <div class="trend-notes">${noteHtml || '<div class="trend-note">暂无发言标记</div>'}</div>
    `;
    card.addEventListener('click', event => {
      const group = event.target.closest('.trend-marker-group');
      if (!group) return;
      const note = card.querySelector(`.trend-note[data-note-id="${group.dataset.noteId}"]`);
      if (!note) return;
      if (note.tagName === 'DETAILS') note.open = true;
      note.classList.add('flash');
      note.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
      setTimeout(() => note.classList.remove('flash'), 1100);
    });
    const svg = card.querySelector('.trend-svg');
    const crossV = card.querySelector('.trend-crosshair-v');
    const crossH = card.querySelector('.trend-crosshair-h');
    const crossLabel = card.querySelector('.trend-cross-label');
    svg.addEventListener('mousemove', event => {
      const rect = svg.getBoundingClientRect();
      const rawX = Math.max(left, Math.min(w - right, ((event.clientX - rect.left) / rect.width) * w));
      const targetMinute = minMinute + ((rawX - left) / Math.max(1, w - left - right)) * Math.max(1, maxMinute - minMinute);
      const point = nearestPointByMinute(points, targetMinute);
      const x = xOf(point);
      const y = yOf(point.close);
      const pct = pctChange(point.close, basePrice);
      const summary = markerSummaryNear(item.markers || [], point);
      const label = `${point.time} ${point.close} ${pctText(pct)}${summary ? ' · ' + summary : ''}`;
      const labelX = Math.max(left + 4, Math.min(x + 8, w - right - 230));
      const labelY = Math.max(top + 14, Math.min(y - 10, h - bottom - 8));
      crossV.setAttribute('x1', x.toFixed(1));
      crossV.setAttribute('x2', x.toFixed(1));
      crossH.setAttribute('y1', y.toFixed(1));
      crossH.setAttribute('y2', y.toFixed(1));
      crossLabel.setAttribute('x', labelX.toFixed(1));
      crossLabel.setAttribute('y', labelY.toFixed(1));
      crossLabel.setAttribute('class', `trend-cross-label trend-pct ${pctTone(pct)}`);
      crossLabel.textContent = label;
      svg.classList.add('crosshair-on');
    });
    svg.addEventListener('mouseleave', () => svg.classList.remove('crosshair-on'));
    root.appendChild(card);
  });
  applyTrendFilter();
}
renderTrendCharts();
