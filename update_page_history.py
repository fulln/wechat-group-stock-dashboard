"""Maintain a small static page history manifest for the dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--date", required=True)
    parser.add_argument("--href", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--stock-json", type=Path, required=True)
    parser.add_argument("--version", default="")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    stats = load_json(args.stock_json, {})
    stocks = stats.get("stocks") or []
    entry = {
        "date": args.date,
        "href": args.href,
        "title": args.title,
        "stock_count": len(stocks),
        "mention_count": sum(item.get("count", 0) for item in stocks),
        "market_count": (stats.get("market") or {}).get("count", 0),
        "version": args.version,
    }

    history = load_json(args.history, {"items": []})
    items = [item for item in history.get("items", []) if item.get("date") != args.date]
    items.append(entry)
    items.sort(key=lambda item: item.get("date", ""), reverse=True)
    history = {"items": items[: args.limit]}
    args.history.parent.mkdir(parents=True, exist_ok=True)
    args.history.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[+] page history: {len(history['items'])} items -> {args.history}")


if __name__ == "__main__":
    main()
