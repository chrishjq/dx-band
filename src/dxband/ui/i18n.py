# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only
# ruff: noqa: E501

"""Translate the existing desktop widgets without modifying song or lyric data.

The original interface text is Chinese. Only known UI strings are translated;
unknown strings, including user content, pass through unchanged. App-owned widgets
and status updates are refreshed while the English UI is active.
"""

import re
from collections.abc import Callable
from functools import lru_cache, partial
from weakref import WeakKeyDictionary

from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QGroupBox,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QPlainTextEdit,
    QSpinBox,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from dxband.ui.render.output_window import OutputWindow
from dxband.ui.widgets.output_screen_button import OutputScreenButton
from dxband.ui.widgets.track_mute_button import TrackMuteButton

ENGLISH: dict[str, str] = {
    "大象乐队工作站": "Elephant Band Workstation",
    "大象乐队工作站 · DX Band": "Elephant Band Workstation · DX Band",
    "工作区": "Workspace",
    "播放控制": "Playback",
    "歌曲库": "Song Library",
    "设置": "Settings",
    "创建歌曲": "Create Song",
    "返回歌曲库": "Back to Song Library",
    "播放列表": "Playlist",
    "语言": "Language",
    "简体中文": "简体中文",
    "工作站、音频设备与演出显示 · 更改自动保存": "Workstation, audio devices, and performance displays · Changes save automatically",
    "通用与音频": "General and Audio",
    "管理本地歌曲库和监听设备": "Manage the local song library and audio output",
    "歌曲库目录": "Song Library Folder",
    "选择歌曲资料库目录": "Choose a song library folder",
    "选择…": "Choose…",
    "音频输出设备": "Audio Output Device",
    "刷新": "Refresh",
    "重新扫描音频输出设备": "Rescan audio output devices",
    "系统默认设备": "System Default Device",
    "观众屏视觉": "Audience Screen Appearance",
    "管理背景素材并预览观众屏字幕字体": "Manage backgrounds and preview audience subtitles",
    "字幕字体": "Subtitle Font",
    "背景资源": "Background Videos",
    "添加": "Add",
    "移除": "Remove",
    "画面监看": "Preview",
    "无背景视频": "None",
    "字幕字体预览": "Subtitle font preview",
    "视频按窗口尺寸拉伸铺满 · 字幕位置按歌曲随机": "Video fills the window · Subtitle position varies by song",
    "支持 MP4、MOV、M4V、WebM · 上传后自动优化为最高 1080p/15 FPS · 系统预设不可删除": "MP4, MOV, M4V, WebM · Imports optimized to 1080p/15 FPS · Built-in videos cannot be removed",
    "导入音频与歌词，生成可演出的六轨歌曲包": "Import audio and lyrics to create a six-stem performance package",
    "歌曲信息与素材": "Song Details and Media",
    "选择源歌曲": "Choose Audio File",
    "选择歌词": "Choose Lyrics",
    "每行输入一句歌词，无需时间戳": "Enter one lyric line per row; timestamps are not required",
    "自动判断（粤语请手选）": "Auto-detect (select Cantonese manually)",
    "国语": "Mandarin",
    "粤语": "Cantonese",
    "英文": "English",
    "源歌曲音频": "Source Audio",
    "LRC 歌词文件": "LRC Lyrics File",
    "或输入歌词文本": "Or Enter Lyrics",
    "歌曲名": "Song Title",
    "歌手": "Singer",
    "歌手屏": "Singer Screen",
    "观众屏": "Audience Screen",
    "乐手屏": "Musician Screen",
    "歌手屏（双击或 F11 全屏）": "Singer Screen (double-click or F11 for full screen)",
    "观众屏（双击或 F11 全屏）": "Audience Screen (double-click or F11 for full screen)",
    "乐手屏（双击或 F11 全屏）": "Musician Screen (double-click or F11 for full screen)",
    "歌手屏（F11 全屏）": "Singer Screen (F11 for full screen)",
    "乐手屏（F11 全屏）": "Musician Screen (F11 for full screen)",
    "网页歌手屏": "Web Singer Screen",
    "网页乐手屏": "Web Musician Screen",
    "开始创建": "Start Creating",
    "取消任务": "Cancel Task",
    "处理进度": "Progress",
    "阶段：等待输入": "Stage: Waiting for input",
    "三种语言均以 LRC 或输入文本为文字依据，自动对齐歌词时间": "For all three languages, lyric timing uses the LRC or entered text",
    "管理本地歌曲包，试听并修改歌词、节奏与和弦": "Manage song packages, listen, and edit lyrics, rhythm, and chords",
    "搜索歌曲名、歌手或歌曲包…": "Search title, artist, or song package…",
    "导入歌曲包": "Import Song Package",
    "双击歌曲可进入修改界面": "Double-click a song to edit it",
    "添加到播放列表": "Add to Playlist",
    "修改": "Edit",
    "导出歌曲包": "Export Song Package",
    "删除": "Delete",
    "尚未扫描歌曲库": "Song library has not been scanned",
    "加入": "Add",
    "歌曲名称": "Song Title",
    "时长": "Duration",
    "原KEY": "Original Key",
    "创建日期": "Created",
    "播放列表为空": "Playlist is empty",
    "双击歌曲可切换当前曲目": "Double-click a song to switch tracks",
    "安排演出顺序；双击歌曲可切换当前曲目": "Arrange the setlist; double-click a song to switch tracks",
    "顺序": "Order",
    "上移": "Up",
    "下移": "Down",
    "从列表移除": "Remove",
    "六轨混音、时间线与三屏演出输出": "Six-stem mixer, timeline, and three performance screens",
    "未加载歌曲": "No song loaded",
    "播放列表为空，请先添加歌曲": "The playlist is empty; add a song first",
    "下一首：播放列表暂无后续歌曲": "Next: No more songs in the playlist",
    "上一首": "Previous",
    "播放列表中没有上一首歌曲": "No previous song in the playlist",
    "回到歌曲开头": "Go to song start",
    "回到当前歌曲开头": "Go to the start of this song",
    "后退五秒": "Back 5 Seconds",
    "后退 5 秒": "Go back 5 seconds",
    "播放": "Play",
    "播放（空格键）": "Play (Space)",
    "前进五秒": "Forward 5 Seconds",
    "前进 5 秒": "Go forward 5 seconds",
    "停止播放": "Stop playback",
    "停止": "Stop",
    "下一首": "Next",
    "加载下一首歌曲；不会自动播放": "Load the next song without playing it",
    "速度": "Speed",
    "按目标 BPM 调整播放速度（变速会同步改变音高）": "Adjust playback speed by target BPM (pitch changes too)",
    "自动播放下一首": "Auto-play Next Song",
    "当前歌曲自然结束后，自动加载并播放下一首": "Load and play the next song when this one ends",
    "六轨混音": "Six-Stem Mixer",
    "主音量": "Master Volume",
    "舞台三屏输出": "Three-Screen Output",
    "观众": "Audience",
    "显示器": "Display",
    "补偿": "Offset",
    "字号": "Font",
    "随机模式": "Random",
    "播放策略": "Playback Mode",
    "显示拍子灯": "Show Beat Lights",
    "显示歌曲信息": "Show Song Info",
    "开启扫码": "Enable QR Access",
    "关闭扫码": "Disable QR Access",
    "网页歌手屏开关": "Web singer screen toggle",
    "让同一局域网内的手机或 iPad 打开歌手屏": "Let phones or tablets on this network open the singer screen",
    "二维码": "QR Code",
    "显示访问二维码和链接": "Show the access QR code and link",
    "乐手": "Musician",
    "调整歌词与和弦字号；有小节拍点时每行显示两小节": "Adjust lyric and chord size; show two measures per row when beats are available",
    "引导拍子声": "Count-in Sound",
    "引导拍子声开关": "Count-in sound toggle",
    "打开乐手屏时，从歌曲开头播放前按 BPM 先响两小节；歌曲开始后不再响拍子声": "Play a two-measure count-in before the song starts on the musician screen",
    "网页乐手屏开关": "Web musician screen toggle",
    "让同一局域网内的手机或 iPad 打开乐手谱面": "Let phones or tablets on this network open the musician score",
    "实时歌词监看": "Live Lyrics Preview",
    "可用滚轮调整；按 Enter 或点击其他位置后退出编辑": "Use the scroll wheel to adjust; press Enter or click elsewhere to finish",
    "可输入或用滚轮调整；按 Enter 或点击其他位置后退出编辑": "Type or scroll to adjust; press Enter or click elsewhere to finish",
    "当前句：—": "Current: —",
    "下一句：—": "Next: —",
    "等待加载": "Waiting to load",
    "人声": "Vocals",
    "鼓组": "Drums",
    "贝斯": "Bass",
    "吉他": "Guitar",
    "钢琴": "Piano",
    "其他": "Other",
    "级数谱": "Degree Chart",
    "和弦谱": "Chord Chart",
    "和弦谱（C调）": "Chord Chart (C)",
    "输入歌词关键词": "Search lyrics",
    "上一处": "Previous Match",
    "下一处": "Next Match",
    "重新识别和弦": "Recognize Chords Again",
    "取消": "Cancel",
    "保存和弦与歌词": "Save Chords and Lyrics",
    "和弦": "Chords",
    "歌词": "Lyrics",
    "修改歌曲": "Edit Song",
    "歌曲信息和节奏": "Song Details and Rhythm",
    "重新分析全部": "Reanalyze All",
    "重新分析节奏、Key、和弦及歌词字词时间": "Reanalyze rhythm, key, chords, and lyric timing",
    "保存修改": "Save Changes",
    "我已试听并核对歌词": "I have listened and checked the lyrics",
    "确认歌词并完成创建": "Confirm Lyrics and Finish",
    "未设置": "Not Set",
    "重新分析节奏和KEY": "Reanalyze Rhythm and Key",
    "音轨试听": "Stem Preview",
    "请试听并核对歌词": "Listen and Check Lyrics",
    "循环当前行": "Loop Current Line",
    "从选中行起偏移": "Offset from Selected Line",
    "撤销": "Undo",
    "重做": "Redo",
    "拆分歌词行": "Split Lyric Line",
    "合并上一行": "Merge with Previous Line",
    "合并下一行": "Merge with Next Line",
    "歌名": "Song Title",
    "静音": "Mute",
    "开始时间": "Start Time",
    "结束时间": "End Time",
    "搜索歌词": "Search Lyrics",
    "复制链接": "Copy Link",
    "关闭": "Close",
    "扫码打开": "Scan to Open",
    "手机或 iPad 需要与这台电脑连接同一个局域网。": "Connect your phone or iPad to the same local network as this computer.",
    "播放中": "Playing",
    "已暂停": "Paused",
    "已停止": "Stopped",
    "播放结束": "Playback Ended",
    "播放错误": "Playback Error",
    "加载失败": "Load Failed",
    "正在后台完整校验歌曲包……": "Validating the song package in the background…",
    "正在加载": "Loading",
    "歌曲已加载": "Song Loaded",
    "未加载": "Not Loaded",
    "暂停": "Pause",
    "暂停（空格键）": "Pause (Space)",
    "操作失败，请重试": "Operation failed; try again",
    "设置操作失败，请重试": "Settings operation failed; try again",
    "错误：": "Error: ",
    "无匹配": "No Matches",
    "分析中…": "Analyzing…",
    "识别中…": "Recognizing…",
    "穹顶火焰": "Ceiling Flames",
    "空灵波浪": "Ethereal Wave",
    "微距脉络": "Macro Plex",
    "系统默认黑体": "System Sans Serif",
    "龙藏体": "Long Cang",
    "马善政毛笔楷体": "Ma Shan Zheng",
    "站酷庆科黄油体": "ZCOOL QingKe HuangYou",
    "站酷小薇体": "ZCOOL XiaoWei",
    "此视频无法预览": "This video cannot be previewed",
    "请选择背景视频": "Choose a background video",
    "歌曲库目录不能为空": "The song library folder cannot be empty",
    "选择歌曲库目录": "Choose Song Library Folder",
    "上传背景循环视频": "Add Looping Background Video",
    "视频文件 (*.mp4 *.mov *.m4v *.webm)": "Video Files (*.mp4 *.mov *.m4v *.webm)",
    "LRC 歌词 (*.lrc)": "LRC Lyrics (*.lrc)",
    "歌曲创建完成，可以创建下一首": "Song created. You can create another.",
    "请选择源歌曲音频": "Choose the source audio file",
    "请选择 LRC 歌词文件或输入歌词文本": "Choose an LRC file or enter lyrics",
    "请选择 LRC 文件或输入歌词文本，不要同时提供": "Use either an LRC file or entered lyrics, not both",
    "正在处理歌曲": "Processing song",
    "正在分离音轨": "Separating audio stems",
    "正在校验六个轨道": "Validating six stems",
    "正在生成整曲简谱": "Generating the song score",
    "正在识别纯人声音符": "Recognizing vocal notes",
    "正在核对节奏和小节": "Checking rhythm and measures",
    "正在读取 LRC 歌词文字": "Reading LRC lyrics",
    "正在读取歌词文本": "Reading lyrics",
    "正在对齐歌词时间": "Aligning lyric timing",
    "正在识别逐字人声时间": "Recognizing word timing",
    "正在校验输入": "Validating input",
    "已加入": "Added",
    "未加入": "Not Added",
    "查看创建进度": "View Creation Progress",
    "请先选择歌曲": "Select a song first",
    "请先选择要加入播放列表的歌曲": "Select a song to add to the playlist",
    "播放列表操作失败，请重试": "Playlist operation failed; try again",
    "歌曲不存在（无法播放）": "Song is missing (cannot play)",
    "播放列表中没有下一首歌曲": "No next song in the playlist",
    "播放列表中没有可播放歌曲": "No playable songs in the playlist",
    "播放列表读取失败": "Could not read the playlist",
    "歌曲不存在，请从播放列表移除": "Song is missing; remove it from the playlist",
    "正在后台解码音轨……": "Decoding audio stems in the background…",
    "乐手屏显示选项已保存": "Musician screen options saved",
    "歌手屏显示选项已保存": "Singer screen options saved",
    "原音频输出设备已断开，已切换为系统默认设备": "The previous audio device disconnected; switched to the system default",
    "创建完成的歌曲路径无效": "The created song path is invalid",
    "部分歌曲已不存在，请刷新歌曲库后重试": "Some songs are missing; refresh the library and try again",
    "播放列表位置无效": "Invalid playlist position",
    "正在加载上一首，加载后请手动播放": "Loading the previous song; start playback manually",
    "正在加载下一首，加载后将自动播放": "Loading the next song; playback will start automatically",
    "正在加载下一首，加载后请手动播放": "Loading the next song; start playback manually",
    "引导拍子声已关闭": "Count-in sound disabled",
    "设置数据无效": "Invalid settings",
    "歌曲库目录已自动保存并应用": "Song library folder saved and applied",
    "音频输出设备已自动保存，将在下次加载歌曲时生效": "Audio output saved; it applies when the next song loads",
    "音频输出设备已更改": "Audio Output Changed",
    "新设备已保存，将在下次加载歌曲时生效。\n当前歌曲仍使用原来的音频输出设备。": "The new device will be used when the next song loads.\nThe current song still uses the previous device.",
    "背景视频设置数据无效": "Invalid background video settings",
    "观众屏背景已设为随机模式": "Audience background set to random",
    "上传的背景视频路径无效": "Invalid background video path",
    "正在优化上一段背景视频，请稍候": "Another background video is being optimized; please wait",
    "上传背景视频失败：资源无效": "Background video import failed: invalid resource",
    "已删除所选用户背景视频": "Selected user background video removed",
    "歌曲库中以歌词为基准的和弦表编辑器。": "Lyric-based chord editor for library songs.",
    "编辑模式": "Edit Mode",
    "前奏": "Intro",
    "间奏": "Interlude",
    "尾奏": "Outro",
    "和弦处理失败，请重试": "Chord processing failed; try again",
    "正在重新识别和弦……": "Recognizing chords again…",
    "歌词间空位": "Space between lyric lines",
    "修改和弦": "Edit Chords",
    "未设置有效原 Key，当前只能用原调和弦谱编辑": "Set a valid original key to edit transposed chord charts",
    "同一拍有多个和弦，请用 → 分隔并保留原有数量": "Separate multiple chords on one beat with → and keep the same count",
    "该句时间不足，无法按拍修改歌词": "This line is too short to edit lyrics by beat",
    "不能清空整句歌词；请在歌词页删除该句": "Delete this line on the Lyrics tab instead of clearing all its text",
    "该句没有逐字时间，请先重新分析歌词时间": "Analyze word timing for this line first",
    "找不到要移动的歌词时间": "Could not find the lyric timing to move",
    "目标拍没有足够时间容纳这些歌词": "The target beat is too short for these lyrics",
    "已暂存剪切；请粘贴到目标拍，随后按新拍位重建歌词时间": "Cut saved. Paste into the target beat, then rebuild lyric timing",
    "已暂存剪切；请完成粘贴，确保整句歌词没有缺字或重复": "Finish pasting and check that no words are missing or repeated",
    "保存空和弦表": "Save Empty Chord Chart",
    "当前和弦表为空，确定保存吗？": "The chord chart is empty. Save it?",
    "和弦校验失败": "Chord Validation Failed",
    "存在超出歌曲时长的和弦": "Some chords extend beyond the song duration",
    "修改此处的和弦；清空可删除": "Edit this chord; clear it to delete",
    "在此时间新增和弦": "Add a chord at this time",
    "该拍剩余时间不足，无法写入这些歌词": "Not enough time remains in this beat for these lyrics",
    "目标拍与另一句歌词重叠，请先调整相邻歌词": "The target beat overlaps another line; adjust neighboring lyrics first",
    "这一拍时间不足，无法放下输入的歌词": "This beat is too short for the entered lyrics",
    "这一拍跨越两句歌词，请在歌词页修改": "This beat crosses two lyric lines; edit it on the Lyrics tab",
    "找不到对应的歌词句": "Could not find the corresponding lyric line",
    "该时间已有和弦": "A chord already exists at this time",
    "该时间无法新增和弦": "Cannot add a chord at this time",
    "该字符位置无法新增和弦": "Cannot add a chord at this character position",
    "该模式需要先设置有效的原 Key": "Set a valid original key to use this mode",
    "这一拍时间不足，无法保存当前歌词": "This beat is too short to save the current lyrics",
    "该字符位置已有和弦": "A chord already exists at this character position",
    "该拍属于标题或段落标记，请先在歌词页调整该行": "This beat belongs to a heading; adjust the line on the Lyrics tab",
    "该拍剩余时间不足，无法新增歌词": "Not enough time remains in this beat to add lyrics",
    "歌曲信息与歌词校对": "Song Details and Lyric Review",
    "歌曲信息与节奏": "Song Details and Rhythm",
    "原 Key、BPM 和逐拍时间表由音乐分析生成；如有错误，请重新分析": "Original key, BPM, and beat timings come from analysis; reanalyze if needed",
    "当前歌词：—": "Current lyric: —",
    "正数使歌词延后，负数使歌词提前": "Positive values delay lyrics; negative values move them earlier",
    "将选中行及其后的全部歌词整体偏移": "Shift the selected line and all later lyrics",
    "歌词校对缺少有效歌曲时长": "Lyric review needs a valid song duration",
    "歌词处理失败，请重试": "Lyric processing failed; try again",
    "草稿已修改，将自动保存": "Draft changed; it will save automatically",
    "歌词已修改，保存后写入歌曲库": "Lyrics changed; save to update the library",
    "修改歌词时间": "Edit Lyric Timing",
    "请先选择歌词行": "Select a lyric line first",
    "从选中行起应用时间偏移": "Apply timing offset from the selected line",
    "后移": "Move Later",
    "前移": "Move Earlier",
    "音乐属性分析完成": "Music analysis complete",
    "请先勾选“我已试听并核对歌词”": "Check “I have listened and checked the lyrics” first",
    "歌名不能为空": "Song title cannot be empty",
    "原Key 和 BPM 需要同时填写，或同时留空": "Enter both original key and BPM, or leave both blank",
    "存在超出歌曲时长的歌词": "Some lyrics extend beyond the song duration",
    "修改歌词文本": "Edit Lyric Text",
    "歌词时间单元格缺失": "Lyric timing cell is missing",
    "请输入非零偏移量；正数后移，负数前移": "Enter a nonzero offset; positive moves later, negative earlier",
    "当前歌词：间奏": "Current lyric: interlude",
    "歌词校验失败": "Lyric Validation Failed",
    "请检查歌词内容后重试": "Check the lyrics and try again",
    "对齐歌词时间": "Align Lyric Timing",
    "按拍修改歌词": "Edit Lyrics by Beat",
    "歌曲处理失败，请重试": "Song processing failed; try again",
    "分析结果无效": "Invalid analysis result",
    "未能生成可靠的逐字时间，请检查歌词和人声轨": "Could not produce reliable word timing; check lyrics and vocals",
    "字词时间对齐失败": "Word Timing Alignment Failed",
    "重新分析节奏、KEY、和弦和歌词字词时间……": "Reanalyzing rhythm, key, chords, and lyric timing…",
    "正在重新分析原 Key、BPM 和节拍表……": "Reanalyzing original key, BPM, and beats…",
    "导出 PDF 失败": "PDF Export Failed",
    "导出乐手谱 PDF": "Export Musician Score PDF",
    "无法保存乐手谱 PDF，请检查保存位置。": "Could not save the score PDF; check the destination.",
    "无法加载 PDF 排版页面。": "Could not load the PDF layout page.",
    "等待谱面排版超时，请重试。": "Score layout timed out; try again.",
    "乐手谱": "Musician Score",
    "PDF 文件 (*.pdf)": "PDF Files (*.pdf)",
    "请先加载歌曲": "Load a song first",
    "请重试或检查歌曲文件": "Try again or check the song file",
    "请重试或检查歌词文件": "Try again or check the lyrics file",
    "歌曲包": "Song Package",
    "删除歌曲": "Delete Song",
    "永久删除": "Delete Permanently",
    "此操作无法撤销。": "This action cannot be undone.",
    "停止导入": "Stop Import",
    "创建新歌曲 ID 并继续": "Create a New Song ID and Continue",
    "歌曲 ID 已存在": "Song ID Already Exists",
    "ZIP 文件 (*.zip)": "ZIP Files (*.zip)",
    "导出歌曲包 ZIP": "Export Song Package ZIP",
    "选择要导入的歌曲包 ZIP": "Select a Song Package ZIP",
    "歌曲信息、歌词与和弦修改已写入歌曲包": "Song details, lyrics, and chords saved to the package",
    "正在校验并导入歌曲包……": "Validating and importing the song package…",
    "正在校验并导出歌曲包……": "Validating and exporting the song package…",
    "正在后台加载歌曲修改工作区……": "Loading the song editor in the background…",
    "歌曲修改窗口已打开": "Song editor opened",
    "歌曲修改数据无效": "Invalid song edit data",
    "当前歌曲数据无效": "Invalid song data",
    "歌曲路径无效": "Invalid song path",
    "已停止导入，原歌曲包未改动": "Import stopped; original package unchanged",
    "正在创建新歌曲 ID 并继续导入……": "Creating a new song ID and continuing import…",
    "没有和弦数据，请到“歌曲库”的修改页面中，重新分析和弦数据": "No chord data; open Edit in the Song Library and analyze chords again",
    "正式播放": "Playing",
    "发生错误": "An Error Occurred",
    "已取消": "Canceled",
    "已有创建任务正在运行": "A song creation task is already running",
    "创建任务运行中，暂时不能切换歌曲库": "The song library cannot be changed during creation",
    "创建参数格式错误": "Invalid song creation parameters",
    "任务缺少自动生成的歌词": "The task has no generated lyrics",
    "歌词已自动定稿，正在生成歌曲包": "Lyrics finalized; generating the song package",
    "正在取消任务……": "Canceling task…",
    "音频引擎尚未加载，可先编辑歌词": "Audio has not loaded; you can edit lyrics first",
    "应用音乐属性分析结果，保存时一并写入歌曲包。": "Music analysis results will be saved with the song package.",
    "歌手屏窗口已关闭": "Singer screen closed",
    "歌手屏拍子灯已显示": "Singer beat lights shown",
    "歌手屏拍子灯已隐藏": "Singer beat lights hidden",
    "乐手屏拍子灯已显示": "Musician beat lights shown",
    "乐手屏拍子灯已隐藏": "Musician beat lights hidden",
    "歌手屏歌曲信息已显示": "Singer song info shown",
    "歌手屏歌曲信息已隐藏": "Singer song info hidden",
    "歌手屏窗口已打开，可拖动或全屏": "Singer screen opened; drag or enter full screen",
    "观众屏窗口已关闭": "Audience screen closed",
    "观众屏窗口已打开，可拖动或全屏": "Audience screen opened; drag or enter full screen",
    "乐手屏窗口已关闭": "Musician screen closed",
    "乐手屏窗口已打开，可拖动或全屏": "Musician screen opened; drag or enter full screen",
    "网页歌手屏已关闭": "Web singer screen closed",
    "网页乐手屏已关闭": "Web musician screen closed",
    "网页歌手屏已开启；手机或 iPad 与电脑连接同一局域网后扫码访问": "Web singer screen enabled; scan the code from a phone or iPad on the same network",
    "网页乐手屏已开启；手机或 iPad 与电脑连接同一局域网后扫码访问": "Web musician screen enabled; scan the code from a phone or iPad on the same network",
    "启动网页歌手屏失败": "Could not start the web singer screen",
    "启动网页乐手屏失败": "Could not start the web musician screen",
    "本地网页歌手屏地址不可用": "Local web singer screen address is unavailable",
    "本地网页乐手屏地址不可用": "Local web musician screen address is unavailable",
    "保存系统混音参数失败": "Could not save mixer settings",
    "保存乐手屏和弦模式失败": "Could not save musician chord mode",
    "保存乐手屏拍子灯设置失败": "Could not save musician beat lights",
    "保存歌手屏显示设置失败": "Could not save singer display settings",
    "保存舞台三屏输出参数失败": "Could not save stage screen settings",
    "播放操作失败，请重试": "Playback failed; try again",
    "加载的歌曲包数据无效": "Invalid loaded song package",
    "打开观众屏输出失败": "Could not open audience screen",
    "打开歌手屏输出失败": "Could not open singer screen",
    "打开乐手屏输出失败": "Could not open musician screen",
    "已加载修改后的歌曲信息和歌词": "Updated song details and lyrics loaded",
    "已加载修改后的和弦表": "Updated chord chart loaded",
    "使用默认渐变背景": "Use the default gradient background",
    "语言已切换": "Language changed",
    "创建歌曲模型": "Song Creation Models",
    "按用途准备本机资源，不显示具体模型名称": "Prepare local resources by role; specific model names are hidden",
    "运行组件": "Runtime Tools",
    "创建与导入歌曲所需的本机工具": "Local tools required for creating and importing songs",
    "转码与探测音频视频": "Transcode and probe audio/video",
    "本机已安装，可直接使用": "Installed on this Mac; ready to use",
    "已下载到本机应用目录": "Downloaded into the app data folder",
    "已随安装包提供": "Included with the app package",
    "请先自行安装 FFmpeg 并确保可在终端调用": "Install FFmpeg yourself and make sure it is on PATH",
    "不可用": "Unavailable",
    "FFmpeg 已就绪": "FFmpeg is ready",
    "正在下载 FFmpeg…": "Downloading FFmpeg…",
    "当前系统不支持应用内下载 FFmpeg，请先自行安装": (
        "In-app FFmpeg download is not supported on this system; install it yourself first"
    ),
    "未找到 FFmpeg。请到设置页下载到本机后重试。": (
        "FFmpeg was not found. Download it on the Settings page, then try again."
    ),
    "下载": "Download",
    "下载中…": "Downloading…",
    "已下载": "Downloaded",
    "已就绪": "Ready",
    "未下载": "Missing",
    "下载中": "Downloading",
    "音轨分离模型": "Stem Separation Model",
    "把歌曲拆成六轨": "Split a song into six stems",
    "节拍模型": "Beat Model",
    "分析拍点与小节": "Analyze beats and bars",
    "谱面分析模型": "Score Analysis Model",
    "分析音符与和弦": "Analyze notes and chords",
    "歌词识别模型": "Lyric Recognition Model",
    "从人声识别歌词文字": "Recognize lyric text from vocals",
    "中文歌词适配模型": "Chinese Lyric Alignment Model",
    "对齐国语歌词时间": "Align Mandarin lyric timing",
    "英文歌词适配模型": "English Lyric Alignment Model",
    "对齐英文歌词时间": "Align English lyric timing",
    "粤语歌词适配模型": "Cantonese Lyric Alignment Model",
    "对齐粤语歌词时间": "Align Cantonese lyric timing",
    "缺少音轨分离模型。请到设置页下载到本机后重试。": "Stem separation model missing. Download it on the Settings page, then try again.",
    "缺少节拍模型。请到设置页下载到本机后重试。": "Beat model missing. Download it on the Settings page, then try again.",
    "缺少谱面分析模型。请到设置页下载到本机后重试。": "Score analysis model missing. Download it on the Settings page, then try again.",
    "缺少歌词识别模型。请到设置页下载到本机后重试。": "Lyric recognition model missing. Download it on the Settings page, then try again.",
    "缺少中文歌词适配模型。请到设置页下载到本机后重试。": "Chinese lyric alignment model missing. Download it on the Settings page, then try again.",
    "缺少英文歌词适配模型。请到设置页下载到本机后重试。": "English lyric alignment model missing. Download it on the Settings page, then try again.",
    "缺少粤语歌词适配模型。请到设置页下载到本机后重试。": "Cantonese lyric alignment model missing. Download it on the Settings page, then try again.",
    "已有资源正在下载，请稍候": "A download is already in progress; please wait",
    "无法识别要下载的资源": "Could not identify the resource to download",
    "下载失败，请稍后重试或检查网络": "Download failed; try again later or check the network",
}

