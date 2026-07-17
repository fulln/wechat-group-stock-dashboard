"""Mark stock mentions in an exported WeChat group markdown file."""

from __future__ import annotations

import argparse
import html
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from chat_export import Message, clean_text, parse_export


@dataclass(frozen=True)
class Stock:
    name: str
    code: str
    market: str
    aliases: tuple[str, ...]
    confidence: str = "high"
    note: str = ""


STOCKS: tuple[Stock, ...] = (
    Stock("捷成股份", "300182", "SZ", ("捷成", "捷成股份", "300182")),
    Stock("长电科技", "600584", "SH", ("长电", "长电科技", "600584")),
    Stock("昭衍新药", "603127", "SH", ("昭衍", "昭衍新药", "603127")),
    Stock("特一药业", "002728", "SZ", ("特一", "特一药业", "002728")),
    Stock("中公教育", "002607", "SZ", ("中公", "中公教育")),
    Stock("诺德股份", "600110", "SH", ("诺德", "诺德股份")),
    Stock("黄河旋风", "600172", "SH", ("黄河旋风", "黄河")),
    Stock("顺络电子", "002138", "SZ", ("顺络", "顺络电子")),
    Stock("数据港", "603881", "SH", ("数据港",)),
    Stock("黑猫股份", "002068", "SZ", ("黑猫", "黑喵", "黑猫股份")),
    Stock("中国巨石", "600176", "SH", ("中国巨石", "巨石")),
    Stock("英维克", "002837", "SZ", ("英维克",)),
    Stock("工业富联", "601138", "SH", ("工业富联",)),
    Stock("通鼎互联", "002491", "SZ", ("通鼎", "通鼎互联")),
    Stock("中际旭创", "300308", "SZ", ("中际", "中际旭创")),
    Stock("杰华特", "688141", "SH", ("杰华特",)),
    Stock("中天科技", "600522", "SH", ("中天", "中天科技")),
    Stock("兴发集团", "600141", "SH", ("兴发", "兴发集团")),
    Stock("风华高科", "000636", "SZ", ("风华", "风华高科")),
    Stock("通富微电", "002156", "SZ", ("通富微电", "通富")),
    Stock("康强电子", "002119", "SZ", ("康强", "康强电子")),
    Stock("大元泵业", "603757", "SH", ("大元", "大元泵业", "603757")),
    Stock("天娱数科", "002354", "SZ", ("天娱", "天娱数科", "002354")),
    Stock("蓝晓科技", "300487", "SZ", ("蓝晓", "蓝晓科技", "300487")),
    Stock("有研新材", "600206", "SH", ("有研", "有研新材", "600206")),
    Stock("中兴通讯", "000063", "SZ", ("中兴", "中兴通讯", "000063")),
    Stock("江海股份", "002484", "SZ", ("江海", "江海股份", "002484")),
    Stock("美诺华", "603538", "SH", ("美诺", "美诺华", "603538")),
    Stock("飞龙股份", "002536", "SZ", ("飞龙", "飞龙股份", "002536")),
    Stock("梦网科技", "002123", "SZ", ("梦网", "梦网科技", "002123")),
    Stock("深南电路", "002916", "SZ", ("深南电路", "深南", "002916")),
    Stock("澜起科技", "688008", "SH", ("澜起", "澜起科技", "688008")),
    Stock("德明利", "001309", "SZ", ("德明利", "001309")),
    Stock("合金投资", "000633", "SZ", ("合金投资", "000633")),
    Stock("中国铝业", "601600", "SH", ("中国铝业", "中铝", "601600")),
    Stock("浪潮信息", "000977", "SZ", ("浪潮信息", "000977")),
    Stock("浪潮软件", "600756", "SH", ("浪潮软件", "600756")),
    Stock("中芯国际", "688981 / 00981", "SH/HK", ("中芯国际", "中芯")),
    Stock("阿里巴巴", "BABA / 09988", "US/HK", ("阿里巴巴", "阿里")),
    Stock("小米集团", "01810", "HK", ("小米", "小米集团")),
    Stock("金山云", "KC / 03896", "US/HK", ("金山云",)),
    Stock("CoreWeave", "CRWV", "US", ("CRWV", "CoreWeave")),
    Stock("Nebius", "NBIS", "US", ("NBIS", "Nebius")),
    Stock("福达合金", "603045", "SH", ("福达", "福达合金", "603045")),
    Stock("彩虹股份", "600707", "SH", ("彩虹", "彩虹股份", "600707")),
    Stock("浪潮", "待确认", "CN", ("浪潮",), "low", "简称可能对应浪潮信息等"),
    Stock("万通", "待确认", "CN", ("万通",), "low", "简称可能对应万通发展、万通智控等"),
    Stock("中国儒意", "00136", "HK", ("儒意", "中国儒意"), "medium", "港股标的，暂不生成 A 股分时图"),
    Stock("中科", "待确认", "CN", ("中科",), "low", "简称可能对应多个中科系股票"),
    Stock("恒生科技", "指数/ETF", "HK", ("恒生科技",), "medium", "更像指数或相关 ETF，不一定是单只股票"),
    Stock("港股互联网ETF", "ETF", "HK", ("港股互联", "港股互联网", "港股互联网ETF"), "medium", "ETF/指数产品，暂不生成 A 股分时图"),
)


STOCK_BY_ALIAS: list[tuple[str, Stock]] = sorted(
    [(alias, stock) for stock in STOCKS for alias in stock.aliases],
    key=lambda item: len(item[0]),
    reverse=True,
)


def alias_regex(alias: str) -> tuple[str, int]:
    if re.fullmatch(r"\d{6}", alias):
        return rf"(?<!\d){re.escape(alias)}(?!\d)", 0
    if re.fullmatch(r"[A-Za-z0-9.]+", alias):
        return rf"(?<![A-Za-z0-9.]){re.escape(alias)}(?![A-Za-z0-9.])", re.IGNORECASE
    return re.escape(alias), 0

SECTOR_RULES = {
    "光通信/光模块": {
        "stocks": {"通鼎互联", "中际旭创", "工业富联", "顺络电子", "中兴通讯"},
        "keywords": ("光", "光模块", "光板块", "中际", "通鼎", "工业富联", "顺络", "中兴"),
    },
    "半导体/硬科技": {
        "stocks": {"中芯国际", "杰华特", "通富微电", "康强电子", "英维克", "长电科技", "有研新材", "深南电路", "澜起科技", "德明利", "江海股份", "浪潮信息", "浪潮软件"},
        "keywords": ("半导体", "硬科技", "中芯", "杰华特", "通富", "康强", "英维克", "科技", "长电", "有研", "深南", "澜起", "德明利", "江海", "PCB", "pcb"),
    },
    "算力/云": {
        "stocks": {"数据港", "金山云", "CoreWeave", "Nebius", "浪潮", "浪潮信息", "浪潮软件", "中科"},
        "keywords": ("算力", "云", "数据港", "金山云", "CRWV", "NBIS", "浪潮", "中科", "租赁"),
    },
    "材料/化工": {
        "stocks": {"中国巨石", "黄河旋风", "兴发集团", "黑猫股份", "福达合金", "诺德股份", "风华高科", "中国铝业", "合金投资", "蓝晓科技"},
        "keywords": ("巨石", "黄河", "兴发", "黑猫", "黑喵", "福达", "诺德", "风华", "材料", "中铝", "中国铝业", "合金", "蓝晓"),
    },
    "教育/消费": {
        "stocks": {"中公教育", "小米集团", "彩虹股份", "特一药业", "昭衍新药", "美诺华"},
        "keywords": ("中公", "教育", "小米", "彩虹", "旅游", "消费", "K12", "创新药", "医药", "药", "昭衍", "美诺", "特一"),
    },
    "传媒/影视": {
        "stocks": {"捷成股份", "天娱数科", "中国儒意"},
        "keywords": ("传媒", "电影", "捷成", "天娱", "儒意"),
    },
    "液冷/机械": {
        "stocks": {"大元泵业", "飞龙股份"},
        "keywords": ("液冷", "大元", "飞龙", "泵业"),
    },
    "港美股/指数": {
        "stocks": {"阿里巴巴", "小米集团", "金山云", "恒生科技", "CoreWeave", "Nebius", "港股互联网ETF", "中国儒意"},
        "keywords": ("港股", "hk", "香港", "恒生科技", "港股互联", "阿里", "小米", "金山云", "NBIS", "CRWV", "美股"),
    },
}

