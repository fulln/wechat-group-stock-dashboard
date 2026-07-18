"""Generate dashboard stock analysis by asking Codex to read the full chat context."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from collections import Counter
from pathlib import Path


RAW_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["stocks", "emotion", "sectors", "market"],
    "properties": {
        "stocks": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "code", "market", "confidence", "note", "contexts"],
                "properties": {
                    "name": {"type": "string"},
                    "code": {"type": "string"},
                    "market": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "note": {"type": "string"},
                    "contexts": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["time", "sender", "alias", "signal", "text"],
                            "properties": {
                                "time": {"type": "string"},
                                "sender": {"type": "string"},
                                "alias": {"type": "string"},
                                "signal": {"type": "string", "enum": ["偏多", "偏空", "中性"]},
                                "text": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "emotion": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "score", "label", "bullish_count", "bearish_count", "neutral_count",
                "bullish_examples", "bearish_examples",
            ],
            "properties": {
                "score": {"type": "integer"},
                "label": {"type": "string"},
                "bullish_count": {"type": "integer"},
                "bearish_count": {"type": "integer"},
                "neutral_count": {"type": "integer"},
                "bullish_examples": {"$ref": "#/$defs/examples"},
                "bearish_examples": {"$ref": "#/$defs/examples"},
            },
        },
        "sectors": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["name", "stock_names"],
                "properties": {
                    "name": {"type": "string"},
                    "stock_names": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "market": {
            "type": "object",
            "additionalProperties": False,
            "required": ["count", "summary", "examples"],
            "properties": {
                "count": {"type": "integer"},
                "summary": {"type": "string"},
                "examples": {"$ref": "#/$defs/examples"},
            },
        },
    },
    "$defs": {
        "examples": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["time", "sender", "text"],
                "properties": {
                    "time": {"type": "string"},
                    "sender": {"type": "string"},
                    "text": {"type": "string"},
                },
            },
        },
    },
}


PROMPT = """读取 {chat_path}，对完整微信群聊做语义股票复盘。
必须结合上下文判断实体、跨消息指代和情绪，禁止用关键词、正则或内置股票词典直接匹配。
只记录能落到具体证券或明确 IPO 标的的讨论；板块、指数、基金、期货、汽车、商品和人名等
非证券语境不要伪装成个股。图片无法看到内容时不要猜。简称需解析为规范证券名和准确代码；
有歧义则降低 confidence 并在 note 说明。contexts 可包含紧邻的指代延续消息，每个对象最多保留
8 条关键上下文。context.time 只写 HH:MM；context.alias 必须是消息里实际出现的股票简称，若该消息
仅通过上下文指代该股票则写“指代延续”，绝不能写发言人。emotion 和 market 是对当日完整文本的
语义估计。仅输出符合 schema 的 JSON，
不要修改任何文件。
"""


def signal_key(label: str) -> str:
    return {"偏多": "bullish", "偏空": "bearish"}.get(label, "neutral")


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


def normalize_security_fields(item: dict) -> dict:
    code = str(item.get("code") or "")
    market = str(item.get("market") or "")
    match = re.search(r"(?<!\d)(\d{6})(?!\d)", code)
    if not match:
        return item
    base_code = match.group(1)
    market_upper = market.upper()
    sh_hint = code.upper().endswith(".SH") or any(token in market_upper for token in ("SH", "SSE", "沪", "科创"))
    sz_hint = code.upper().endswith(".SZ") or any(token in market_upper for token in ("SZ", "深", "创业"))
    mainland_generic = market_upper in {"A股", "CN", "中国A股"}
    if (sh_hint or mainland_generic) and base_code.startswith(("600", "601", "603", "605", "688", "689")):
        return {**item, "code": base_code, "market": "SH"}
    if (sz_hint or mainland_generic) and base_code.startswith(("000", "001", "002", "003", "300", "301")):
        return {**item, "code": base_code, "market": "SZ"}
    return item


def normalize_analysis(raw: dict) -> dict:
    stocks = []
    for raw_item in raw.get("stocks", []):
        item = normalize_security_fields(raw_item)
        contexts = []
        for ctx in item["contexts"]:
            time = str(ctx.get("time") or "")
            contexts.append({
                **ctx,
                "time": time[-5:] if len(time) >= 5 else time,
                "signal_key": signal_key(str(ctx.get("signal") or "")),
            })
        signals = Counter(ctx["signal_key"] for ctx in contexts)
        score = signals["bullish"] - signals["bearish"]
        aliases = Counter(str(ctx.get("alias") or item["name"]) for ctx in contexts)
        stocks.append({
            **item,
            "count": len(contexts),
            "speakers": len({str(ctx.get("sender") or "未知") for ctx in contexts}),
            "aliases": aliases.most_common(),
            "sentiment": {
                "score": score,
                "label": sentiment_label(score),
                "bullish": signals["bullish"],
                "bearish": signals["bearish"],
                "neutral": signals["neutral"],
            },
            "contexts": contexts,
        })

    stock_by_name = {stock["name"]: stock for stock in stocks}
    sectors = []
    for raw_sector in raw.get("sectors", []):
        sector_stocks = [stock_by_name[name] for name in raw_sector["stock_names"] if name in stock_by_name]
        score = sum(stock["sentiment"]["score"] for stock in sector_stocks)
        sentiment = {
            "score": score,
            "label": sentiment_label(score),
            "bullish": sum(stock["sentiment"]["bullish"] for stock in sector_stocks),
            "bearish": sum(stock["sentiment"]["bearish"] for stock in sector_stocks),
            "neutral": sum(stock["sentiment"]["neutral"] for stock in sector_stocks),
        }
        sectors.append({
            "name": raw_sector["name"],
            "count": sum(stock["count"] for stock in sector_stocks),
            "leaders": sorted(
                [[stock["name"], stock["count"]] for stock in sector_stocks], key=lambda row: row[1], reverse=True
            ),
            "sentiment": sentiment,
            "stocks": [{
                "name": stock["name"],
                "code": stock["code"],
                "count": stock["count"],
                "confidence": stock["confidence"],
                "sentiment": stock["sentiment"],
                "clues": stock["contexts"],
            } for stock in sector_stocks],
            "examples": [
                {key: ctx[key] for key in ("time", "sender", "text")}
                for stock in sector_stocks for ctx in stock["contexts"]
            ][:4],
        })

    emotion = raw["emotion"]
    market = raw["market"]
    hourly_counts = Counter(int(item["time"][:2]) for item in market["examples"] if len(item.get("time", "")) >= 2)
    return {
        "analysis_method": "codex_semantic_context_review",
        "analysis_note": "由 Codex 阅读完整群聊并基于上下文识别；未使用别名词典或规则直接匹配。",
        "stocks": stocks,
        "emotion": {
            "score": emotion["score"],
            "label": emotion["label"],
            "total_signal": emotion["bullish_count"] + emotion["bearish_count"] + emotion["neutral_count"],
            "buckets": {
                "bullish": {"label": "偏多/进攻", "count": emotion["bullish_count"], "examples": emotion["bullish_examples"]},
                "bearish": {"label": "偏空/防守", "count": emotion["bearish_count"], "examples": emotion["bearish_examples"]},
                "neutral": {"label": "中性/观望", "count": emotion["neutral_count"], "examples": []},
            },
        },
        "sectors": sectors,
        "market": {
            "count": market["count"],
            "summary": market["summary"],
            "hourly": [{"hour": hour, "count": hourly_counts[hour]} for hour in range(24)],
            "examples": market["examples"],
        },
    }


def run_codex(chat_path: Path, raw_output: Path, codex_bin: str, model: str) -> None:
    with tempfile.NamedTemporaryFile("w", suffix=".json", encoding="utf-8") as schema_file:
        json.dump(RAW_SCHEMA, schema_file, ensure_ascii=False)
        schema_file.flush()
        command = [
            codex_bin, "exec", "--ephemeral", "--ignore-user-config", "-s", "read-only",
            "-C", str(Path.cwd()), "--output-schema", schema_file.name, "-o", str(raw_output),
        ]
        if model:
            command[2:2] = ["-m", model]
        subprocess.run(command + [PROMPT.format(chat_path=chat_path)], check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("chat", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--raw-output", type=Path)
    parser.add_argument("--codex-bin", default=os.environ.get("CODEX_BIN", "codex"))
    parser.add_argument("--model", default=os.environ.get("CODEX_MODEL", "gpt-5.4-mini"))
    args = parser.parse_args()

    raw_output = args.raw_output or args.output.with_name("codex_raw_analysis.json")
    raw_output.parent.mkdir(parents=True, exist_ok=True)
    run_codex(args.chat, raw_output, args.codex_bin, args.model)
    raw = json.loads(raw_output.read_text(encoding="utf-8"))
    analysis = normalize_analysis(raw)
    args.output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] Codex semantic analysis: {len(analysis['stocks'])} stocks -> {args.output}")


if __name__ == "__main__":
    main()
