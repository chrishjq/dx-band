# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

"""Reject bundled model weights and unlicensed media from the source resources."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ROOT = PROJECT_ROOT / "src" / "dxband" / "resources"
EXPECTED_RESOURCE_FILE_COUNT = 63  # docs/resource_license_inventory.md
FIRST_PARTY_IMAGES = {
    "dx_band_icon.png", "dx_band_icon.ico", "dx_band_icon.icns",
    "dx_band_sidebar_logo.png",
    "instruments/bass-clef.svg", "instruments/piano-keys.svg",
}
FIRST_PARTY_VIDEOS = {
    "background_videos/Cieling_Flames_1080p_Loop.mp4",
    "background_videos/Ethereal_Wave_1080p_Loop.mp4",
    "background_videos/Macro_Plex_1080p_Loop.mp4",
}
FIRST_PARTY_PAGES = {
    "web_musician/index.html", "web_singer/index.html",
    "raw_score_preview/index.html",
}
RESOURCE_NOTICES = {
    "controls/LICENSE.txt", "controls/NOTICE.md", "fontawesome/NOTICE.md",
    "instruments/NOTICE.md", "fonts/audience/README.md",
    "web_musician/vendor/jianpurender/LICENSE",
    "web_musician/vendor/jianpurender/NOTICE",
}
AUDIENCE_FONT_FAMILIES = {
    "longcang", "mashanzheng", "zcoolqingkehuangyou", "zcoolxiaowei",
}
FORBIDDEN_SUFFIXES = {
    ".7z", ".aac", ".bin", ".ckpt", ".flac", ".gguf", ".m4v", ".mov", ".mp3",
    ".mp4", ".ogg", ".onnx", ".pem", ".pt", ".pth", ".safetensors", ".tar",
    ".wav", ".webm", ".zip",
}
ALLOWED_VIDEOS = {Path("docs/assets/dx-band-demo.mp4")} | {
    Path("src/dxband/resources") / relative for relative in FIRST_PARTY_VIDEOS
}


def main() -> int:
    problems: list[str] = []
    if (PROJECT_ROOT / ".git").exists():
        tracked = subprocess.run(
            ["git", "-C", str(PROJECT_ROOT), "ls-files", "-z"],
            capture_output=True,
            check=False,
        )
        if tracked.returncode:
            problems.append("无法检查 Git 暂存文件清单")
        else:
            for raw in tracked.stdout.split(b"\0"):
                if not raw:
                    continue
                relative = Path(os.fsdecode(raw))
                if (
                    relative.suffix.lower() in FORBIDDEN_SUFFIXES
                    and relative not in ALLOWED_VIDEOS
                ):
                    problems.append(f"禁止随源码分发的文件：{relative}")
                if relative.parts[0] == "website" or relative.parts[:2] == ("docs", "releases"):
                    problems.append(f"本轮源码快照不包含该目录：{relative}")
    files = [path for path in ROOT.rglob("*") if path.is_file()]
    if len(files) != EXPECTED_RESOURCE_FILE_COUNT:
        problems.append(
            f"资源清单文件数不一致：实际 {len(files)}，登记 {EXPECTED_RESOURCE_FILE_COUNT}"
        )
    for relative in FIRST_PARTY_VIDEOS:
        if not (ROOT / relative).is_file():
            problems.append(f"预设背景视频缺失：{relative}")
    controls_notice = ROOT / "controls" / "NOTICE.md"
    control_attributions = (
        controls_notice.read_text(encoding="utf-8") if controls_notice.is_file() else ""
    )
    for path in files:
        relative = path.relative_to(ROOT).as_posix()
        if path.suffix.lower() in FORBIDDEN_SUFFIXES and relative not in FIRST_PARTY_VIDEOS:
            problems.append(f"禁止随源码分发的文件：{path.relative_to(ROOT)}")
        if path.suffix.lower() in {".ttf", ".otf"} and not (path.parent / "OFL.txt").is_file():
            problems.append(f"字体缺少 OFL.txt：{path.relative_to(ROOT)}")
        parts = path.relative_to(ROOT).parts
        is_font = (
            len(parts) == 4 and parts[:2] == ("fonts", "audience")
            and parts[2] in AUDIENCE_FONT_FAMILIES
            and (path.suffix.lower() == ".ttf" or path.name == "OFL.txt")
        )
        is_controls_icon = (
            len(parts) == 2 and parts[0] == "controls" and path.suffix == ".svg"
        )
        is_fontawesome_icon = (
            len(parts) == 2 and parts[0] == "fontawesome" and path.suffix == ".svg"
        )
        is_vendor_js = relative == "web_musician/vendor/jianpurender/jianpurender.js"
        is_first_party = relative in (
            FIRST_PARTY_IMAGES | FIRST_PARTY_VIDEOS | FIRST_PARTY_PAGES | RESOURCE_NOTICES
        )
        if not (
            is_first_party
            or is_font or is_controls_icon or is_fontawesome_icon or is_vendor_js
        ):
            problems.append(f"资源许可清单未登记：{relative}")
        if (is_controls_icon or is_fontawesome_icon) and (
            "Font Awesome Free 7.2.0" not in path.read_text(encoding="utf-8")
        ):
            problems.append(f"Font Awesome 图标缺少上游版权注释：{relative}")
        if is_controls_icon and f"| `{path.name}` |" not in control_attributions:
            problems.append(f"控件图标缺少逐项来源映射：{relative}")
    vendor = ROOT / "web_musician" / "vendor" / "jianpurender"
    if (vendor / "jianpurender.js").is_file():
        for name in ("LICENSE", "NOTICE"):
            if not (vendor / name).is_file():
                problems.append(f"JianpuRender 缺少 {name}")
    controls = ROOT / "controls"
    if any(controls.glob("*.svg")):
        for name in ("LICENSE.txt", "NOTICE.md"):
            if not (controls / name).is_file():
                problems.append(f"Font Awesome 控件图标缺少 {name}")
    for notice in RESOURCE_NOTICES:
        if not (ROOT / notice).is_file():
            problems.append(f"资源许可清单缺少：{notice}")
    for problem in problems:
        print(problem)
    if problems:
        return 1
    print("源码资源基础检查通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
