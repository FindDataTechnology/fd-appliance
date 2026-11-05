"""组件注册表（领域无关）：bundle 声明的每个组件必须登记可打包分类。

分类两态（lex packer 先例泛化）：
- ``packable``    —— 制品可入包（镜像 tar、数据切片、配置、pack 清单……）；
- ``cloud_locked`` —— 依赖公网 SaaS/云厂商专属服务，客户机房不可用；
  登记时给 substitute（包内替代）或明示移除方向。

未登记组件 = 违规（禁止未分类依赖混入，fail-closed）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PACKABLE = "packable"
CLOUD_LOCKED = "cloud_locked"
_CLASSES = {PACKABLE, CLOUD_LOCKED}


@dataclass
class ComponentSpec:
    name: str
    kind: str
    klass: str = PACKABLE
    substitute: str | None = None
    note: str = ""
    #: 参与公网硬依赖扫描的文本文件（相对 tenant 目录）；二进制制品由镜像扫描另行处理
    scan_files: list[str] | None = None

    def to_dict(self) -> dict:
        out: dict = {"name": self.name, "kind": self.kind, "class": self.klass}
        if self.substitute:
            out["substitute"] = self.substitute
        if self.note:
            out["note"] = self.note
        if self.scan_files:
            out["scan_files"] = self.scan_files
        return out


class ComponentRegistry:
    def __init__(self, specs: dict[str, ComponentSpec]):
        self._specs = specs

    @classmethod
    def load(cls, path: Path | str) -> "ComponentRegistry":
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        specs: dict[str, ComponentSpec] = {}
        for item in payload.get("components") or []:
            klass = str(item.get("class") or PACKABLE)
            if klass not in _CLASSES:
                raise ValueError(f"component {item.get('name')!r}: class must be {'|'.join(sorted(_CLASSES))}, got {klass!r}")
            name = str(item["name"])
            specs[name] = ComponentSpec(
                name=name,
                kind=str(item.get("kind") or "artifact"),
                klass=klass,
                substitute=(str(item["substitute"]) if item.get("substitute") else None),
                note=str(item.get("note") or ""),
                scan_files=[str(p) for p in item["scan_files"]] if item.get("scan_files") else None,
            )
        return cls(specs)

    def require(self, name: str) -> ComponentSpec:
        try:
            return self._specs[name]
        except KeyError:
            raise KeyError(name) from None

    def names(self) -> list[str]:
        return sorted(self._specs)