PREFIXES: tuple[tuple[str, str], ...] = (
    ("保存失败：", "Save failed: "),
    ("加载歌曲失败：", "Could not load song: "),
    ("播放列表读取失败：", "Could not read playlist: "),
    ("读取播放列表失败：", "Could not read playlist: "),
    ("添加到播放列表失败：", "Could not add to playlist: "),
    ("删除背景视频失败：", "Could not remove background video: "),
    ("上传背景视频失败：", "Could not import background video: "),
    ("刷新音频输出设备失败：", "Could not refresh audio devices: "),
    ("保存引导拍子声设置失败：", "Could not save count-in sound: "),
    ("保存背景视频设置失败：", "Could not save background video settings: "),
    ("保存自动播放设置失败：", "Could not save auto-play: "),
    ("应用观众屏字体失败：", "Could not apply audience font: "),
    ("移除失败：", "Removal failed: "),
    ("调整顺序失败：", "Could not change order: "),
    ("字词时间对齐失败：", "Word timing alignment failed: "),
    ("字词时间识别失败：", "Word timing recognition failed: "),
    ("保存歌曲修改失败：", "Could not save song edits: "),
    ("加载歌曲修改工作区失败：", "Could not open the song editor: "),
    ("重新分析失败：", "Reanalysis failed: "),
    ("保存乐手屏和弦模式失败：", "Could not save musician chord mode: "),
    ("保存乐手屏拍子灯设置失败：", "Could not save musician beat lights: "),
    ("保存歌手屏显示设置失败：", "Could not save singer display settings: "),
    ("保存舞台三屏输出参数失败：", "Could not save stage screen settings: "),
    ("网页歌手屏自动恢复失败：", "Could not restore web singer screen: "),
    ("网页乐手屏自动恢复失败：", "Could not restore web musician screen: "),
    ("导入歌曲失败：", "Song import failed: "),
    ("导出歌曲失败：", "Song export failed: "),
    ("重新分析全部失败：", "Reanalysis failed: "),
    ("重新分析节奏和 KEY 失败：", "Rhythm and key analysis failed: "),
    ("重新识别和弦失败：", "Chord recognition failed: "),
    ("正在解码 ", "Decoding "),
    ("已导入歌曲：", "Imported song: "),
    ("已永久删除歌曲：", "Deleted song: "),
    ("已创建新歌曲 ID 并导入：", "Created a new song ID and imported: "),
    ("重复 ID：", "Duplicate ID: "),
    ("歌曲包已导出：", "Exported song package: "),
    ("已优化并应用背景视频：", "Optimized and applied background video: "),
    ("观众屏字体已应用：", "Audience font applied: "),
    ("观众屏背景已固定为：", "Audience background set to: "),
    ("乐手屏字号已保存：", "Musician font size saved: "),
    ("保存乐手屏字号失败", "Could not save musician font size"),
    ("保存字幕字号失败", "Could not save subtitle font size"),
)

PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"版本 (.+)"), r"Version \1"),
    (re.compile(r"播放列表：(\d+) 首"), r"Playlist: \1 songs"),
    (re.compile(r"(\d+) 声道"), r"\1 channels"),
    (re.compile(r"原KEY\s+(.+?)\s*·\s*(\d+)\s+BPM"), r"Original key \1 · \2 BPM"),
    (
        re.compile(r"可播放歌曲：(\d+)；损坏或不完整歌曲包：(\d+)"),
        r"Playable songs: \1; damaged or incomplete packages: \2",
    ),
    (re.compile(r"当前句：(.*)"), r"Current: \1"),
    (re.compile(r"下一句：(.*)"), r"Next: \1"),
    (re.compile(r"下一首：(.*)"), r"Next: \1"),
    (re.compile(r"已加入 (\d+) 首歌曲"), r"Added \1 songs"),
    (re.compile(r"已刷新音频输出设备：发现 (\d+) 个设备"), r"Audio devices refreshed: \1 found"),
    (
        re.compile(r"字幕字号已保存：观众 (\d+) pt，歌手 (\d+) pt"),
        r"Subtitle sizes saved: audience \1 pt, singer \2 pt",
    ),
    (re.compile(r"加载失败：(.*)"), r"Load failed: \1"),
    (re.compile(r"错误：(.*)"), r"Error: \1"),
)


