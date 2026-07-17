"""Fetch Google Finance quote snapshots for stocks detected in a group export."""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen


GOOGLE_FINANCE_BASE = "https://www.google.com/finance/beta"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"
)

CN_DIGITS = str.maketrans({
    "零": "0",
    "〇": "0",
    "一": "1",
    "二": "2",
    "三": "3",
    "四": "4",
    "五": "5",
    "六": "6",
    "七": "7",
    "八": "8",
    "九": "9",
})

ICON_WORDS = {
    "add",
    "check_indeterminate_small",
    "arrow_downward",
    "arrow_upward",
    "area_chart",
    "stacked_line_chart",
    "monitoring",
    "keyboard_arrow_down",
    "search",
    "close",
    "概览",
    "财报",
    "财务",
    "指标",
    "面积图",
    "比较",
    "所有股票代码",
}


def html_lines(raw: str) -> list[str]:
    text = re.sub(r"<(script|style)[\s\S]*?</\1>", "\n", raw, flags=re.I)
    text = re.sub(r"</(div|span|h1|h2|h3|p|li|td|tr|section|a)>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    rows = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return [line for line in rows if line]


def fetch_quote(symbol: str, timeout: int) -> tuple[str, str]:
    url = f"{GOOGLE_FINANCE_BASE}/quote/{quote(symbol, safe='')}"
    last_error: Exception | None = None
    for attempt in range(3):
        req = Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8", "Connection": "close"})
        try:
            with urlopen(req, timeout=timeout) as resp:
                return url, resp.read().decode("utf-8", "ignore")
        except Exception as exc:  # noqa: BLE001 - retry transient finance page fetches.
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
    raise last_error or RuntimeError(f"failed to fetch {symbol}")


def pct_value(text: str | None) -> float | None:
    if not text:
        return None
    match = re.search(r"([+-]?\d+(?:\.\d+)?)%", text.replace(",", ""))
    return float(match.group(1)) if match else None


def cn_number(text: str | None) -> float | None:
    if not text:
        return None
    value = (
        str(text)
        .translate(CN_DIGITS)
        .replace(",", "")
        .replace("，", "")
        .replace("¥", "")
        .replace("HK$", "")
        .replace("$", "")
        .strip()
    )
    multiplier = 1.0
    if "亿" in value:
        multiplier = 100_000_000
        value = value.replace("亿", "")
    elif "万" in value:
        multiplier = 10_000
        value = value.replace("万", "")
    match = re.search(r"-?\d+(?:\.\d+)?", value)
    return float(match.group(0)) * multiplier if match else None


def first_after(lines: list[str], idx: int, pattern: str, limit: int = 80) -> str:
    rx = re.compile(pattern)
    for line in lines[idx : idx + limit]:
        if rx.search(line):
            return line
    return ""


def stat_after(lines: list[str], label: str) -> str:
    for idx, line in enumerate(lines):
        if line == label and idx + 1 < len(lines):
            return lines[idx + 1]
        if line.startswith(label + "："):
            return line.split("：", 1)[1]
    return ""


def related_block(lines: list[str]) -> list[str]:
    try:
        idx = lines.index("相关股票")
    except ValueError:
        return []
    block: list[str] = []
    for line in lines[idx + 1 : idx + 36]:
        if line in {"新闻报道", "资料", "显示更多内容"}:
            break
        if line not in ICON_WORDS:
            block.append(line)
    return block


def page_news(lines: list[str]) -> list[str]:
    try:
        idx = lines.index("新闻报道")
    except ValueError:
        return []
    rows: list[str] = []
    for line in lines[idx + 1 : idx + 42]:
        if line in {"资料", "显示更多内容"}:
            break
        if line in {"来自全网", "·"} or line in ICON_WORDS:
            continue
        if re.fullmatch(r"\d+[小时前天]+", line):
            continue
        if len(line) >= 12:
            rows.append(line)
        if len(rows) >= 4:
            break
    return rows


def page_profile(lines: list[str]) -> list[str]:
    try:
        idx = lines.index("资料")
    except ValueError:
        return []
    return [line for line in lines[idx + 1 : idx + 10] if len(line) > 12][:2]


def market_direction(percent: str) -> str:
    if percent.startswith("+"):
        return "up"
    if percent.startswith("-"):
        return "down"
    return "neutral"


def related_moves(block: list[str]) -> tuple[int, int]:
    ups = downs = 0
    for line in block:
        value = pct_value(line)
        if value is None:
            continue
        if value > 0:
            ups += 1
        elif value < 0:
            downs += 1
    return ups, downs


def market_label(score: int) -> str:
    if score >= 3:
        return "市场明显偏强"
    if score > 0:
        return "市场小幅偏强"
    if score <= -3:
        return "市场明显偏弱"
    if score < 0:
        return "市场小幅偏弱"
    return "市场中性/分歧"


def build_market_sentiment(item: dict) -> tuple[dict, str]:
    stats = item.get("stats") or {}
    change = item.get("changePercentValue")
    score = 0
    factors: list[str] = []

    if change is not None:
        if change >= 5:
            score += 3
        elif change >= 2:
            score += 2
        elif change > 0:
            score += 1
        elif change <= -5:
            score -= 3
        elif change <= -2:
            score -= 2
        elif change < 0:
            score -= 1
        factors.append(f"当日涨跌幅 {item.get('changePercent')}，价格动量{'偏强' if change > 0 else '偏弱' if change < 0 else '中性'}")

    price = cn_number(item.get("price"))
    high = cn_number(stats.get("最高价"))
    low = cn_number(stats.get("最低价"))
    range_pos = None
    if price is not None and high is not None and low is not None and high > low:
        range_pos = max(0.0, min(1.0, (price - low) / (high - low)))
        if range_pos >= 0.72:
            score += 1
            factors.append(f"收盘/当前价位于日内区间上沿（约 {range_pos:.0%}），承接偏强")
        elif range_pos <= 0.28:
            score -= 1
            factors.append(f"收盘/当前价靠近日内低位（约 {range_pos:.0%}），承接偏弱")
        else:
            factors.append(f"收盘/当前价处于日内区间中部（约 {range_pos:.0%}），方向仍有分歧")

    volume = cn_number(stats.get("成交量"))
    avg_volume = cn_number(stats.get("平均成交量"))
    volume_ratio = None
    if volume is not None and avg_volume:
        volume_ratio = volume / avg_volume
        if volume_ratio >= 1.2:
            if change is not None and change > 0:
                score += 1
                factors.append(f"成交量约为均量 {volume_ratio:.2f} 倍，上涨有放量确认")
            elif change is not None and change < 0:
                score -= 1
                factors.append(f"成交量约为均量 {volume_ratio:.2f} 倍，下跌有放量确认")
            else:
                factors.append(f"成交量约为均量 {volume_ratio:.2f} 倍，但价格未给出方向")
        elif volume_ratio <= 0.7:
            factors.append(f"成交量约为均量 {volume_ratio:.2f} 倍，量能不足，信号可信度打折")
        else:
            factors.append(f"成交量约为均量 {volume_ratio:.2f} 倍，量能接近常态")

    ups, downs = related_moves(item.get("relatedBlock") or [])
    if ups or downs:
        if downs >= ups + 2:
            score -= 1
            factors.append(f"Google Finance 相关股票下跌更多（涨 {ups} / 跌 {downs}），同类情绪偏弱")
        elif ups >= downs + 2:
            score += 1
            factors.append(f"Google Finance 相关股票上涨更多（涨 {ups} / 跌 {downs}），同类情绪偏强")
        else:
            factors.append(f"Google Finance 相关股票涨跌接近（涨 {ups} / 跌 {downs}），同类情绪分歧")

    label = market_label(score)
    if score <= -3:
        action = "明日先看止跌承接和开盘是否继续低走，右侧确认前不把反弹当趋势。"
    elif score < 0:
        action = "明日偏弱修复观察，重点看是否缩量止跌、能否收回日内中位。"
    elif score >= 3:
        action = "明日偏强延续观察，但若高开放量回落，要防短线兑现。"
    elif score > 0:
        action = "明日温和偏强观察，需用量能和相关股同步性确认。"
    else:
        action = "明日按震荡/分歧处理，等待价格和量能给出更清晰方向。"

    if change is None:
        change_word = "未解析到涨跌幅"
    elif change > 0:
        change_word = f"当日上涨 {item.get('changePercent')}"
    elif change < 0:
        change_word = f"当日下跌 {item.get('changePercent')}"
    else:
        change_word = f"当日持平 {item.get('changePercent')}"
    takeaway = f"Google Finance 显示{change_word}，综合量能、日内位置和相关股表现为“{label}”。{action}"
    sentiment = {
        "score": score,
        "label": label,
        "factors": factors,
        "volumeRatio": round(volume_ratio, 3) if volume_ratio is not None else None,
        "rangePosition": round(range_pos, 3) if range_pos is not None else None,
        "relatedUp": ups,
        "relatedDown": downs,
    }
    return sentiment, takeaway


def candidates_for(stock: dict) -> list[dict]:
    name = stock["name"]
    market = stock.get("market")
    code = stock.get("code", "")
    if name == "浪潮":
        return [
            {
                "stockName": name,
                "displayName": "浪潮（浪潮信息候选）",
                "symbol": "000977:SHE",
                "code": "000977",
                "market": "SZ",
                "ambiguity": "群聊检测到“浪潮”简称，语境里出现浪潮信息；此项作为候选，不等同于确认标的。",
            },
            {
                "stockName": name,
                "displayName": "浪潮（浪潮软件候选）",
                "symbol": "600756:SHA",
                "code": "600756",
                "market": "SH",
                "ambiguity": "群聊检测到“浪潮”简称，语境里也提到浪潮软件；此项作为候选，不等同于确认标的。",
            },
        ]
    if name == "中芯国际":
        return [{
            "stockName": name,
            "displayName": "中芯国际A",
            "symbol": "688981:SHA",
            "code": "688981",
            "market": "SH",
            "ambiguity": "群聊标的含 A/H 两地代码；此处优先采集 A 股 688981:SHA。",
        }]
    if market == "SH" and re.fullmatch(r"\d{6}", code):
        symbol = f"{code}:SHA"
    elif market == "SZ" and re.fullmatch(r"\d{6}", code):
        symbol = f"{code}:SHE"
    else:
        return []
    return [{"stockName": name, "displayName": name, "symbol": symbol, "code": code, "market": market}]


def parse_item(candidate: dict, group_stock: dict, raw: str, source_url: str) -> dict:
    lines = html_lines(raw)
    title_match = re.search(r"<title>(.*?)</title>", raw, flags=re.I | re.S)
    page_title = html.unescape(re.sub(r"\s+", " ", title_match.group(1)).strip()) if title_match else ""
    idx = next((i for i, line in enumerate(lines) if candidate["symbol"] in line), -1)
    if idx < 0:
        idx = next((i for i, line in enumerate(lines) if candidate["code"] in line), 0)
    window = [line for line in lines[idx : idx + 90] if line not in ICON_WORDS]
    google_name = next(
        (line for line in window if re.search(r"[\u4e00-\u9fffA-Za-z]", line) and ":" not in line and not re.fullmatch(r"\d{6}", line)),
        candidate["displayName"],
    )
    price = first_after(lines, idx, r"^(?:¥|HK\$|\$)?-?\d[\d,.]*(?:\.\d+)?$")
    change_percent = first_after(lines, idx, r"^[+-]?\d+(?:\.\d+)?%$")
    change_value = pct_value(change_percent)
    timestamp = first_after(lines, idx, r"(GMT|UTC|CNY|HKD|USD)")
    stats = {
        label: stat_after(lines, label)
        for label in ("昨收盘", "昨收", "开盘价", "最高价", "最低价", "市值", "平均成交量", "成交量", "52 周最高价", "52 周最低价", "市盈率", "股息收益率", "每股收益", "流通股数", "员工人数")
        if stat_after(lines, label)
    }
    if "昨收盘" in stats and "昨收" not in stats:
        stats["昨收"] = stats.pop("昨收盘")
    item = {
        **candidate,
        "sourceUrl": source_url,
        "pageTitle": page_title,
        "googleName": google_name,
        "price": price,
        "changePercent": change_percent,
        "changeAmountLine": "",
        "changeDirection": market_direction(change_percent),
        "changePercentValue": change_value,
        "timestamp": timestamp,
        "stats": stats,
        "news": page_news(lines),
        "profile": page_profile(lines),
        "relatedBlock": related_block(lines),
        "status": "ok" if price and change_percent else "partial",
        "group": group_stock,
        "sampledAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    sentiment, takeaway = build_market_sentiment(item)
    item["marketSentiment"] = sentiment
    item["takeaway"] = takeaway
    return item


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("stock_json", type=Path, help="build_stock_mentions.py 输出的 stock_mentions.json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    stats = json.loads(args.stock_json.read_text(encoding="utf-8"))
    items: list[dict] = []
    for stock in stats.get("stocks", []):
        for candidate in candidates_for(stock):
            try:
                source_url, raw = fetch_quote(candidate["symbol"], args.timeout)
                item = parse_item(candidate, stock, raw, source_url)
            except Exception as exc:  # noqa: BLE001 - daily job should keep other symbols moving.
                item = {
                    **candidate,
                    "sourceUrl": f"{GOOGLE_FINANCE_BASE}/quote/{quote(candidate['symbol'], safe='')}",
                    "status": "failed",
                    "error": str(exc),
                    "group": stock,
                    "sampledAt": dt.datetime.now(dt.timezone.utc).isoformat(),
                }
            items.append(item)
            print(f"[{item['status']}] {candidate['displayName']} {candidate['symbol']} {item.get('price', '')} {item.get('changePercent', '')}", file=sys.stderr)

    snapshot = {
        "source": "Google Finance Beta",
        "betaEntryUrl": GOOGLE_FINANCE_BASE,
        "generatedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
        "note": "Google Finance 页面快照；情绪判断只使用 Google Finance 页面中的价格、成交量、日内位置、相关股票和新闻线索，不使用群内偏多/偏空。非投资建议。",
        "items": items,
    }
    output = args.output or args.stock_json.with_name("google_finance_snapshot.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    ok = sum(1 for item in items if item.get("status") == "ok")
    print(f"[+] Google Finance snapshot: {ok}/{len(items)} ok -> {output}")


if __name__ == "__main__":
    main()
