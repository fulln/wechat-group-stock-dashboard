"""Fetch intraday stock trend lines and attach group mention markers."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from fetch_google_finance_snapshot import candidates_for


SINA_TRENDS_URL = "https://quotes.sina.cn/cn/api/openapi.php/CN_MinlineService.getMinlineData"
SINA_QUOTE_URL = "http://hq.sinajs.cn/list="
USER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def market_symbol(candidate: dict) -> str | None:
    market = candidate.get("market")
    code = candidate.get("code")
    if market == "SH":
        return f"sh{code}"
    if market == "SZ":
        return f"sz{code}"
    return None


def fetch_trends(symbol: str, timeout: int) -> dict:
    query = urlencode({"symbol": symbol})
    req = Request(f"{SINA_TRENDS_URL}?{query}", headers={"User-Agent": USER_AGENT, "Referer": "https://finance.sina.com.cn/"})
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


def fetch_quote(symbol: str, timeout: int) -> dict:
    req = Request(
        f"{SINA_QUOTE_URL}{symbol}",
        headers={
            "User-Agent": USER_AGENT,
            "Referer": "https://finance.sina.com.cn/",
            "Accept": "*/*",
            "Connection": "close",
        },
    )
    with urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("gbk", "ignore")
    if '="' not in text:
        return {}
    fields = text.split('="', 1)[1].split('"', 1)[0].split(",")
    return {
        "quoteName": fields[0] if len(fields) > 0 else "",
        "open": to_float(fields[1]) if len(fields) > 1 else None,
        "preClose": to_float(fields[2]) if len(fields) > 2 else None,
        "current": to_float(fields[3]) if len(fields) > 3 else None,
        "high": to_float(fields[4]) if len(fields) > 4 else None,
        "low": to_float(fields[5]) if len(fields) > 5 else None,
        "quoteDate": fields[30] if len(fields) > 30 else "",
        "quoteTime": fields[31] if len(fields) > 31 else "",
    }


def to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_points(raw: dict) -> list[dict]:
    rows = (((raw.get("result") or {}).get("data")) or [])
    points: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        points.append({
            "time": str(row.get("m", ""))[:5],
            "datetime": str(row.get("m", "")),
            "open": None,
            "close": to_float(row.get("p")),
            "high": None,
            "low": None,
            "volume": to_float(row.get("v")),
            "amount": None,
            "avg": to_float(row.get("avg_p")),
        })
    return [point for point in points if point["close"] is not None]


def marker_contexts(stock: dict) -> list[dict]:
    markers = []
    for ctx in stock.get("contexts") or []:
        markers.append({
            "time": ctx.get("time"),
            "sender": ctx.get("sender"),
            "signal": ctx.get("signal"),
            "signal_key": ctx.get("signal_key"),
            "text": ctx.get("text"),
        })
    return markers


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stock_json", type=Path)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    stats = json.loads(args.stock_json.read_text(encoding="utf-8"))
    items: list[dict] = []
    for stock in stats.get("stocks", []):
        for candidate in candidates_for(stock):
            symbol = market_symbol(candidate)
            if not symbol:
                continue
            try:
                raw = fetch_trends(symbol, args.timeout)
                points = parse_points(raw)
                quote = fetch_quote(symbol, args.timeout)
                item = {
                    **candidate,
                    "source": "Sina CN_MinlineService",
                    "marketSymbol": symbol,
                    "quoteName": quote.get("quoteName", ""),
                    "preClose": quote.get("preClose"),
                    "open": quote.get("open"),
                    "current": quote.get("current"),
                    "quoteDate": quote.get("quoteDate", ""),
                    "quoteTime": quote.get("quoteTime", ""),
                    "points": points,
                    "markers": marker_contexts(stock),
                    "status": "ok" if points else "partial",
                    "sampledAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            except Exception as exc:  # noqa: BLE001 - keep the rest of the charts moving.
                item = {
                    **candidate,
                    "source": "Sina CN_MinlineService",
                    "marketSymbol": symbol,
                    "points": [],
                    "markers": marker_contexts(stock),
                    "status": "failed",
                    "error": str(exc),
                    "sampledAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            print(f"[{item['status']}] {candidate['displayName']} {symbol} points={len(item['points'])}")
            items.append(item)

    output = args.output or args.stock_json.with_name("stock_trends.json")
    snapshot = {
        "source": "Sina CN_MinlineService",
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "note": "分钟线用于静态展示群内提及时间点，不构成投资建议。",
        "items": items,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for item in items if item.get("status") == "ok")
    print(f"[+] stock trends: {ok}/{len(items)} ok -> {output}")


if __name__ == "__main__":
    main()