@lru_cache(maxsize=4096)
def english(text: str) -> str:
    if not any("\u3400" <= char <= "\u9fff" for char in text):
        return text
    result = ENGLISH.get(text)
    if result is not None:
        return result
    for prefix, translated_prefix in PREFIXES:
        if text.startswith(prefix):
            return translated_prefix + text[len(prefix) :]
    if match := re.fullmatch(r"(.+)（系统预设）", text):
        return f"{english(match.group(1))} (built-in)"
    if match := re.fullmatch(r"(.+)（用户上传）", text):
        return f"{match.group(1)} (uploaded)"
    if match := re.fullmatch(r"阶段：(.*)", text):
        return f"Stage: {english(match.group(1))}"
    if match := re.fullmatch(r"(.+)（(\d+) 声道）", text):
        return f"{match.group(1)} ({match.group(2)} channels)"
    if match := re.fullmatch(r"(.+)屏输出开关", text):
        return f"{english(match.group(1))} screen output toggle"
    if match := re.fullmatch(r"(.+)轨道静音开关", text):
        return f"{english(match.group(1))} mute toggle"
    if match := re.fullmatch(r"(.+)轨音量", text):
        return f"{english(match.group(1))} volume"
    if match := re.fullmatch(r"调整(.+)轨音量", text):
        return f"Adjust {english(match.group(1))} volume"
    if match := re.fullmatch(r"点击切换(.+)轨道；彩色为启用，灰色为静音", text):
        return f"Toggle {english(match.group(1))}; colored means enabled, gray means muted"
    if match := re.fullmatch(r"点击打开或关闭(.+)屏输出窗口；彩色为已打开", text):
        return f"Toggle the {english(match.group(1))} screen; colored means open"
    if match := re.fullmatch(r"将《(.+)》加入播放列表", text):
        return f"Add “{match.group(1)}” to playlist"
    if match := re.fullmatch(r"将(.+)加入播放列表", text):
        return f"Add {match.group(1)} to playlist"
    if match := re.fullmatch(r"加载下一首：(.+)；不会自动播放", text):
        return f"Load next: {match.group(1)}; will not play automatically"
    if match := re.fullmatch(r"歌词试听校对 - (.+)", text):
        return f"Lyric Review - {match.group(1)}"
    if match := re.fullmatch(r"修改和弦 · (.+)", text):
        return f"Edit Chords · {match.group(1)}"
    for pattern, replacement in PATTERNS:
        if pattern.fullmatch(text):
            return pattern.sub(replacement, text)
    return text


