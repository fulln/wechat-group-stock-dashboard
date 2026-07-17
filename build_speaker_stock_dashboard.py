"""Build a speaker-centric stock mention dashboard with daily candles."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SINA_KLINE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def normalize_speaker(name: str) -> str:
    if name == "me":
        return os.environ.get("CHAT_STOCK_SELF_NAME", name)
    return name


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def parse_float(value: object) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def a_share_symbol(stock: dict) -> str | None:
    market = str(stock.get("market") or "")
    code = str(stock.get("code") or "")
    match = re.search(r"\d{6}", code)
    if not match:
        return None
    base_code = match.group(0)
    if market == "SZ" or base_code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"sz{base_code}"
    if market == "SH" or base_code.startswith(("600", "601", "603", "605", "688", "689")):
        return f"sh{base_code}"
    return None


def fetch_daily(symbol: str, timeout: int = 30, datalen: int = 60) -> list[dict]:
    query = urlencode({"symbol": symbol, "scale": 240, "ma": "no", "datalen": datalen})
    req = Request(
        f"{SINA_KLINE_URL}?{query}",
        headers={"User-Agent": USER_AGENT, "Referer": "https://finance.sina.com.cn/"},
    )
    with urlopen(req, timeout=timeout) as resp:
        raw = json.loads(resp.read().decode("utf-8", "ignore"))
    rows = (((raw.get("result") or {}).get("data")) or [])
    points: list[dict] = []
    for row in rows:
        point = {
            "date": row.get("day"),
            "open": parse_float(row.get("open")),
            "high": parse_float(row.get("high")),
            "low": parse_float(row.get("low")),
            "close": parse_float(row.get("close")),
            "volume": parse_float(row.get("volume")),
        }
        if point["date"] and all(point[key] is not None for key in ("open", "high", "low", "close")):
            points.append(point)
    return points


def collect(input_dir: Path, days: int) -> tuple[dict, dict, list[str]]:
    stock_files = sorted(input_dir.glob("20??-??-??/stock_mentions.json"))[-days:]
    stocks: dict[str, dict] = {}
    speakers: dict[str, dict] = {}
    seen_mentions: set[tuple[str, str, str, str, str]] = set()
    for path in stock_files:
        day = path.parent.name
        data = load_json(path)
        for stock in data.get("stocks", []):
            code = str(stock.get("code") or "")
            market = str(stock.get("market") or "")
            name = str(stock.get("name") or "")
            stock_id = f"{market}:{code}:{name}"
            stocks.setdefault(
                stock_id,
                {
                    "id": stock_id,
                    "name": name,
                    "code": code,
                    "market": market,
                    "symbol": a_share_symbol(stock),
                    "mentions": 0,
                    "speakers": Counter(),
                },
            )
            for ctx in stock.get("contexts") or []:
                speaker = normalize_speaker(str(ctx.get("sender") or "未知"))
                text = str(ctx.get("text") or "")
                time = str(ctx.get("time") or "")
                key = (day, speaker, stock_id, time, text)
                if key in seen_mentions:
                    continue
                seen_mentions.add(key)
                mention = {
                    "date": day,
                    "time": time,
                    "speaker": speaker,
                    "stockId": stock_id,
                    "stockName": name,
                    "stockCode": code,
                    "stockMarket": market,
                    "signal": ctx.get("signal"),
                    "signalKey": ctx.get("signal_key"),
                    "alias": ctx.get("alias"),
                    "text": text,
                }
                speaker_item = speakers.setdefault(
                    speaker,
                    {"name": speaker, "mentions": 0, "stocks": {}, "signals": Counter(), "dates": Counter()},
                )
                stock_item = speaker_item["stocks"].setdefault(
                    stock_id,
                    {"stockId": stock_id, "mentions": 0, "dates": Counter(), "items": []},
                )
                stock_item["mentions"] += 1
                stock_item["dates"][day] += 1
                stock_item["items"].append(mention)
                speaker_item["mentions"] += 1
                speaker_item["signals"][str(ctx.get("signal_key") or "neutral")] += 1
                speaker_item["dates"][day] += 1
                stocks[stock_id]["mentions"] += 1
                stocks[stock_id]["speakers"][speaker] += 1

    normalized_speakers = {}
    for speaker, item in speakers.items():
        stock_rows = []
        for stock_id, stock_item in item["stocks"].items():
            stock_item["dates"] = dict(sorted(stock_item["dates"].items()))
            stock_item["items"].sort(key=lambda row: (row["date"], row["time"], row["text"]))
            stock_rows.append(stock_item)
        stock_rows.sort(key=lambda row: (-row["mentions"], stocks[row["stockId"]]["name"]))
        normalized_speakers[speaker] = {
            "name": speaker,
            "mentions": item["mentions"],
            "stockCount": len(stock_rows),
            "signals": dict(item["signals"]),
            "dates": dict(sorted(item["dates"].items())),
            "stocks": stock_rows,
        }

    normalized_stocks = {}
    for stock_id, item in stocks.items():
        normalized_stocks[stock_id] = {
            **{key: value for key, value in item.items() if key != "speakers"},
            "speakers": dict(item["speakers"]),
        }
    return normalized_speakers, normalized_stocks, [path.parent.name for path in stock_files]


def hydrate_daily_k(stocks: dict, cache_path: Path, timeout: int) -> dict:
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache = load_json(cache_path) if cache_path.exists() else {"items": {}}
    items = cache.setdefault("items", {})
    today = dt.date.today().isoformat()
    for stock_id, stock in sorted(stocks.items(), key=lambda row: row[1]["name"]):
        symbol = stock.get("symbol")
        if not symbol:
            items.setdefault(stock_id, {"status": "unmapped", "points": []})
            continue
        cached = items.get(stock_id) or {}
        if cached.get("symbol") == symbol and cached.get("fetchedDate") == today and cached.get("points"):
            continue
        try:
            points = fetch_daily(symbol, timeout=timeout)
            status = "ok" if points else "empty"
            items[stock_id] = {
                "symbol": symbol,
                "source": "Sina CN_MarketDataService.getKLineData",
                "status": status,
                "points": points,
                "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                "fetchedDate": today,
            }
            print(f"[{status}] {stock['name']} {symbol} points={len(points)}")
        except Exception as exc:  # noqa: BLE001 - keep the local page generation moving.
            items[stock_id] = {
                "symbol": symbol,
                "source": "Sina CN_MarketDataService.getKLineData",
                "status": "failed",
                "error": str(exc),
                "points": [],
                "fetchedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                "fetchedDate": today,
            }
            print(f"[failed] {stock['name']} {symbol}: {exc}")
    cache["generatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat()
    cache["note"] = "日 K 用于把群聊提及日期映射到股票走势，不构成投资建议。"
    cache_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    return cache


def disabled_daily_k(stocks: dict) -> dict:
    return {
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "note": "日 K 抓取已关闭；使用 --with-market-data 或取消 --no-daily-k 后可生成走势数据。",
        "items": {stock_id: {"status": "disabled", "points": []} for stock_id in stocks},
    }


def attach_chart_data(stocks: dict, daily_k: dict) -> None:
    for stock_id, stock in stocks.items():
        stock["dailyK"] = daily_k.get("items", {}).get(stock_id, {"status": "missing", "points": []})


def render(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>人物股票图谱 · 群聊股票看板</title>
<style>
:root {{ --bg:#f6f7f2; --panel:#fff; --ink:#202225; --muted:#657071; --line:#dfe4dc; --blue:#285f9f; --red:#b8443f; --green:#15835b; --amber:#b7791f; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.55 -apple-system,BlinkMacSystemFont,"PingFang SC",sans-serif; }}
.shell {{ max-width:1380px; margin:0 auto; padding:20px; }}
.topbar {{ display:flex; justify-content:space-between; gap:16px; align-items:end; margin-bottom:14px; }}
.topbar h1 {{ margin:0 0 5px; font-size:26px; }}
.sub {{ color:var(--muted); font-size:13px; }}
.home {{ color:var(--blue); text-decoration:none; border:1px solid var(--line); background:#fff; border-radius:8px; padding:8px 10px; }}
.layout {{ display:grid; grid-template-columns:300px minmax(0,1fr); gap:14px; min-height:calc(100vh - 100px); }}
.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; }}
.people {{ padding:14px; overflow:auto; max-height:calc(100vh - 106px); }}
.people h2 {{ margin:0 0 8px; font-size:15px; }}
.person-btn {{ width:100%; border:1px solid var(--line); background:#fff; color:var(--ink); border-radius:8px; padding:10px; margin:6px 0; text-align:left; cursor:pointer; }}
.person-btn:hover {{ background:#f8fbf7; }}
.person-btn.active {{ border-color:var(--blue); background:#edf5fb; box-shadow:inset 3px 0 0 var(--blue); }}
.person-name {{ display:flex; justify-content:space-between; gap:8px; font-weight:750; }}
.person-meta {{ color:var(--muted); font-size:12px; margin-top:2px; }}
.content {{ min-width:0; display:grid; grid-template-rows:auto auto 1fr; gap:14px; }}
.summary {{ padding:16px; display:grid; grid-template-columns:1fr auto; gap:12px; align-items:center; }}
.summary h2 {{ margin:0; font-size:22px; }}
.metrics {{ display:flex; flex-wrap:wrap; gap:8px; justify-content:end; }}
.metrics span, .chip {{ border:1px solid var(--line); border-radius:999px; padding:5px 9px; background:#fbfcf8; color:var(--muted); font-size:12px; }}
.stock-strip {{ padding:12px; display:flex; gap:8px; overflow-x:auto; }}
.stock-btn {{ flex:0 0 auto; min-width:150px; max-width:210px; border:1px solid var(--line); border-radius:8px; background:#fff; color:var(--ink); padding:9px; text-align:left; cursor:pointer; }}
.stock-btn.active {{ border-color:var(--blue); background:#edf5fb; }}
.stock-btn b, .stock-btn small {{ display:block; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
.stock-btn small {{ color:var(--muted); }}
.detail {{ padding:16px; min-width:0; }}
.detail-head {{ display:flex; justify-content:space-between; gap:12px; align-items:start; margin-bottom:12px; }}
.detail h3 {{ margin:0 0 4px; font-size:20px; }}
.chart-wrap {{ position:relative; height:360px; border:1px solid var(--line); border-radius:8px; background:#fbfcf8; overflow:hidden; }}
canvas {{ width:100%; height:100%; display:block; }}
.hover-box {{ margin-top:10px; min-height:48px; border-left:3px solid var(--blue); background:#f5f8fb; padding:9px 11px; color:var(--muted); }}
.hover-box b {{ color:var(--ink); }}
.hover-box .quote {{ margin-top:7px; padding-top:7px; border-top:1px solid var(--line); color:var(--ink); }}
.messages {{ margin-top:12px; display:grid; gap:8px; max-height:260px; overflow:auto; }}
.msg {{ display:grid; grid-template-columns:92px 56px 1fr; gap:8px; border:1px solid var(--line); border-radius:8px; padding:9px; background:#fff; }}
.msg time {{ color:var(--blue); font-weight:700; }}
.msg .signal {{ color:var(--muted); }}
.empty {{ color:var(--muted); padding:20px; }}
@media (max-width:900px) {{ .layout {{ grid-template-columns:1fr; }} .people {{ max-height:none; }} .summary {{ grid-template-columns:1fr; }} .metrics {{ justify-content:start; }} .chart-wrap {{ height:300px; }} }}
</style>
</head>
<body>
<main class="shell">
  <div class="topbar">
    <div>
      <h1>人物股票图谱</h1>
      <div class="sub">按人名聚合群里提到过的股票消息，并叠加到日 K。区间：{payload["dateRange"]} · 非投资建议</div>
    </div>
    <a class="home" href="./">返回首页</a>
  </div>
  <section class="layout">
    <aside class="panel people">
      <h2>发言人</h2>
      <div id="peopleList"></div>
    </aside>
    <section class="content">
      <div class="panel summary">
        <div>
          <h2 id="speakerName"></h2>
          <div class="sub" id="speakerSub"></div>
        </div>
        <div class="metrics" id="speakerMetrics"></div>
      </div>
      <div class="panel stock-strip" id="stockStrip"></div>
      <article class="panel detail">
        <div class="detail-head">
          <div>
            <h3 id="stockTitle"></h3>
            <div class="sub" id="stockMeta"></div>
          </div>
          <span class="chip" id="chartStatus"></span>
        </div>
        <div class="chart-wrap"><canvas id="chart"></canvas></div>
        <div class="hover-box" id="hoverBox">移动鼠标查看日 K；图上的圆点是该人提到该股票的日期。</div>
        <div class="messages" id="messageList"></div>
      </article>
    </section>
  </section>
</main>
<script>
const S = {data};
const people = Object.values(S.speakers).sort((a,b) => b.mentions - a.mentions || a.name.localeCompare(b.name));
let activePerson = people[0]?.name || '';
let activeStockId = '';
let hoverIndex = null;
const canvas = document.getElementById('chart');
const esc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
const stockOf = id => S.stocks[id] || {{}};

function mentionPointIndex(points, date) {{
  if (!points.length) return -1;
  const exact = points.findIndex(point => point.date === date);
  if (exact >= 0) return exact;
  const after = points.findIndex(point => point.date > date);
  return after >= 0 ? after : points.length - 1;
}}

function drawChart(stock, mentions, focusIndex = null) {{
  const points = stock.dailyK?.points || [];
  const dpr = window.devicePixelRatio || 1;
  const width = canvas.clientWidth || 800;
  const height = canvas.clientHeight || 360;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, width, height);
  if (!points.length) {{
    ctx.fillStyle = '#657071';
    ctx.font = '14px sans-serif';
    ctx.fillText('没有可用日 K 数据，可能是港股/美股/待确认标的。', 24, 42);
    return;
  }}
  const pad = {{ left: 54, right: 18, top: 18, bottom: 32 }};
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
  for (let i = 0; i <= 4; i++) {{
    const yy = pad.top + chartH * i / 4;
    const value = high - span * i / 4;
    ctx.beginPath();
    ctx.moveTo(pad.left, yy);
    ctx.lineTo(width - pad.right, yy);
    ctx.stroke();
    ctx.fillText(value.toFixed(value < 10 ? 2 : 0), 6, yy + 4);
  }}
  points.forEach((point, index) => {{
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
  }});
  const markerCountByIndex = new Map();
  mentions.forEach(item => {{
    const index = mentionPointIndex(points, item.date);
    if (index < 0) return;
    markerCountByIndex.set(index, (markerCountByIndex.get(index) || 0) + 1);
  }});
  markerCountByIndex.forEach((count, index) => {{
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
  }});
  ctx.fillStyle = '#657071';
  [0, Math.floor(points.length / 2), points.length - 1].forEach(index => {{
    const x = pad.left + step * (index + 0.5);
    ctx.fillText(points[index].date.slice(5), x - 14, height - 10);
  }});
  if (focusIndex !== null && points[focusIndex]) {{
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
  }}
}}

function focusDetail(stock, mentions, index) {{
  const points = stock.dailyK?.points || [];
  const point = points[index];
  const box = document.getElementById('hoverBox');
  if (!point) {{
    box.textContent = '没有可用日 K 数据。';
    return;
  }}
  const related = mentions.filter(item => mentionPointIndex(points, item.date) === index);
  const change = (point.close / point.open - 1) * 100;
  box.innerHTML = `<b>${{point.date}} · 收 ${{point.close.toFixed(2)}} · ${{change >= 0 ? '+' : ''}}${{change.toFixed(2)}}%</b>` +
    `<div>开 ${{point.open.toFixed(2)}} / 高 ${{point.high.toFixed(2)}} / 低 ${{point.low.toFixed(2)}} / 量 ${{Math.round(point.volume || 0).toLocaleString()}}</div>` +
    (related.length ? related.map(item => `<div class="quote">${{esc(item.time)}} · ${{esc(item.signal || '中性')}} · ${{esc(item.text)}}</div>`).join('') : '<div class="quote">该交易日无该人相关发言。</div>');
}}

function locateIndex(event, stock) {{
  const points = stock.dailyK?.points || [];
  if (!points.length) return null;
  const rect = canvas.getBoundingClientRect();
  const left = 54;
  const right = 18;
  const chartW = rect.width - left - right;
  return Math.max(0, Math.min(points.length - 1, Math.floor((event.clientX - rect.left - left) / chartW * points.length)));
}}

function renderPeople() {{
  const root = document.getElementById('peopleList');
  root.innerHTML = people.map(person => `
    <button class="person-btn ${{person.name === activePerson ? 'active' : ''}}" data-person="${{esc(person.name)}}">
      <span class="person-name"><span>${{esc(person.name)}}</span><span>${{person.mentions}}</span></span>
      <span class="person-meta">${{person.stockCount}} 个股票 · ${{Object.keys(person.dates).length}} 天</span>
    </button>
  `).join('');
  root.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {{
    activePerson = button.dataset.person;
    activeStockId = '';
    renderAll();
  }}));
}}

function renderStocks(person) {{
  const strip = document.getElementById('stockStrip');
  if (!activeStockId && person.stocks[0]) activeStockId = person.stocks[0].stockId;
  strip.innerHTML = person.stocks.map(item => {{
    const stock = stockOf(item.stockId);
    return `<button class="stock-btn ${{item.stockId === activeStockId ? 'active' : ''}}" data-stock="${{esc(item.stockId)}}">
      <b>${{esc(stock.name || item.stockId)}}</b>
      <small>${{esc(stock.market)}} ${{esc(stock.code)}} · ${{item.mentions}} 次</small>
    </button>`;
  }}).join('');
  strip.querySelectorAll('button').forEach(button => button.addEventListener('click', () => {{
    activeStockId = button.dataset.stock;
    hoverIndex = null;
    renderAll(false);
  }}));
}}

function renderDetail(person) {{
  const stockRow = person.stocks.find(item => item.stockId === activeStockId) || person.stocks[0];
  if (!stockRow) {{
    document.getElementById('stockTitle').textContent = '暂无股票提及';
    document.getElementById('messageList').innerHTML = '<div class="empty">这个人没有股票上下文。</div>';
    drawChart({{ dailyK: {{ points: [] }} }}, []);
    return;
  }}
  const stock = stockOf(stockRow.stockId);
  const points = stock.dailyK?.points || [];
  document.getElementById('stockTitle').textContent = stock.name || stockRow.stockId;
  document.getElementById('stockMeta').textContent = `${{stock.market || '--'}} ${{stock.code || '--'}} · ${{stockRow.mentions}} 次提及 · ${{Object.keys(stockRow.dates).join('、')}}`;
  document.getElementById('chartStatus').textContent = points.length ? `${{stock.dailyK.symbol}} · ${{points.length}} 根日 K` : '无日 K 映射';
  document.getElementById('messageList').innerHTML = stockRow.items.map(item => `
    <div class="msg">
      <time>${{esc(item.date)}} ${{esc(item.time)}}</time>
      <span class="signal">${{esc(item.signal || '中性')}}</span>
      <span>${{esc(item.text)}}</span>
    </div>
  `).join('');
  drawChart(stock, stockRow.items, hoverIndex);
  const defaultIndex = points.length ? mentionPointIndex(points, stockRow.items[stockRow.items.length - 1]?.date || points[points.length - 1].date) : null;
  if (defaultIndex !== null && defaultIndex >= 0) focusDetail(stock, stockRow.items, defaultIndex);
}}

function renderAll(rebuildPeople = true) {{
  const person = S.speakers[activePerson] || people[0];
  if (!person) return;
  document.getElementById('speakerName').textContent = person.name;
  document.getElementById('speakerSub').textContent = `覆盖 ${{Object.keys(person.dates).length}} 天，按提及次数排序。`;
  document.getElementById('speakerMetrics').innerHTML = `<span>${{person.mentions}} 次提及</span><span>${{person.stockCount}} 个股票</span><span>偏多 ${{person.signals.bullish || 0}}</span><span>偏空 ${{person.signals.bearish || 0}}</span>`;
  if (rebuildPeople) renderPeople();
  renderStocks(person);
  renderDetail(person);
}}

canvas.addEventListener('mousemove', event => {{
  const person = S.speakers[activePerson];
  const stockRow = person?.stocks.find(item => item.stockId === activeStockId);
  const stock = stockOf(activeStockId);
  const index = locateIndex(event, stock);
  if (index === null || !stockRow) return;
  hoverIndex = index;
  drawChart(stock, stockRow.items, hoverIndex);
  focusDetail(stock, stockRow.items, hoverIndex);
}});
canvas.addEventListener('mouseleave', () => {{ hoverIndex = null; renderDetail(S.speakers[activePerson]); }});
addEventListener('resize', () => renderDetail(S.speakers[activePerson]));
renderAll();
</script>
</body>
</html>"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, default=Path("exports/group_stock_dashboard"))
    parser.add_argument("--output", type=Path, default=Path("exports/group_stock_dashboard/speakers.html"))
    parser.add_argument("--json", type=Path, default=Path("exports/group_stock_dashboard/speakers.json"))
    parser.add_argument("--daily-k", type=Path, default=Path("exports/group_stock_dashboard/speaker_daily_k.json"))
    parser.add_argument("--days", type=int, default=15)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--no-daily-k", action="store_true", help="生成发言人页面但不抓取日 K 数据")
    args = parser.parse_args()

    speakers, stocks, dates = collect(args.input_dir, args.days)
    daily_k = disabled_daily_k(stocks) if args.no_daily_k else hydrate_daily_k(stocks, args.daily_k, args.timeout)
    attach_chart_data(stocks, daily_k)
    payload = {
        "generatedAt": dt.datetime.now().astimezone().isoformat(),
        "dateRange": f"{dates[0]} — {dates[-1]}" if dates else "",
        "dates": dates,
        "speakerCount": len(speakers),
        "stockCount": len(stocks),
        "speakers": speakers,
        "stocks": stocks,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(payload), encoding="utf-8")
    args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] speakers={len(speakers)} stocks={len(stocks)} -> {args.output}")


if __name__ == "__main__":
    main()
