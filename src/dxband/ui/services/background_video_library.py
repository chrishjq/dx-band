# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import logging
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from PySide6.QtCore import QStandardPaths

from dxband.resource_paths import BACKGROUND_VIDEO_ROOT
from dxband.workers.command import subprocess_creation_flags

NO_BACKGROUND_ID = "none"
SUPPORTED_VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".m4v", ".webm"})
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class BackgroundVideoResource:
    id: str
    name: str
    path: Path | None
    built_in: bool

    @property
    def deletable(self) -> bool:
        return not self.built_in and self.path is not None


class BackgroundVideoLibrary:
    """枚举内置背景视频，并管理用户上传到应用数据目录的资源。"""

    # 保留原资源 ID，避免升级后用户已保存的背景选择失效。
    _BUILT_IN_VIDEOS: ClassVar[dict[str, tuple[str, str]]] = {
        "Cieling_Flames_4K_Motion_Background_Loop.mp4": (
            "穹顶火焰", "Cieling_Flames_1080p_Loop.mp4"
        ),
        "Ethereal_Wave_4K_Motion_Background_Loop.mp4": (
            "空灵波浪", "Ethereal_Wave_1080p_Loop.mp4"
        ),
        "Macro_Plex_4K_Motion_Background_Loop.mp4": (
            "微距脉络", "Macro_Plex_1080p_Loop.mp4"
        ),
    }

    def __init__(
        self,
        *,
        built_in_root: Path | None = None,
        user_root: Path | None = None,
    ) -> None:
        self.built_in_root = built_in_root or BACKGROUND_VIDEO_ROOT
        app_data = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
        self.user_root = user_root or Path(app_data) / "background_videos"

    def resources(self) -> tuple[BackgroundVideoResource, ...]:
        entries = [
            BackgroundVideoResource(
                id=NO_BACKGROUND_ID,
                name="无背景视频",
                path=None,
                built_in=True,
            )
        ]
        for resource_id, (display_name, filename) in self._BUILT_IN_VIDEOS.items():
            path = self.built_in_root / filename
            if path.is_file():
                entries.append(
                    BackgroundVideoResource(
                        id=f"builtin:{resource_id}",
                        name=f"{display_name}（系统预设）",
                        path=path,
                        built_in=True,
                    )
                )
        if self.user_root.is_dir():
            for path in sorted(
                (
                    candidate
                    for candidate in self.user_root.iterdir()
                    if candidate.is_file()
                    and not candidate.name.startswith(".")
                    and candidate.suffix.lower() in SUPPORTED_VIDEO_SUFFIXES
                ),
                key=lambda candidate: candidate.name.casefold(),
            ):
                entries.append(
                    BackgroundVideoResource(
                        id=f"user:{path.name}",
                        name=f"{path.stem}（用户上传）",
                        path=path,
                        built_in=False,
                    )
                )
        return tuple(entries)

    def import_file(self, source: Path) -> BackgroundVideoResource:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise ValueError("选择的背景视频文件不存在")
        if source.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
            raise ValueError("仅支持 MP4、MOV、M4V 或 WebM 视频")
        ffmpeg = shutil.which("ffmpeg")
        if ffmpeg is None:
            raise ValueError("当前环境缺少视频处理组件，无法优化背景视频")
        self.user_root.mkdir(parents=True, exist_ok=True)
        destination = self._available_destination(f"{source.stem}.mp4")
        temporary = destination.with_name(f".{destination.stem}.uploading.mp4")
        try:
            completed = subprocess.run(
                [
                    ffmpeg,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    str(source),
                    "-map",
                    "0:v:0",
                    "-vf",
                    "fps=15,scale=1920:1080:flags=lanczos:"
                    "force_original_aspect_ratio=decrease:force_divisible_by=2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "veryfast",
                    "-crf",
                    "23",
                    "-pix_fmt",
                    "yuv420p",
                    "-an",
                    "-sn",
                    "-dn",
                    "-movflags",
                    "+faststart",
                    str(temporary),
                ],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
                creationflags=subprocess_creation_flags(),
            )
            if completed.returncode != 0 or not temporary.is_file():
                detail = completed.stderr.strip()[-500:] or "视频无法转换"
                logger.warning("背景视频优化失败：%s", detail)
                raise ValueError("优化背景视频失败，请检查视频文件后重试")
            os.replace(temporary, destination)
        except subprocess.TimeoutExpired as exc:
            raise ValueError("优化背景视频超时，请使用较短的视频") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return BackgroundVideoResource(
            id=f"user:{destination.name}",
            name=f"{destination.stem}（用户上传）",
            path=destination,
            built_in=False,
        )

    def delete(self, resource_id: str) -> None:
        resource = self.find(resource_id)
        if resource is None:
            raise ValueError("背景视频资源不存在")
        if not resource.deletable or resource.path is None:
            raise ValueError("系统预设背景不能删除")
        resource.path.unlink(missing_ok=False)

    def find(self, resource_id: str) -> BackgroundVideoResource | None:
        return next(
            (resource for resource in self.resources() if resource.id == resource_id),
            None,
        )

    def playable_resources(self) -> tuple[BackgroundVideoResource, ...]:
        return tuple(resource for resource in self.resources() if resource.path is not None)

    def _available_destination(self, filename: str) -> Path:
        candidate = self.user_root / filename
        index = 2
        while candidate.exists():
            candidate = self.user_root / f"{Path(filename).stem} ({index}){Path(filename).suffix}"
            index += 1
        return candidate
