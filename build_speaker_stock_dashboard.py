"""Build a speaker-centric stock mention dashboard with daily candles."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SINA_KLINE_URL = "https://quotes.sina.cn/cn/api/openapi.php/CN_MarketDataService.getKLineData"
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"
TEMPLATE_DIR = Path(__file__).with_name("templates")


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
    market = str(stock.get("market") or "").upper()
    code = str(stock.get("code") or "")
    mainland_markets = {"A股", "CN", "SH", "SHSE", "SSE", "SSE STAR", "SZ", "SZSE"}
    if market not in mainland_markets:
        return None
    match = re.search(r"\d{6}", code)
    if not match:
        return None
    base_code = match.group(0)
    if market in {"SZ", "SZSE"} or base_code.startswith(("000", "001", "002", "003", "300", "301")):
        return f"sz{base_code}"
    if market in {"SH", "SHSE", "SSE", "SSE STAR"} or base_code.startswith(("600", "601", "603", "605", "688", "689")):
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
            items[stock_id] = {"status": "unmapped", "points": []}
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


def render_template(template_name: str, replacements: dict[str, str]) -> str:
    template = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def render(payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    script = render_template("speaker_dashboard.js", {"__DATA__": data})
    return render_template(
        "speaker_dashboard.html",
        {
            "__DATE_RANGE__": str(payload.get("dateRange", "")),
            "__SCRIPT__": script,
        },
    )


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
