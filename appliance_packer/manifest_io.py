"""规范化 JSON（同源核对的字节稳定形态）与通用读写。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def canonical_json(payload: Any, *, indent: int | None = None) -> str:
    """键排序+分隔符固定；indent=None 为紧凑单行（digest 计算用）。"""
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=indent, separators=None if indent else (",", ":"))


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(payload, indent=2) + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
