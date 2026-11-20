# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from pytestqt.qtbot import QtBot

from dxband.ui.pages.library_page import LibraryPage
from dxband.ui.pages.settings_page import SettingsPage
from dxband.ui.public_messages import creation_error_message, public_message


def test_public_message_hides_analysis_implementation_details() -> None:
    fallback = "请重试或检查歌曲文件"
    for message in (
        "正在用 SheetSage2 分析简谱",
        "Beat This! 模型文件不存在",
        "Demucs GPU 分离失败，回退到 CPU",
        "ctc-segmentation 无法启动",
        "model file not found",
        "separating",
        "优化背景视频需要 FFmpeg",
    ):
        assert public_message(message, fallback) == fallback


def test_public_message_preserves_useful_user_facing_errors() -> None:
    assert public_message("请选择歌词文件", "请重试") == "请选择歌词文件"


def test_creation_errors_show_fixed_model_setup_advice() -> None:
    cases = (
        ("未配置 SheetSage2 模型目录", "DX_BAND_SHEETSAGE2_MODEL_DIR"),
        ("Beat This! 模型文件不存在：/private/path", "DX_BAND_BEAT_THIS_CHECKPOINT"),
        ("缺少本机 Demucs htdemucs_6s 权重", "HTDemucs-6s"),
        ("缺少 Fun-ASR 模型代码", "DX_BAND_FUN_ASR_MODEL_CODE"),
        ("缺少本机 Fun-ASR 模型", "DX_BAND_FUN_ASR_MODEL_DIR"),
        ("缺少本机zh歌词对齐模型", "DX_BAND_ALIGNER_ZH_MODEL_DIR"),
        ("缺少en歌词对齐模型文件：/private/path", "DX_BAND_ALIGNER_EN_MODEL_DIR"),
        ("缺少本机yue歌词对齐模型", "DX_BAND_ALIGNER_YUE_MODEL_DIR"),
    )
    for backend_message, setup_hint in cases:
        visible = creation_error_message(backend_message)
        assert setup_hint in visible
        assert "/private/path" not in visible
    assert creation_error_message("Beat This! 模型无法启动") == "歌曲处理失败，请重试"


def test_other_pages_do_not_show_backend_names(qtbot: QtBot) -> None:
    library = LibraryPage()
    settings = SettingsPage()
    qtbot.addWidget(library)
    qtbot.addWidget(settings)

    library.show_error("SheetSage2 Python 环境不存在")
    settings.show_status("上传背景视频失败：FFmpeg 无法启动")

    assert library.status_label.text() == "错误：操作失败，请重试"
    assert settings.status_label.text() == "设置操作失败，请重试"
