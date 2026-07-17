"""Helpers for parsing WeChat-style markdown chat exports."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


MSG_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})\] (?:(.+?): )?(.*)$")
HEADER_COUNT_RE = re.compile(r"\*\*消息数量:\*\*\s*(\d+)")
HEADER_NAME_RE = re.compile(r"^# 聊天记录:\s*(.+)$", re.MULTILINE)


@dataclass
class Message:
    ts: datetime
    sender: str
    content: str


def parse_export(path: Path) -> tuple[str, int | None, list[Message]]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    name_match = HEADER_NAME_RE.search(text)
    count_match = HEADER_COUNT_RE.search(text)
    chat_name = name_match.group(1).strip() if name_match else path.stem
    header_count = int(count_match.group(1)) if count_match else None

    messages: list[Message] = []
    current: Message | None = None
    for raw in text.splitlines():
        match = MSG_RE.match(raw)
        if match:
            date, hm, sender, content = match.groups()
            sender = (sender or "系统").strip()
            current = Message(
                ts=datetime.strptime(f"{date} {hm}", "%Y-%m-%d %H:%M"),
                sender=sender,
                content=content.strip(),
            )
            messages.append(current)
        elif current and raw.strip():
            current.content += "\n" + raw.strip()
    return chat_name, header_count, messages


def clean_text(content: str) -> str:
    content = re.sub(r"<[^>]+>", " ", content)
    content = re.sub(r"\(local_id=\d+\)", " ", content)
    content = re.sub(r"https?://\S+", " ", content)
    content = re.sub(r"↳\s*回复.+", " ", content)
    content = re.sub(r"\[[^\]]{1,12}\]", " ", content)
    return re.sub(r"\s+", " ", content).strip()
