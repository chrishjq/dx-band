# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtGui import QFontDatabase

from dxband.resource_paths import AUDIENCE_FONT_ROOT

DEFAULT_AUDIENCE_FONT_ID = "default"


@dataclass(frozen=True, slots=True)
class AudienceFontResource:
    id: str
    name: str
    family: str
    path: Path | None


class AudienceFontLibrary:
    """注册随应用分发的观众屏艺术字体，并提供稳定的设置标识。"""

    _FONT_SPECS = (
        ("mashanzheng", "马善政毛笔楷体", "MaShanZheng-Regular.ttf"),
        ("longcang", "龙藏体", "LongCang-Regular.ttf"),
        ("zcoolxiaowei", "站酷小薇体", "ZCOOLXiaoWei-Regular.ttf"),
        (
            "zcoolqingkehuangyou",
            "站酷庆科黄油体",
            "ZCOOLQingKeHuangYou-Regular.ttf",
        ),
    )

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or AUDIENCE_FONT_ROOT
        self._resources: tuple[AudienceFontResource, ...] | None = None

    def resources(self) -> tuple[AudienceFontResource, ...]:
        if self._resources is not None:
            return self._resources
        entries = [
            AudienceFontResource(
                id=DEFAULT_AUDIENCE_FONT_ID,
                name="系统默认黑体",
                family="PingFang SC",
                path=None,
            )
        ]
        for resource_id, display_name, filename in self._FONT_SPECS:
            path = self.root / resource_id / filename
            if not path.is_file():
                continue
            font_id = QFontDatabase.addApplicationFont(str(path.resolve()))
            if font_id < 0:
                continue
            families = QFontDatabase.applicationFontFamilies(font_id)
            if not families:
                continue
            entries.append(
                AudienceFontResource(
                    id=resource_id,
                    name=display_name,
                    family=families[0],
                    path=path,
                )
            )
        self._resources = tuple(entries)
        return self._resources

    def find(self, resource_id: str) -> AudienceFontResource:
        resources = self.resources()
        return next(
            (resource for resource in resources if resource.id == resource_id),
            resources[0],
        )