class UiTranslator(QObject):
    """Translate app widgets in either direction without touching WebEngine internals."""

    def __init__(self, application: QApplication) -> None:
        super().__init__(application)
        self.application = application
        self.language = "zh"
        self._values: WeakKeyDictionary[QWidget, dict[str, tuple[str, str]]] = (
            WeakKeyDictionary()
        )
        self._timer = QTimer(self)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.translate_all)

    def set_language(self, language: str) -> None:
        self.language = language if language in {"zh", "en"} else "zh"
        self.translate_all()
        if self.language == "en":
            self._timer.start()
        else:
            self._timer.stop()

    def translate_all(self) -> None:
        for root in self.application.topLevelWidgets():
            if not isinstance(root, (QMainWindow, QDialog, OutputWindow)):
                continue
            stack: list[QWidget] = [root]
            while stack:
                widget = stack.pop()
                if isinstance(widget, QWebEngineView):
                    continue
                try:
                    self._translate_widget(widget)
                    stack.extend(
                        child for child in widget.children() if isinstance(child, QWidget)
                    )
                except RuntimeError:  # A dialog may close while it is being scanned.
                    continue

    def _set_text(
        self, widget: QWidget, key: str, current: str, setter: Callable[[str], None]
    ) -> None:
        values = self._values.setdefault(widget, {})
        previous = values.get(key)
        source = previous[0] if previous is not None and current == previous[1] else current
        if widget.objectName() == "brandSubtitle" and source == "大象乐队工作站":
            target = "Power by Siwen" if self.language == "en" else source
        else:
            target = english(source) if self.language == "en" else source
        if target != current:
            setter(target)
        values[key] = (source, target)

    def _translate_widget(self, widget: QWidget) -> None:
        self._set_text(widget, "windowTitle", widget.windowTitle(), widget.setWindowTitle)
        self._set_text(widget, "toolTip", widget.toolTip(), widget.setToolTip)
        self._set_text(widget, "accessibleName", widget.accessibleName(), widget.setAccessibleName)
        if (
            isinstance(widget, QLabel)
            and (widget.objectName() != "songTitle" or widget.property("i18n_static"))
            and not widget.property("i18n_skip")
        ):
            self._set_text(widget, "text", widget.text(), widget.setText)
        if isinstance(widget, QAbstractButton):
            self._set_text(widget, "text", widget.text(), widget.setText)
        if isinstance(widget, (TrackMuteButton, OutputScreenButton)):
            self._set_text(
                widget, "paintedLabel", widget.label, partial(self._set_painted_label, widget)
            )
        if isinstance(widget, QGroupBox):
            self._set_text(widget, "title", widget.title(), widget.setTitle)
        if isinstance(widget, QLineEdit):
            self._set_text(widget, "placeholder", widget.placeholderText(), widget.setPlaceholderText)
        if isinstance(widget, (QPlainTextEdit, QTextEdit)):
            self._set_text(widget, "placeholder", widget.placeholderText(), widget.setPlaceholderText)
        if isinstance(widget, QComboBox):
            with QSignalBlocker(widget):
                for index in range(widget.count()):
                    self._set_text(
                        widget, f"combo:{index}", widget.itemText(index), partial(widget.setItemText, index)
                    )
        if isinstance(widget, QListWidget):
            with QSignalBlocker(widget):
                for index in range(widget.count()):
                    list_item = widget.item(index)
                    if list_item is not None:
                        self._set_text(widget, f"list:{index}", list_item.text(), list_item.setText)
        if isinstance(widget, QTableWidget):
            for index in range(widget.columnCount()):
                header_item = widget.horizontalHeaderItem(index)
                if header_item is not None:
                    self._set_text(widget, f"header:{index}", header_item.text(), header_item.setText)
            if widget.objectName() == "songLibraryTable" and widget.columnCount() > 6:
                for row in range(widget.rowCount()):
                    status_item = widget.item(row, 6)
                    if status_item is not None:
                        if self.language == "en" and status_item.text() in {"已加入", "未加入"}:
                            status_item.setText(english(status_item.text()))
                        elif self.language == "zh" and status_item.text() in {"Added", "Not Added"}:
                            status_item.setText("已加入" if status_item.text() == "Added" else "未加入")
        if isinstance(widget, QTabWidget):
            for index in range(widget.count()):
                self._set_text(
                    widget, f"tab:{index}", widget.tabText(index), partial(widget.setTabText, index)
                )
        if isinstance(widget, (QSpinBox, QDoubleSpinBox)):
            self._set_text(widget, "prefix", widget.prefix(), widget.setPrefix)
            self._set_text(widget, "suffix", widget.suffix(), widget.setSuffix)
            self._set_text(widget, "special", widget.specialValueText(), widget.setSpecialValueText)

    @staticmethod
    def _set_painted_label(widget: TrackMuteButton | OutputScreenButton, value: str) -> None:
        widget.label = value
        widget.update()