BULLISH_WORDS = ("红", "涨", "拉", "封板", "起飞", "暴涨", "反弹", "回暖", "强", "抗跌", "稳", "补仓", "加仓", "买", "建仓", "冲", "优秀")
BEARISH_WORDS = ("跌", "绿", "亏", "套", "杀", "跳水", "瀑布", "吐", "破位", "跌停", "难受", "回本无望", "呼吸困难", "不行", "没仓位")
MARKET_WORDS = ("创业板", "指数", "大盘", "市场", "权重", "行情", "普跌", "港股", "恒生科技", "科技", "半导体", "A股", "美股")


def normalize_sender(sender: str) -> str:
    if sender == "me":
        return os.environ.get("CHAT_STOCK_SELF_NAME", sender)
    return sender


def normalize_sender_fields(value):
    if isinstance(value, dict):
        return {
            key: normalize_sender(str(item)) if key in {"sender", "speaker"} and item == "me" else normalize_sender_fields(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [normalize_sender_fields(item) for item in value]
    return value


def find_mentions(text: str) -> list[tuple[str, Stock]]:
    hits: list[tuple[str, Stock]] = []
    occupied: list[range] = []
    for alias, stock in STOCK_BY_ALIAS:
        pattern, flags = alias_regex(alias)
        for match in re.finditer(pattern, text, flags):
            span = range(match.start(), match.end())
            if any(match.start() < r.stop and match.end() > r.start for r in occupied):
                continue
            hits.append((match.group(0), stock))
            occupied.append(span)
    return hits


def classify_signal(text: str) -> dict:
    bull = sum(text.count(word) for word in BULLISH_WORDS)
    bear = sum(text.count(word) for word in BEARISH_WORDS)
    score = bull - bear
    if score > 0:
        label = "偏多"
        key = "bullish"
    elif score < 0:
        label = "偏空"
        key = "bearish"
    else:
        label = "中性"
        key = "neutral"
    return {"key": key, "label": label, "score": score, "bull": bull, "bear": bear}


def sentiment_label(score: int) -> str:
    if score >= 3:
        return "强偏多"
    if score > 0:
        return "偏多"
    if score <= -3:
        return "强偏空"
    if score < 0:
        return "偏空"
    return "中性"


def analyze(messages: list[Message]) -> dict:
    counts: Counter[str] = Counter()
    alias_counts: Counter[str] = Counter()
    speakers: dict[str, set[str]] = defaultdict(set)
    contexts: dict[str, list[dict]] = defaultdict(list)
    stock_signal_counts: dict[str, Counter[str]] = defaultdict(Counter)
    stock_signal_scores: Counter[str] = Counter()

    for msg in messages:
        content = clean_text(msg.content)
        if not content:
            continue
        sender = normalize_sender(msg.sender)
        seen_in_message: set[str] = set()
        for alias, stock in find_mentions(content):
            key = stock.name
            counts[key] += 1
            alias_counts[f"{key}|{alias}"] += 1
            speakers[key].add(sender)
            if key not in seen_in_message:
                signal = classify_signal(content)
                stock_signal_counts[key][signal["key"]] += 1
                stock_signal_scores[key] += signal["score"]
                contexts[key].append({
                    "time": msg.ts.strftime("%H:%M"),
                    "sender": sender,
                    "alias": alias,
                    "signal": signal["label"],
                    "signal_key": signal["key"],
                    "text": content[:96],
                })
            seen_in_message.add(key)

    stock_meta = {s.name: s for s in STOCKS}
    rows = []
    for name, count in counts.most_common():
        stock = stock_meta[name]
        aliases = {
            key.split("|", 1)[1]: n
            for key, n in alias_counts.items()
            if key.startswith(name + "|")
        }
        rows.append({
            "name": stock.name,
            "code": stock.code,
            "market": stock.market,
            "confidence": stock.confidence,
            "note": stock.note,
            "count": count,
            "speakers": len(speakers[name]),
            "aliases": sorted(aliases.items(), key=lambda item: item[1], reverse=True),
            "sentiment": {
                "score": stock_signal_scores[name],
                "label": sentiment_label(stock_signal_scores[name]),
                "bullish": stock_signal_counts[name]["bullish"],
                "bearish": stock_signal_counts[name]["bearish"],
                "neutral": stock_signal_counts[name]["neutral"],
            },
            "contexts": contexts[name],
        })
    return {
        "stocks": rows,
        "emotion": analyze_emotion(messages),
        "sectors": analyze_sectors(messages, rows),
        "market": analyze_market(messages),
    }


def analyze_emotion(messages: list[Message]) -> dict:
    buckets = {
        "bullish": {"label": "偏多/进攻", "count": 0, "examples": []},
        "bearish": {"label": "偏空/防守", "count": 0, "examples": []},
        "neutral": {"label": "中性/观望", "count": 0, "examples": []},
    }
    score = 0
    for msg in messages:
        text = clean_text(msg.content)
        if not text:
            continue
        sender = normalize_sender(msg.sender)
        bull = sum(text.count(word) for word in BULLISH_WORDS)
        bear = sum(text.count(word) for word in BEARISH_WORDS)
        if bull > bear:
            key = "bullish"
            score += bull - bear
        elif bear > bull:
            key = "bearish"
            score -= bear - bull
        else:
            key = "neutral"
        buckets[key]["count"] += 1
        if key != "neutral" and len(buckets[key]["examples"]) < 6:
            buckets[key]["examples"].append({
                "time": msg.ts.strftime("%H:%M"),
                "sender": sender,
                "text": text[:90],
            })
    total_signal = buckets["bullish"]["count"] + buckets["bearish"]["count"]
    if score > 8:
        label = "情绪偏进攻，但分歧不小"
    elif score < -8:
        label = "情绪偏防守，亏损/回撤讨论较多"
    else:
        label = "情绪拉扯，观望和试错并存"
    return {
        "score": score,
        "label": label,
        "total_signal": total_signal,
        "buckets": buckets,
    }


def analyze_sectors(messages: list[Message], stock_rows: list[dict]) -> list[dict]:
    stock_counts = {row["name"]: row["count"] for row in stock_rows}
    stock_by_name = {row["name"]: row for row in stock_rows}
    sector_hits: dict[str, Counter[str]] = {name: Counter() for name in SECTOR_RULES}
    examples: dict[str, list[dict]] = defaultdict(list)

    for msg in messages:
        text = clean_text(msg.content)
        if not text:
            continue
        sender = normalize_sender(msg.sender)
        for sector, rule in SECTOR_RULES.items():
            matched = False
            for stock_name in rule["stocks"]:
                if stock_counts.get(stock_name) and any(alias in text for alias, stock in STOCK_BY_ALIAS if stock.name == stock_name):
                    sector_hits[sector][stock_name] += 1
                    matched = True
            keyword_hits = [kw for kw in rule["keywords"] if kw.lower() in text.lower()]
            if keyword_hits:
                sector_hits[sector]["关键词"] += len(keyword_hits)
                matched = True
            if matched and len(examples[sector]) < 4:
                examples[sector].append({
                    "time": msg.ts.strftime("%H:%M"),
                    "sender": sender,
                    "text": text[:88],
                })

    rows = []
    for sector, counter in sector_hits.items():
        count = sum(counter.values())
        if not count:
            continue
        related_stocks = []
        score = 0
        bullish = 0
        bearish = 0
        neutral = 0
        for stock_name in SECTOR_RULES[sector]["stocks"]:
            row = stock_by_name.get(stock_name)
            if not row:
                continue
            sent = row["sentiment"]
            score += sent["score"]
            bullish += sent["bullish"]
            bearish += sent["bearish"]
            neutral += sent["neutral"]
            related_stocks.append({
                "name": row["name"],
                "code": row["code"],
                "count": row["count"],
                "confidence": row["confidence"],
                "sentiment": sent,
                "clues": row["contexts"],
            })
        related_stocks.sort(key=lambda item: (item["count"], abs(item["sentiment"]["score"])), reverse=True)
        rows.append({
            "name": sector,
            "count": count,
            "leaders": counter.most_common(5),
            "sentiment": {
                "score": score,
                "label": sentiment_label(score),
                "bullish": bullish,
                "bearish": bearish,
                "neutral": neutral,
            },
            "stocks": related_stocks,
            "examples": examples[sector],
        })
    return sorted(rows, key=lambda item: item["count"], reverse=True)


def analyze_market(messages: list[Message]) -> dict:
    rows = []
    hour_counter: Counter[int] = Counter()
    for msg in messages:
        text = clean_text(msg.content)
        if not text:
            continue
        sender = normalize_sender(msg.sender)
        hits = [word for word in MARKET_WORDS if word.lower() in text.lower()]
        if not hits:
            continue
        hour_counter[msg.ts.hour] += 1
        rows.append({
            "time": msg.ts.strftime("%H:%M"),
            "sender": sender,
            "keywords": hits,
            "text": text[:96],
        })
    if rows:
        peak_hour, peak_count = hour_counter.most_common(1)[0]
        summary = f"大盘/指数讨论集中在 {peak_hour:02d}:00，相关消息 {peak_count} 条。"
    else:
        summary = "今天几乎没有明确的大盘/指数讨论。"
    return {
        "count": len(rows),
        "summary": summary,
        "hourly": [{"hour": h, "count": hour_counter.get(h, 0)} for h in range(24)],
        "examples": rows[:14],
    }


def highlight_text(text: str) -> str:
    matches = []
    for alias, stock in STOCK_BY_ALIAS:
        pattern, flags = alias_regex(alias)
        for match in re.finditer(pattern, text, flags):
            matches.append((match.start(), match.end(), match.group(0), stock))
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    selected = []
    last_end = -1
    for item in matches:
        start, end, _, _ = item
        if start < last_end:
            continue
        selected.append(item)
        last_end = end

    out = []
    pos = 0
    for start, end, alias, stock in selected:
        out.append(html.escape(text[pos:start]))
        label = html.escape(f"{stock.name} {stock.code}")
        out.append(
            f'<mark class="stock {stock.confidence}" title="{label}">'
            f"{html.escape(alias)}</mark>"
        )
        pos = end
    out.append(html.escape(text[pos:]))
    return "".join(out)


def render_html(chat_name: str, date: str, messages: list[Message], stats: dict) -> str:
    data = json.dumps(stats, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(chat_name)} · 股票标记</title>
<style>
:root {{
  --bg: #f7f7f3;
  --panel: #fff;
  --ink: #202225;
  --muted: #68707a;
  --line: #dde2d9;
  --green: #13795b;
  --amber: #a86c12;
  --red: #aa3d36;
  --blue: #285f9f;
}}
* {{ box-sizing: border-box; }}
body {{ margin: 0; overflow: hidden; background: var(--bg); color: var(--ink); font: 14px/1.55 -apple-system, BlinkMacSystemFont, "PingFang SC", sans-serif; }}
.shell {{ max-width: 1280px; margin: 0 auto; padding: 86px 24px 24px; }}
.head {{ display: grid; grid-template-columns: minmax(280px, auto) minmax(0, 1fr) auto; gap: 24px; align-items: center; margin-bottom: 16px; }}
h1 {{ margin: 0 0 6px; font-size: 25px; letter-spacing: 0; }}
.sub {{ color: var(--muted); font-size: 13px; }}
.badge {{ background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 7px 10px; white-space: nowrap; }}
.sector-summary {{ min-width: 0; }}
.sector-summary-head {{ display: flex; align-items: baseline; gap: 8px; margin-bottom: 6px; }}
.sector-summary-title {{ font-weight: 750; }}
.sector-summary-count {{ color: var(--muted); font-size: 12px; }}
.sector-summary-list {{ display: flex; gap: 8px; min-width: 0; overflow-x: auto; scrollbar-width: thin; }}
.sector-summary-item {{ flex: 1 0 130px; min-width: 0; max-width: 180px; border: 1px solid var(--line); border-radius: 8px; padding: 6px 8px; background: #fff; }}
.sector-summary-name {{ display: block; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.sector-summary-meta {{ display: block; color: var(--muted); font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.dashboard-layout {{ display: grid; grid-template-columns: minmax(300px, 420px) minmax(0, 1fr); gap: 14px; align-items: stretch; height: calc(100vh - 211px); min-height: 360px; }}
.stock-column,
.main-column {{ min-width: 0; height: 100%; overflow-y: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }}
.history-float {{ position: fixed; right: 22px; top: 16px; width: min(300px, calc(100vw - 32px)); z-index: 20; padding: 0; overflow: hidden; box-shadow: 0 12px 30px rgba(31, 41, 55, 0.12); }}
.history-toggle {{ width: 100%; appearance: none; border: 0; border-bottom: 1px solid var(--line); background: #fff; color: var(--ink); padding: 12px 14px; font: inherit; font-weight: 750; text-align: left; cursor: pointer; }}
.history-toggle:hover {{ background: #f8fbf7; }}
.history-panel {{ display: none; padding: 12px; }}
.history-float.open .history-panel {{ display: block; }}
.history-list {{ display: grid; gap: 8px; }}
.history-extra {{ display: block; margin-bottom: 10px; border: 1px solid #cfe0ef; border-radius: 8px; padding: 10px; background: #f3f8fd; color: var(--blue); text-decoration: none; font-weight: 750; }}
.history-extra:hover {{ background: #eaf3ff; }}
.history-link {{ display: block; border: 1px solid #edf0ea; border-radius: 8px; padding: 9px; color: var(--ink); text-decoration: none; background: #fff; }}
.history-link:hover {{ border-color: #b8c4b9; background: #f8fbf7; }}
.history-link.active {{ border-color: var(--blue); background: #eaf3ff; }}
.history-date {{ font-weight: 750; }}
.history-meta {{ color: var(--muted); font-size: 12px; margin-top: 2px; }}
.card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 16px; }}
h2 {{ margin: 0 0 12px; font-size: 15px; }}
.metric {{ font-size: 28px; line-height: 1; font-weight: 750; }}
.metric small {{ font-size: 12px; color: var(--muted); font-weight: 500; }}
.mini {{ color: var(--muted); font-size: 12px; margin-top: 7px; }}
.stock-control-list {{ display: grid; gap: 12px; margin-top: 10px; }}
.stock-control-group {{ display: grid; gap: 8px; }}
.stock-control-group-head {{ display: flex; justify-content: space-between; align-items: center; gap: 10px; color: var(--muted); font-size: 12px; font-weight: 750; }}
.stock-control-group-head .count {{ font-weight: 500; }}
.stock-control-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(136px, 1fr)); gap: 8px; }}
.stock-control {{ position: relative; appearance: none; border: 1px solid var(--line); border-radius: 8px; background: #fbfcf8; color: var(--ink); padding: 7px 9px; font: inherit; cursor: pointer; text-align: left; min-width: 0; }}
.stock-control:hover {{ border-color: #b8c4b9; background: #f1f6ee; }}
.stock-control.active {{ border-color: #8db6e0; background: linear-gradient(90deg, rgba(40,95,159,0.10), rgba(255,255,255,0) 42%), #f7fbff; box-shadow: 0 3px 10px rgba(40, 95, 159, 0.10); }}
.stock-control.active::before {{ content: ""; position: absolute; left: 7px; top: 9px; bottom: 9px; width: 3px; border-radius: 999px; background: var(--blue); }}
.stock-control.active::after {{ content: ""; position: absolute; right: 8px; top: 10px; width: 7px; height: 7px; border-radius: 999px; background: var(--blue); box-shadow: 0 0 0 3px rgba(40, 95, 159, 0.12); }}
.stock-control.active .stock-control-title,
.stock-control.active .stock-control-sub {{ padding-left: 9px; padding-right: 14px; }}
.stock-control.up {{ border-color: #bfe5ce; background: #fbfffc; }}
.stock-control.down {{ border-color: #efc6c1; background: #fffafa; }}
.stock-control.neutral {{ border-color: var(--line); background: #fbfcf8; }}
.stock-control-title {{ display: block; font-weight: 750; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.stock-control-sub {{ display: block; color: var(--muted); font-size: 12px; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.stock-control-sub .bullish {{ color: var(--green); }}
.stock-control-sub .bearish {{ color: var(--red); }}
.stock-control-sub .neutral {{ color: var(--muted); }}
.section-list {{ display: grid; gap: 8px; margin-top: 10px; }}
.section-item {{ border-left: 3px solid #d9e4dc; padding-left: 8px; color: var(--muted); font-size: 12px; }}
.relation-card {{ margin-bottom: 14px; }}
.association-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 12px; }}
.chain-card {{ border: 1px solid #edf0ea; border-radius: 8px; padding: 12px; background: #fff; }}
.chain-head {{ display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; }}
.chain-title {{ font-weight: 750; }}
.chain-meta {{ color: var(--muted); font-size: 12px; text-align: right; }}
.gf-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; }}
.gf-detail {{ border: 1px solid #edf0ea; border-radius: 8px; padding: 12px; background: #fff; }}
.gf-detail-top {{ display: flex; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
.gf-title {{ font-weight: 750; font-size: 16px; }}
.gf-price {{ font-size: 22px; font-weight: 800; }}
.gf-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(130px, 1fr)); gap: 8px; margin-top: 10px; }}
.gf-stat {{ border: 1px solid #edf0ea; border-radius: 8px; padding: 8px; }}
.gf-stat b {{ display: block; font-size: 12px; color: var(--muted); font-weight: 500; }}
.gf-takeaway {{ margin-top: 10px; padding: 10px; border-left: 3px solid #b9cbdc; background: #f8fbff; }}
.gf-link {{ color: var(--blue); text-decoration: none; }}
.gf-link:hover {{ text-decoration: underline; }}
.trend-grid {{ display: grid; grid-template-columns: 1fr; gap: 12px; }}
.trend-card {{ border: 1px solid #edf0ea; border-radius: 8px; padding: 12px; background: #fff; }}
.trend-card[hidden] {{ display: none; }}
.trend-card.active {{ border-color: var(--blue); box-shadow: 0 0 0 2px rgba(40, 95, 159, 0.08); }}
.trend-head {{ display: flex; justify-content: space-between; gap: 12px; align-items: flex-start; margin-bottom: 8px; }}
.trend-title {{ font-weight: 750; }}
.trend-meta {{ color: var(--muted); font-size: 12px; text-align: right; }}
.trend-svg {{ width: 100%; height: 260px; display: block; border: 1px solid #edf0ea; border-radius: 8px; background: #fbfcf8; }}
.trend-axis {{ stroke: #d9e4dc; stroke-width: 1; }}
.trend-line {{ fill: none; stroke: var(--blue); stroke-width: 2.2; }}
.trend-avg {{ fill: none; stroke: #9aa5ad; stroke-width: 1.3; stroke-dasharray: 4 4; }}
.trend-base {{ stroke: #cfd8cf; stroke-width: 1; stroke-dasharray: 2 5; }}
.trend-marker {{ stroke: #fff; stroke-width: 1.5; cursor: pointer; }}
.trend-marker.bullish {{ fill: var(--green); }}
.trend-marker.bearish {{ fill: var(--red); }}
.trend-marker.neutral {{ fill: var(--amber); }}
.trend-label {{ font-size: 10px; fill: var(--muted); }}
.trend-marker-group {{ cursor: pointer; }}
.trend-crosshair {{ stroke: #5f6f78; stroke-width: 1; stroke-dasharray: 4 4; opacity: 0; pointer-events: none; }}
.trend-svg.crosshair-on .trend-crosshair {{ opacity: 0.75; }}
.trend-cross-label {{ font-size: 11px; font-weight: 750; paint-order: stroke; stroke: #fbfcf8; stroke-width: 4px; stroke-linejoin: round; opacity: 0; pointer-events: none; }}
.trend-svg.crosshair-on .trend-cross-label {{ opacity: 1; }}
.trend-pct.up {{ color: var(--green); fill: var(--green); }}
.trend-pct.down {{ color: var(--red); fill: var(--red); }}
.trend-pct.flat {{ color: var(--muted); fill: var(--muted); }}
.trend-notes {{ display: grid; gap: 6px; margin-top: 8px; }}
.trend-note {{ border-left: 3px solid #d9e4dc; padding-left: 8px; color: var(--muted); font-size: 12px; }}
.trend-note.flash {{ border-left-color: var(--blue); background: #f4f9ff; }}
.trend-note summary {{ cursor: pointer; color: var(--ink); }}
.trend-note-full {{ margin-top: 4px; color: var(--muted); }}
.stock-link {{ border-top: 1px solid #edf0ea; padding: 8px 0; }}
.stock-link:first-of-type {{ border-top: 0; }}
.stock-link-head {{ display: flex; justify-content: space-between; gap: 10px; }}
.stock-link-title {{ font-weight: 650; }}
.clue-list {{ display: grid; gap: 5px; margin-top: 6px; color: var(--muted); font-size: 12px; }}
.signal {{ display: inline-block; border-radius: 7px; padding: 1px 6px; font-size: 12px; border: 1px solid var(--line); }}
.signal.bullish {{ color: var(--green); background: #edf8f1; border-color: #bfe5ce; }}
.signal.bearish {{ color: var(--red); background: #fff0ee; border-color: #efc6c1; }}
.signal.neutral {{ color: var(--muted); background: #f4f5f1; }}
#stocks {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }}
.stock-row {{ border: 1px solid #edf0ea; border-radius: 8px; padding: 12px; background: #fff; }}
.stock-top {{ display: flex; justify-content: space-between; gap: 12px; }}
.stock-name {{ font-weight: 700; }}
.code {{ color: var(--blue); font-variant-numeric: tabular-nums; }}
.meta {{ color: var(--muted); font-size: 12px; }}
.low .stock-name::after {{ content: " 待确认"; color: var(--amber); font-weight: 500; font-size: 12px; }}
.medium .stock-name::after {{ content: " 指数/ETF"; color: var(--blue); font-weight: 500; font-size: 12px; }}
.aliases {{ margin-top: 4px; color: var(--muted); font-size: 12px; }}
.examples {{ margin-top: 7px; display: grid; gap: 5px; color: var(--muted); font-size: 12px; }}
.example {{ border-left: 3px solid #d9e4dc; padding-left: 8px; }}
mark.stock {{ border-radius: 5px; padding: 1px 4px; color: #111; }}
mark.high {{ background: #c8f0da; box-shadow: inset 0 -1px 0 var(--green); }}
mark.medium {{ background: #d8eaff; box-shadow: inset 0 -1px 0 var(--blue); }}
mark.low {{ background: #ffe7ba; box-shadow: inset 0 -1px 0 var(--amber); }}
.legend {{ display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 12px; }}
.legend span {{ border: 1px solid var(--line); border-radius: 8px; padding: 4px 8px; background: #fbfcf8; }}
@media (max-width: 920px) {{
  body {{ overflow: auto; }}
  .shell {{ padding: 16px; }}
  .head {{ display: block; }}
  .sector-summary {{ margin-top: 12px; }}
  .sector-summary-item {{ flex-basis: 140px; }}
  .badge {{ display: inline-block; margin-top: 10px; }}
  .dashboard-layout {{ grid-template-columns: 1fr; height: auto; min-height: 0; }}
  .stock-column,
  .main-column {{ height: auto; overflow: visible; }}
  .history-float {{ top: auto; bottom: 16px; right: 16px; }}
  #stocks {{ grid-template-columns: 1fr; }}
}}
</style>
</head>
<body>
<main class="shell">
  <div class="head">
    <div>
      <h1>{html.escape(chat_name)}</h1>
      <div class="sub">{html.escape(date)} · 股票提及标记 · 非投资建议</div>
    </div>
    <section class="sector-summary" aria-labelledby="sectorSummaryTitle">
      <div class="sector-summary-head">
        <span class="sector-summary-title" id="sectorSummaryTitle">3 板块</span>
        <span class="sector-summary-count" id="sectorMetric"></span>
      </div>
      <div class="sector-summary-list" id="sectorList"></div>
    </section>
    <div class="badge" id="summaryBadge"></div>
  </div>
  <div class="dashboard-layout">
    <aside class="stock-column">
      <section class="card">
        <h2>1 股票</h2>
        <div class="metric" id="stockMetric">--</div>
        <div class="mini" id="stockMini"></div>
        <div class="stock-control-list" id="stockControls"></div>
      </section>
    </aside>
    <div class="main-column">
      <section class="card relation-card">
        <h2>股票分时 / 群聊标记</h2>
        <div class="mini" id="trendScope">折线为分钟收盘价，圆点为群内提到该标的的时间；点击左侧股票卡片可切换对应折线图</div>
        <div id="trendCharts" class="trend-grid"></div>
      </section>
      <section class="card relation-card" id="gfSection" hidden>
        <div class="gf-head">
          <div>
            <h2>Google Finance 快照 / 明日线索</h2>
            <div class="mini" id="gfMeta"></div>
          </div>
          <a class="gf-link" id="gfEntry" href="https://www.google.com/finance/beta" target="_blank" rel="noopener">打开 Google Finance</a>
        </div>
        <div id="gfDetail"></div>
      </section>
    </div>
  </div>
  <section class="card history-float open" id="historySection" hidden>
    <button class="history-toggle" id="historyToggle" type="button">历史记录</button>
    <div class="history-panel">
      <a class="history-extra" id="speakerHistoryLink" href="#" hidden>人物股票图谱</a>
      <div class="mini">最近 10 个页面</div>
      <div id="pageHistory" class="history-list"></div>
    </div>
  </section>
</main>
<script>
const S = {data};
function esc(v) {{
  return String(v ?? '').replace(/[&<>"']/g, ch => ({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[ch]));
}}
function normalizeHistoryHref(href) {{
  if (!href || href.startsWith('#') || href.startsWith('http://') || href.startsWith('https://') || href.startsWith('/')) return href || '#';
  const isDateSegment = part => part.length === 10 && part[4] === '-' && part[7] === '-' &&
    Number.isFinite(Number(part.slice(0, 4))) && Number.isFinite(Number(part.slice(5, 7))) && Number.isFinite(Number(part.slice(8, 10)));
  if (window.location.protocol === 'file:' && window.location.pathname.split('/').some(isDateSegment)) {{
    return `../${{href}}`;
  }}
  if (window.location.protocol === 'file:') return href;
  return `/${{href.replace(/^\\.\\//, '')}}`;
}}
function versionedHref(item) {{
  const href = normalizeHistoryHref(item.href || '#');
  if (!item.version || href.includes('?') || href.startsWith('#')) return href;
  return `${{href}}?v=${{encodeURIComponent(item.version)}}`;
}}
function pageHistoryUrl() {{
  if (window.location.protocol === 'file:') {{
    const isDateSegment = part => part.length === 10 && part[4] === '-' && part[7] === '-';
    return window.location.pathname.split('/').some(isDateSegment) ? '../page_history.json' : 'page_history.json';
  }}
  return '/page_history.json';
}}
async function loadLatestPageHistory(fallbackItems) {{
  try {{
    const response = await fetch(pageHistoryUrl(), {{ cache: 'no-store' }});
    if (!response.ok) return fallbackItems;
    const data = await response.json();
    return Array.isArray(data?.items) ? data.items : fallbackItems;
  }} catch (_err) {{
    return fallbackItems;
  }}
}}
function signalClass(score) {{
  if (score > 0) return 'bullish';
  if (score < 0) return 'bearish';
  return 'neutral';
}}
function gfSignal(direction) {{
  if (direction === 'up') return 'bullish';
  if (direction === 'down') return 'bearish';
  return 'neutral';
}}
function stockKey(item) {{
  return `${{item.market || ''}}:${{item.code || ''}}`;
}}
function shortText(value, limit) {{
  const chars = Array.from(String(value || ''));
  return chars.length > limit ? `${{chars.slice(0, limit).join('')}}...` : chars.join('');
}}
let activeStockKey = '';
let activeStockName = '';
let renderGfDetailFn = null;
function setActiveStock(item) {{
  activeStockKey = stockKey(item);
  activeStockName = item.displayName || item.stockName || item.name || item.code || '';
  applyTrendFilter();
}}
function syncStockControls(item) {{
  const key = stockKey(item);
  document.querySelectorAll('.stock-control').forEach(button => {{
    button.classList.toggle('active', button.dataset.stockKey === key);
  }});
}}
function selectDashboardStock(item) {{
  setActiveStock(item);
  syncStockControls(item);
  if (renderGfDetailFn) renderGfDetailFn(item);
}}
function renderStockControls(items) {{
  const root = document.getElementById('stockControls');
  root.innerHTML = '';
  const groups = [
    ['up', '上涨'],
    ['down', '下跌'],
    ['neutral', '平盘 / 未取价'],
  ];
  const bucketed = {{ up: [], down: [], neutral: [] }};
  items.forEach(item => {{
    const direction = item.changeDirection === 'up' || item.changeDirection === 'down' ? item.changeDirection : 'neutral';
    bucketed[direction].push(item);
  }});
  groups.forEach(([key, label]) => {{
    const rows = bucketed[key];
    if (!rows.length) return;
    const group = document.createElement('div');
    group.className = 'stock-control-group';
    group.innerHTML = `
      <div class="stock-control-group-head">
        <span>${{label}}</span>
        <span class="count">${{rows.length}} 个</span>
      </div>
      <div class="stock-control-grid"></div>
    `;
    const grid = group.querySelector('.stock-control-grid');
    rows.forEach((item, index) => {{
      const button = document.createElement('button');
      button.type = 'button';
      button.className = `stock-control ${{key}}`;
      button.dataset.stockKey = stockKey(item);
      const price = item.price || `${{item.market || ''}} ${{item.code || ''}}`.trim();
      const change = item.changePercent || `${{item.count ?? 0}} 次提及`;
      const signal = gfSignal(item.changeDirection);
      const labelText = item.marketSentiment?.label || item.sentiment?.label || '未计算';
      button.innerHTML = `
        <span class="stock-control-title">${{esc(item.displayName || item.stockName || item.name)}}</span>
        <span class="stock-control-sub">${{esc(price)}} · <span class="${{signal}}">${{esc(change)}}</span> · ${{esc(labelText)}}</span>
      `;
      button.addEventListener('click', () => selectDashboardStock(item));
      grid.appendChild(button);
    }});
    root.appendChild(group);
  }});
}}
function applyTrendFilter() {{
  const root = document.getElementById('trendCharts');
  if (!root) return;
  const cards = [...root.querySelectorAll('.trend-card')];
  if (!cards.length) return;
  let matched = false;
  cards.forEach(card => {{
    const isActive = !activeStockKey || card.dataset.stockKey === activeStockKey;
    card.hidden = !isActive;
    card.classList.toggle('active', Boolean(activeStockKey && isActive));
    if (isActive) matched = true;
  }});
  if (!matched) {{
    cards.forEach(card => {{
      card.hidden = false;
      card.classList.remove('active');
    }});
  }}
  const scope = document.getElementById('trendScope');
  if (scope) {{
    scope.textContent = matched && activeStockName
      ? `当前选择：${{activeStockName}}。十字线跟随鼠标并吸附到折线交点，交点旁显示涨跌幅和附近发言；点击圆点可定位原文。`
      : '折线为分钟收盘价，圆点为群内提到该标的的时间；点击左侧股票卡片可切换对应折线图';
  }}
}}
document.getElementById('summaryBadge').textContent = `${{S.stocks.length}} 个标的 / ${{S.stocks.reduce((n, s) => n + s.count, 0)}} 次提及`;
document.getElementById('sectorMetric').textContent = `${{S.sectors.length}} 个板块 · 横向滚动查看全部`;
S.sectors.forEach(sec => {{
  const item = document.createElement('div');
  item.className = 'sector-summary-item';
  const leaders = sec.leaders.slice(0, 2).map(([name, n]) => `${{name}}×${{n}}`).join('、');
  item.innerHTML = `
    <span class="sector-summary-name">${{esc(sec.name)}}</span>
    <span class="sector-summary-meta">${{esc(sec.count)}} 次${{leaders ? ` · ${{esc(leaders)}}` : ''}}</span>
  `;
  document.getElementById('sectorList').appendChild(item);
}});
const gf = S.google_finance;

document.getElementById('stockMetric').innerHTML = `${{S.stocks.length}} <small>标的</small>`;
document.getElementById('stockMini').textContent = `${{S.stocks.reduce((n, s) => n + s.count, 0)}} 次提及${{S.google_finance ? ' · Google Finance 选择联动' : ''}}`;

const speakerHistoryLink = document.getElementById('speakerHistoryLink');
if (S.speaker_dashboard_href) {{
  speakerHistoryLink.href = normalizeHistoryHref(S.speaker_dashboard_href);
  speakerHistoryLink.hidden = false;
}}
function renderPageHistory(pageHistory) {{
  if (!pageHistory.length) return;
  const section = document.getElementById('historySection');
  const rootHistory = document.getElementById('pageHistory');
  const toggle = document.getElementById('historyToggle');
  section.hidden = false;
  if (!toggle.dataset.bound) {{
    toggle.addEventListener('click', () => section.classList.toggle('open'));
    toggle.dataset.bound = '1';
  }}
  rootHistory.replaceChildren();
  pageHistory.slice(0, 10).forEach(item => {{
    const link = document.createElement('a');
    link.className = `history-link ${{item.date === S.page_history?.current_date ? 'active' : ''}}`;
    link.href = versionedHref(item);
    link.innerHTML = `
      <div class="history-date">${{esc(item.date || '未知日期')}}</div>
      <div class="history-meta">${{esc(item.stock_count ?? '--')}} 标的 · ${{esc(item.mention_count ?? '--')}} 次提及 · 大盘 ${{esc(item.market_count ?? '--')}} 条</div>
    `;
    rootHistory.appendChild(link);
  }});
}}
loadLatestPageHistory(S.page_history?.items || []).then(renderPageHistory);

if (gf?.items?.length) {{
  const section = document.getElementById('gfSection');
  const detail = document.getElementById('gfDetail');
  section.hidden = false;
  document.getElementById('gfEntry').href = gf.betaEntryUrl || 'https://www.google.com/finance/beta';
  const updated = gf.generatedAt ? new Date(gf.generatedAt).toLocaleString('zh-CN', {{ hour12: false }}) : '未知时间';
  document.getElementById('gfMeta').textContent = `${{gf.source || 'Google Finance'}} · 采集 ${{gf.items.length}} 个结果 · 更新时间 ${{updated}} · 非投资建议`;

  renderGfDetailFn = function renderGfDetail(item) {{
    const group = item.group || {{}};
    const marketSentiment = item.marketSentiment || {{}};
    const statKeys = ['昨收', '开盘价', '最高价', '最低价', '市值', '成交量', '平均成交量', '52 周最高价', '52 周最低价'];
    const statsHtml = statKeys
      .filter(k => item.stats && item.stats[k])
      .map(k => `<div class="gf-stat"><b>${{esc(k)}}</b>${{esc(item.stats[k])}}</div>`)
      .join('');
    const factorHtml = (marketSentiment.factors || []).map(n => `<div class="section-item">${{esc(n)}}</div>`).join('');
    const newsHtml = (item.news || []).slice(0, 3).map(n => `<div class="section-item">${{esc(n)}}</div>`).join('');
    const profileHtml = (item.profile || []).slice(0, 2).map(n => `<div class="section-item">${{esc(n)}}</div>`).join('');
    detail.innerHTML = `
      <div class="gf-detail">
        <div class="gf-detail-top">
          <div>
            <div class="gf-title">${{esc(item.displayName || item.stockName)}} <span class="code">${{esc(item.symbol)}}</span></div>
            <div class="meta">${{esc(item.googleName || '')}} · ${{esc(item.timestamp || '时间未解析')}}${{item.ambiguity ? ' · ' + esc(item.ambiguity) : ''}}</div>
          </div>
          <div>
            <div class="gf-price">${{esc(item.price || '--')}}</div>
            <div class="signal ${{gfSignal(item.changeDirection)}}">${{esc(item.changePercent || '--')}} ${{esc(item.changeAmountLine || '')}}</div>
          </div>
        </div>
        <div class="meta" style="margin-top:8px">Google Finance 情绪：<span class="signal ${{signalClass(marketSentiment.score || 0)}}">${{esc(marketSentiment.label || '未计算')}} ${{(marketSentiment.score || 0) > 0 ? '+' : ''}}${{esc(marketSentiment.score ?? 0)}}</span></div>
        <div class="gf-takeaway">${{esc(item.takeaway || '')}}</div>
        <div class="meta" style="margin-top:8px">聊天来源：${{esc(group.count ?? 0)}} 次提及（不参与本段情绪判断） · <a class="gf-link" href="${{esc(item.sourceUrl)}}" target="_blank" rel="noopener">Google Finance 页面</a></div>
        <div class="gf-grid">${{statsHtml}}</div>
        ${{factorHtml ? `<div class="section-list" style="margin-top:10px"><div class="meta">Google Finance 判断因子</div>${{factorHtml}}</div>` : ''}}
        ${{profileHtml ? `<div class="section-list" style="margin-top:10px">${{profileHtml}}</div>` : ''}}
        ${{newsHtml ? `<div class="section-list" style="margin-top:10px"><div class="meta">页面新闻线索</div>${{newsHtml}}</div>` : ''}}
      </div>
    `;
  }};
}}
const selectorItems = gf?.items?.length ? gf.items : S.stocks;
renderStockControls(selectorItems);
if (selectorItems.length) selectDashboardStock(selectorItems[0]);

function minuteValue(time) {{
  const [h, m] = String(time || '').split(':').map(Number);
  return Number.isFinite(h) && Number.isFinite(m) ? h * 60 + m : null;
}}
function pathFromPoints(points, xOf, yOf, field) {{
  return points
    .filter(p => Number.isFinite(p[field]))
    .map((p, i) => `${{i ? 'L' : 'M'}}${{xOf(p)}} ${{yOf(p[field])}}`)
    .join(' ');
}}
function nearestPoint(points, time) {{
  const target = minuteValue(time);
  if (target == null || !points.length) return null;
  let best = points[0], bestDelta = Infinity;
  points.forEach(p => {{
    const mv = minuteValue(p.time);
    if (mv == null) return;
    const delta = Math.abs(mv - target);
    if (delta < bestDelta) {{
      best = p;
      bestDelta = delta;
    }}
  }});
  return best;
}}
function priceBase(item, points) {{
  const explicit = Number(item.preClose);
  if (Number.isFinite(explicit) && explicit > 0) return explicit;
  const first = points.find(p => Number.isFinite(p.close) && p.close > 0);
  return first ? first.close : null;
}}
function pctChange(value, base) {{
  if (!Number.isFinite(value) || !Number.isFinite(base) || base <= 0) return null;
  return ((value - base) / base) * 100;
}}
function pctText(value) {{
  if (!Number.isFinite(value)) return '--';
  const sign = value > 0 ? '+' : '';
  return `${{sign}}${{value.toFixed(2)}}%`;
}}
function pctTone(value) {{
  if (!Number.isFinite(value) || Math.abs(value) < 0.005) return 'flat';
  return value > 0 ? 'up' : 'down';
}}
function nearestPointByMinute(points, targetMinute) {{
  let best = points[0], bestDelta = Infinity;
  points.forEach(point => {{
    const minute = minuteValue(point.time);
    if (minute == null) return;
    const delta = Math.abs(minute - targetMinute);
    if (delta < bestDelta) {{
      best = point;
      bestDelta = delta;
    }}
  }});
  return best;
}}
function markerSummaryNear(markers, point) {{
  const pointMinute = minuteValue(point?.time);
  if (pointMinute == null) return '';
  let best = null, bestDelta = Infinity;
  (markers || []).forEach(marker => {{
    const markerMinute = minuteValue(marker.time);
    if (markerMinute == null) return;
    const delta = Math.abs(markerMinute - pointMinute);
    if (delta < bestDelta) {{
      best = marker;
      bestDelta = delta;
    }}
  }});
  if (!best || bestDelta > 2) return '';
  return `${{best.sender || '未知'}}：${{shortText(best.text || '', 18)}}`;
}}
function markerNoteHtml(marker, noteId, point, base) {{
  const text = String(marker.text || '');
  const isLong = Array.from(text).length > 42;
  const pct = point ? pctChange(point.close, base) : null;
  const priceMeta = point
    ? ` · 价格 ${{esc(point.close)}} · <span class="trend-pct ${{pctTone(pct)}}">${{esc(pctText(pct))}}</span>`
    : '';
  const head = `${{esc(marker.time || '')}} ${{esc(marker.sender || '未知')}} <span class="signal ${{esc(marker.signal_key || 'neutral')}}">${{esc(marker.signal || '中性')}}</span>${{priceMeta}}`;
  if (isLong) {{
    return `
      <details class="trend-note" data-note-id="${{esc(noteId)}}">
        <summary>${{head}}：${{esc(shortText(text, 42))}}</summary>
        <div class="trend-note-full">${{esc(text)}}</div>
      </details>
    `;
  }}
  return `<div class="trend-note" data-note-id="${{esc(noteId)}}">${{head}}：${{esc(text || '无文本')}}</div>`;
}}
function renderTrendCharts() {{
  const root = document.getElementById('trendCharts');
  const items = (S.stock_trends?.items || []).filter(item => item.points?.length);
  if (!items.length) {{
    root.innerHTML = '<div class="meta">暂无分钟线数据</div>';
    return;
  }}
  items.forEach((item, index) => {{
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
    const xOf = p => {{
      const mv = minuteValue(p.time);
      return left + ((mv - minMinute) / Math.max(1, maxMinute - minMinute)) * (w - left - right);
    }};
    const yOf = value => top + ((yMax - value) / Math.max(0.0001, yMax - yMin)) * (h - top - bottom);
    const linePath = pathFromPoints(points, xOf, yOf, 'close');
    const avgPath = pathFromPoints(points, xOf, yOf, 'avg');
    const endPct = pctChange(points[points.length - 1].close, basePrice);
    const baseLine = Number.isFinite(basePrice) && basePrice >= yMin && basePrice <= yMax
      ? `<line class="trend-base" x1="${{left}}" y1="${{yOf(basePrice).toFixed(1)}}" x2="${{w - right}}" y2="${{yOf(basePrice).toFixed(1)}}"></line>`
      : '';
    const notePrefix = `trend-note-${{stockKey(item).replace(/[^a-z0-9]/gi, '-')}}`;
    const markerGroups = (item.markers || []).map((m, markerIndex) => {{
      const point = nearestPoint(points, m.time);
      if (!point) return '';
      const pct = pctChange(point.close, basePrice);
      const x = xOf(point);
      const y = yOf(point.close);
      const noteId = `${{notePrefix}}-${{markerIndex}}`;
      return `
        <g class="trend-marker-group" data-note-id="${{esc(noteId)}}" tabindex="0">
          <circle class="trend-marker ${{esc(m.signal_key || 'neutral')}}" cx="${{x.toFixed(1)}}" cy="${{y.toFixed(1)}}" r="5"></circle>
          <title>${{esc(`${{m.time}} ${{m.sender || ''}} [${{m.signal || ''}}] ${{m.text || ''}} · 价格 ${{point.close}} · ${{pctText(pct)}}`)}}</title>
        </g>
      `;
    }}).join('');
    const noteHtml = (item.markers || []).map((m, markerIndex) => markerNoteHtml(m, `${{notePrefix}}-${{markerIndex}}`, nearestPoint(points, m.time), basePrice)).join('');
    const card = document.createElement('div');
    card.className = 'trend-card';
    card.dataset.stockKey = stockKey(item);
    card.innerHTML = `
      <div class="trend-head">
        <div>
          <div class="trend-title">${{esc(item.displayName || item.stockName)}} <span class="code">${{esc(item.code)}}</span></div>
          <div class="meta">${{esc(item.quoteName || '')}} · ${{points.length}} 个分钟点 · ${{(item.markers || []).length}} 个发言标记 · 昨收基准 ${{basePrice ? basePrice.toFixed(2) : '--'}}</div>
        </div>
        <div class="trend-meta">${{esc(points[0].time)}} - ${{esc(points[points.length - 1].time)}}<br>低 ${{minPrice.toFixed(2)}} / 高 ${{maxPrice.toFixed(2)}} · <span class="trend-pct ${{pctTone(endPct)}}">${{pctText(endPct)}}</span></div>
      </div>
      <svg class="trend-svg" viewBox="0 0 ${{w}} ${{h}}" role="img" aria-label="${{esc(item.displayName || item.stockName)}} 分时折线图">
        <line class="trend-axis" x1="${{left}}" y1="${{top}}" x2="${{left}}" y2="${{h - bottom}}"></line>
        <line class="trend-axis" x1="${{left}}" y1="${{h - bottom}}" x2="${{w - right}}" y2="${{h - bottom}}"></line>
        <line class="trend-crosshair trend-crosshair-v" x1="${{left}}" y1="${{top}}" x2="${{left}}" y2="${{h - bottom}}"></line>
        <line class="trend-crosshair trend-crosshair-h" x1="${{left}}" y1="${{h - bottom}}" x2="${{w - right}}" y2="${{h - bottom}}"></line>
        <line class="trend-axis" x1="${{left}}" y1="${{yOf(maxPrice).toFixed(1)}}" x2="${{w - right}}" y2="${{yOf(maxPrice).toFixed(1)}}" opacity="0.5"></line>
        <line class="trend-axis" x1="${{left}}" y1="${{yOf(minPrice).toFixed(1)}}" x2="${{w - right}}" y2="${{yOf(minPrice).toFixed(1)}}" opacity="0.5"></line>
        ${{baseLine}}
        <text class="trend-label" x="6" y="${{yOf(maxPrice).toFixed(1)}}">${{maxPrice.toFixed(2)}}</text>
        <text class="trend-label" x="6" y="${{yOf(minPrice).toFixed(1)}}">${{minPrice.toFixed(2)}}</text>
        <text class="trend-label" x="${{left}}" y="${{h - 8}}">${{esc(points[0].time)}}</text>
        <text class="trend-label" x="${{(w - right - 36)}}" y="${{h - 8}}">${{esc(points[points.length - 1].time)}}</text>
        <path class="trend-avg" d="${{avgPath}}"></path>
        <path class="trend-line" d="${{linePath}}"></path>
        ${{markerGroups}}
        <text class="trend-cross-label trend-pct flat" x="${{left + 8}}" y="${{top + 14}}"></text>
      </svg>
      <div class="trend-notes">${{noteHtml || '<div class="trend-note">暂无发言标记</div>'}}</div>
    `;
    card.addEventListener('click', event => {{
      const group = event.target.closest('.trend-marker-group');
      if (!group) return;
      const note = card.querySelector(`.trend-note[data-note-id="${{group.dataset.noteId}}"]`);
      if (!note) return;
      if (note.tagName === 'DETAILS') note.open = true;
      note.classList.add('flash');
      note.scrollIntoView({{ block: 'nearest', behavior: 'smooth' }});
      setTimeout(() => note.classList.remove('flash'), 1100);
    }});
    const svg = card.querySelector('.trend-svg');
    const crossV = card.querySelector('.trend-crosshair-v');
    const crossH = card.querySelector('.trend-crosshair-h');
    const crossLabel = card.querySelector('.trend-cross-label');
    svg.addEventListener('mousemove', event => {{
      const rect = svg.getBoundingClientRect();
      const rawX = Math.max(left, Math.min(w - right, ((event.clientX - rect.left) / rect.width) * w));
      const targetMinute = minMinute + ((rawX - left) / Math.max(1, w - left - right)) * Math.max(1, maxMinute - minMinute);
      const point = nearestPointByMinute(points, targetMinute);
      const x = xOf(point);
      const y = yOf(point.close);
      const pct = pctChange(point.close, basePrice);
      const summary = markerSummaryNear(item.markers || [], point);
      const label = `${{point.time}} ${{point.close}} ${{pctText(pct)}}${{summary ? ' · ' + summary : ''}}`;
      const labelX = Math.max(left + 4, Math.min(x + 8, w - right - 230));
      const labelY = Math.max(top + 14, Math.min(y - 10, h - bottom - 8));
      crossV.setAttribute('x1', x.toFixed(1));
      crossV.setAttribute('x2', x.toFixed(1));
      crossH.setAttribute('y1', y.toFixed(1));
      crossH.setAttribute('y2', y.toFixed(1));
      crossLabel.setAttribute('x', labelX.toFixed(1));
      crossLabel.setAttribute('y', labelY.toFixed(1));
      crossLabel.setAttribute('class', `trend-cross-label trend-pct ${{pctTone(pct)}}`);
      crossLabel.textContent = label;
      svg.classList.add('crosshair-on');
    }});
    svg.addEventListener('mouseleave', () => svg.classList.remove('crosshair-on'));
    root.appendChild(card);
  }});
  applyTrendFilter();
}}
renderTrendCharts();
</script>
</body>
</html>
"""


def render_markdown(chat_name: str, date: str, stats: dict) -> str:
    lines = [f"# {chat_name} 四维分析", "", f"- 日期: {date}", f"- 标的数: {len(stats['stocks'])}", ""]

    lines.append("## 1 股票")
    lines.append("| 标的 | 代码 | 市场 | 提及 | 人数 | 情绪 | 别名 | 置信 |")
    lines.append("| --- | --- | --- | ---: | ---: | --- | --- | --- |")
    for stock in stats["stocks"]:
        aliases = "、".join(f"{a}×{n}" for a, n in stock["aliases"])
        confidence = stock["confidence"]
        if stock["note"]:
            confidence += f"（{stock['note']}）"
        lines.append(
            f"| {stock['name']} | {stock['code']} | {stock['market']} | {stock['count']} | "
            f"{stock['speakers']} | {stock['sentiment']['label']} {stock['sentiment']['score']:+d} | {aliases} | {confidence} |"
        )

    lines.append("")
    lines.append("## 2 情绪")
    emotion = stats["emotion"]
    lines.append(f"- 情绪分: {emotion['score']}")
    lines.append(f"- 判断: {emotion['label']}")
    lines.append(f"- 偏多/进攻消息: {emotion['buckets']['bullish']['count']}")
    lines.append(f"- 偏空/防守消息: {emotion['buckets']['bearish']['count']}")
    for key in ("bearish", "bullish"):
        bucket = emotion["buckets"][key]
        lines.append("")
        lines.append(f"### {bucket['label']}")
        for item in bucket["examples"]:
            lines.append(f"- {item['time']} {item['sender']}: {item['text']}")

    lines.append("")
    lines.append("## 3 板块")
    lines.append("| 板块 | 命中 | 情绪 | 代表项 |")
    lines.append("| --- | ---: | --- | --- |")
    for sector in stats["sectors"]:
        leaders = "、".join(f"{name}×{count}" for name, count in sector["leaders"])
        lines.append(f"| {sector['name']} | {sector['count']} | {sector['sentiment']['label']} {sector['sentiment']['score']:+d} | {leaders} |")

    lines.append("")
    lines.append("### 板块-股票-情绪线索")
    for sector in stats["sectors"]:
        lines.append("")
        lines.append(f"#### {sector['name']}（{sector['sentiment']['label']} {sector['sentiment']['score']:+d}）")
        for stock in sector["stocks"]:
            sent = stock["sentiment"]
            lines.append(f"- {stock['name']} {stock['code']}: {stock['count']} 次，{sent['label']} {sent['score']:+d}（多 {sent['bullish']} / 空 {sent['bearish']} / 中 {sent['neutral']}）")
            for clue in stock["clues"][:3]:
                lines.append(f"  - {clue['time']} {clue['sender']} [{clue['signal']}]: {clue['text']}")

    lines.append("")
    lines.append("## 4 大盘")
    lines.append(f"- 相关消息: {stats['market']['count']}")
    lines.append(f"- 摘要: {stats['market']['summary']}")
    for item in stats["market"]["examples"][:10]:
        lines.append(f"- {item['time']} {item['sender']}: {item['text']}")

    lines.append("")
    lines.append("## 样例上下文")
    for stock in stats["stocks"]:
        lines.append("")
        lines.append(f"### {stock['name']}（{stock['sentiment']['label']} {stock['sentiment']['score']:+d}）")
        for ctx in stock["contexts"]:
            lines.append(f"- {ctx['time']} {ctx['sender']} [{ctx['signal']}]: {ctx['text']}")
    lines.append("")
    lines.append("> 自动标记结果仅用于聊天统计，不构成投资建议。")
    return "\n".join(lines)


def load_google_finance_snapshot(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Google Finance 快照 JSON 无法解析: {path} ({exc})") from exc
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise SystemExit(f"Google Finance 快照格式不正确: {path}")
    return normalize_sender_fields(data)


def load_page_history(path: Path, current_date: str) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"页面记录 JSON 无法解析: {path} ({exc})") from exc
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"页面记录格式不正确: {path}")
    return {"current_date": current_date, "items": items[:10]}


def load_stock_trends(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"股票分钟线 JSON 无法解析: {path} ({exc})") from exc
    items = data.get("items")
    if not isinstance(items, list):
        raise SystemExit(f"股票分钟线格式不正确: {path}")
    return normalize_sender_fields(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--google-finance", type=Path, help="Google Finance 快照 JSON，默认读取导出文件同目录 google_finance_snapshot.json")
    parser.add_argument("--no-google-finance", action="store_true", help="不要读取 Google Finance 快照，用于每日任务的第一阶段标的识别")
    parser.add_argument("--page-history", type=Path, help="页面记录 JSON，最多展示最近 10 个页面")
    parser.add_argument("--stock-trends", type=Path, help="股票分钟线 JSON，用于分时折线和发言标记")
    parser.add_argument("--speaker-dashboard-href", default="", help="人物股票图谱入口，例如 speakers.html")
    args = parser.parse_args()

    chat_name, _header_count, messages = parse_export(args.input)
    date = messages[0].ts.strftime("%Y-%m-%d") if messages else ""
    stats = analyze(messages)
    if not args.no_google_finance:
        google_finance_path = args.google_finance or args.input.with_name("google_finance_snapshot.json")
        google_finance = load_google_finance_snapshot(google_finance_path)
        if google_finance:
            stats["google_finance"] = google_finance
    if args.page_history:
        page_history = load_page_history(args.page_history, date)
        if page_history:
            stats["page_history"] = page_history
    if args.stock_trends:
        stock_trends = load_stock_trends(args.stock_trends)
        if stock_trends:
            stats["stock_trends"] = stock_trends
    if args.speaker_dashboard_href:
        stats["speaker_dashboard_href"] = args.speaker_dashboard_href

    html_out = args.html or args.input.with_name("stock_mentions.html")
    json_out = args.json or args.input.with_name("stock_mentions.json")
    md_out = args.markdown or args.input.with_name("stock_mentions.md")

    html_out.parent.mkdir(parents=True, exist_ok=True)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    md_out.parent.mkdir(parents=True, exist_ok=True)
    html_out.write_text(render_html(chat_name, date, messages, stats), encoding="utf-8")
    json_out.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out.write_text(render_markdown(chat_name, date, stats), encoding="utf-8")

    total_mentions = sum(item["count"] for item in stats["stocks"])
    print(f"[+] {len(messages)} messages, {len(stats['stocks'])} stocks, {total_mentions} mentions")
    print(f"    html: {html_out}")
    print(f"    json: {json_out}")
    print(f"    markdown: {md_out}")


if __name__ == "__main__":
    main()
