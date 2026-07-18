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


TEMPLATE_DIR = Path(__file__).with_name("templates")


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


def render_template(template_name: str, replacements: dict[str, str]) -> str:
    template = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
    for token, value in replacements.items():
        template = template.replace(token, value)
    return template


def render_html(chat_name: str, date: str, messages: list[Message], stats: dict) -> str:
    data = json.dumps(stats, ensure_ascii=False).replace("</", "<\\/")
    script = render_template("stock_mentions.js", {"__DATA__": data})
    return render_template(
        "stock_mentions.html",
        {
            "__CHAT_NAME__": html.escape(chat_name),
            "__DATE__": html.escape(date),
            "__SCRIPT__": script,
        },
    )


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
    return {"current_date": current_date, "items": items[:15]}


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


def load_analysis(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"分析 JSON 无法解析: {path} ({exc})") from exc
    required = {"stocks", "emotion", "sectors", "market"}
    if not isinstance(data, dict) or not required.issubset(data):
        missing = ", ".join(sorted(required - set(data) if isinstance(data, dict) else required))
        raise SystemExit(f"分析 JSON 格式不正确: {path}（缺少 {missing}）")
    return normalize_sender_fields(data)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("--html", type=Path)
    parser.add_argument("--json", type=Path)
    parser.add_argument("--markdown", type=Path)
    parser.add_argument("--google-finance", type=Path, help="Google Finance 快照 JSON，默认读取导出文件同目录 google_finance_snapshot.json")
    parser.add_argument("--no-google-finance", action="store_true", help="不要读取 Google Finance 快照，用于每日任务的第一阶段标的识别")
    parser.add_argument("--page-history", type=Path, help="页面记录 JSON，最多展示最近 15 个页面")
    parser.add_argument("--stock-trends", type=Path, help="股票分钟线 JSON，用于分时折线和发言标记")
    parser.add_argument("--speaker-dashboard-href", default="", help="人物股票图谱入口，例如 speakers.html")
    parser.add_argument("--analysis-json", type=Path, help="外部语义分析 JSON；提供时跳过内置词典/规则分析")
    args = parser.parse_args()

    chat_name, _header_count, messages = parse_export(args.input)
    date = messages[0].ts.strftime("%Y-%m-%d") if messages else ""
    stats = load_analysis(args.analysis_json) if args.analysis_json else analyze(messages)
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
