# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

PRO_AUDIO_STYLESHEET = """
QMainWindow,
QDialog {
    background-color: #0d0f13;
}

QWidget {
    color: #e7ebf1;
    font-size: 13px;
}

QWidget#applicationRoot,
QStackedWidget#pageStack {
    background-color: #101319;
}

QWidget#embeddedPlaylistPage {
    background-color: #12161d;
}

QFrame#playbackPlaylistDivider {
    color: #2b313b;
    background-color: #2b313b;
    border: 0;
    min-width: 1px;
    max-width: 1px;
}

QWidget#sidebar {
    background-color: #15181e;
    border-right: 1px solid #292e38;
}

QLabel#brandTitle {
    color: #f4f7fb;
    font-size: 19px;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#brandSubtitle,
QLabel#pageSubtitle,
QLabel#mutedText {
    color: #7f8998;
    font-size: 12px;
}

QLabel#pageTitle {
    color: #f5f7fa;
    font-size: 26px;
    font-weight: 700;
}

QLabel#sectionLabel {
    color: #8d97a6;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#sidebarVersion {
    color: #66707e;
    font-size: 11px;
    padding: 4px 0 0 0;
}

QLabel#songTitle {
    color: #ffffff;
    font-size: 22px;
    font-weight: 700;
}

QLabel#nowPlayingMusicInfo {
    color: #74adff;
    background-color: #172841;
    border: 1px solid #285187;
    border-radius: 8px;
    padding: 5px 10px;
    font-family: "Menlo", monospace;
    font-size: 12px;
    font-weight: 700;
}

QLabel#stateChip {
    color: #74adff;
    background-color: #172841;
    border: 1px solid #285187;
    border-radius: 11px;
    padding: 4px 10px;
    font-size: 11px;
    font-weight: 700;
}

QLabel#timeDisplay {
    color: #b6c1d0;
    font-family: "Menlo", monospace;
    font-size: 12px;
}

QLabel#volumeValue {
    color: #d7dee8;
    font-family: "Menlo", monospace;
    font-size: 12px;
    min-width: 38px;
}

QLabel#volumeLabel:disabled,
QLabel#volumeValue:disabled {
    color: #59616d;
}

QLabel[role="parameterLabel"]:disabled {
    color: #59616d;
}

QLabel#statusBar {
    color: #8994a3;
    background-color: #15191f;
    border: 1px solid #262c35;
    border-radius: 6px;
    padding: 8px 11px;
}

QLabel#currentLyric {
    color: #f4c34d;
    font-size: 18px;
    font-weight: 700;
    padding: 2px 0;
}

QLabel#nextLyric {
    color: #909aa8;
    font-size: 14px;
    padding: 2px 0;
}

QListWidget#primaryNavigation {
    background-color: transparent;
    border: 0;
    outline: 0;
    padding: 2px 10px;
}

QListWidget#primaryNavigation::item {
    color: #929cab;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 11px 14px;
    margin: 2px 0;
}

QListWidget#primaryNavigation::item:hover {
    color: #dbe3ee;
    background-color: #1d222a;
}

QListWidget#primaryNavigation::item:selected {
    color: #ffffff;
    background-color: #243b5d;
    border: 1px solid #315d96;
    font-weight: 700;
}

QFrame#card,
QFrame#nowPlayingPanel,
QFrame#transportPanel,
QFrame#toolbarCard,
QFrame#editorPanel {
    background-color: #181c23;
    border: 1px solid #2b313b;
    border-radius: 9px;
}

QFrame#nowPlayingPanel {
    background-color: #151b25;
    border: 1px solid #2e4e78;
}

QDialog#songEditDialog {
    background-color: #101319;
}

QDialog#confirmationDialog {
    background-color: #15191f;
}

QLabel#confirmationIcon {
    background-color: #352023;
    border: 1px solid #673238;
    border-radius: 8px;
}

QLabel#confirmationTitle {
    color: #f5f7fa;
    font-size: 19px;
    font-weight: 700;
}

QLabel#confirmationMessage {
    color: #e7ebf1;
    font-size: 14px;
    font-weight: 600;
}

QLabel#confirmationDetail {
    color: #8d97a6;
    font-size: 12px;
}

QTabWidget#songEditTabs {
    background-color: #12161c;
}

QTabWidget#songEditTabs::pane {
    background-color: #12161c;
    border: 1px solid #303946;
    border-radius: 8px;
    top: -1px;
}

QTabBar::tab {
    color: #98a4b3;
    background-color: #1b222b;
    border: 1px solid #303946;
    border-bottom: 0;
    border-top-left-radius: 7px;
    border-top-right-radius: 7px;
    min-width: 112px;
    padding: 10px 18px;
    margin-right: 5px;
    font-weight: 600;
}

QTabBar::tab:hover {
    color: #e8edf4;
    background-color: #25303c;
}

QTabBar::tab:selected {
    color: #ffffff;
    background-color: #254267;
    border-color: #4b80bc;
}

QFrame#settingsPanel {
    background-color: #1b1d22;
    border: 1px solid #34373e;
    border-radius: 9px;
}

QLabel#settingsPanelTitle {
    color: #f3f4f6;
    font-size: 17px;
    font-weight: 700;
}

QLabel#settingsPanelSubtitle,
QLabel#settingsPreviewDetail,
QLabel#settingsFooterHint {
    color: #7f858e;
    font-size: 11px;
}

QLabel#settingsSectionLabel {
    color: #aeb3bb;
    border-bottom: 1px solid #34373e;
    padding-bottom: 6px;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1px;
}

QLabel#settingsFieldLabel {
    color: #8d939d;
    font-size: 11px;
    font-weight: 600;
}

QFrame#settingsModelList {
    background-color: #14161a;
    border: 1px solid #30333a;
    border-radius: 7px;
}

QLabel#settingsModelTitle {
    color: #e4e6ea;
    font-size: 12px;
    font-weight: 600;
}

QLabel#settingsModelDetail {
    color: #7f858e;
    font-size: 10px;
}

QLabel#settingsModelStatus {
    color: #8d939d;
    font-size: 11px;
    font-weight: 600;
    min-width: 42px;
}

QLabel#settingsModelStatus[state="ready"] {
    color: #7dbe8e;
}

QLabel#settingsModelStatus[state="missing"] {
    color: #d0a15c;
}

QLabel#settingsModelStatus[state="busy"] {
    color: #7aa7d9;
}

QLabel#settingsHintCard {
    color: #90959e;
    background-color: #15171b;
    border: 1px solid #2c2f35;
    border-radius: 6px;
    padding: 10px;
    font-size: 11px;
}

QFrame#settingsResourcePane,
QFrame#settingsPreviewPane {
    background-color: #14161a;
    border: 1px solid #30333a;
    border-radius: 7px;
}

QLabel#settingsBrowserTitle {
    color: #d6d9de;
    font-size: 12px;
    font-weight: 700;
}

QLabel#settingsBrowserMeta {
    color: #676d76;
    font-family: "Menlo", monospace;
    font-size: 9px;
    font-weight: 700;
}

QStackedWidget#settingsPreviewMonitor {
    background-color: #080a0d;
    border: 1px solid #424750;
    border-radius: 3px;
}

QListWidget#backgroundResourceList {
    color: #bdc2ca;
    background-color: #101216;
    border: 1px solid #2c3037;
    border-radius: 4px;
    outline: 0;
    padding: 4px;
}

QListWidget#backgroundResourceList::item {
    border: 1px solid transparent;
    border-radius: 4px;
    padding: 7px 8px;
    margin: 1px 0;
}

QListWidget#backgroundResourceList::item:hover {
    color: #f0f1f3;
    background-color: #24272d;
}

QListWidget#backgroundResourceList::item:selected {
    color: #ffffff;
    background-color: #3a3222;
    border-color: #7c6331;
}

QGroupBox {
    color: #b9c2cf;
    background-color: #181c23;
    border: 1px solid #2b313b;
    border-radius: 9px;
    margin-top: 13px;
    padding: 15px 13px 11px 13px;
    font-weight: 700;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 13px;
    padding: 0 7px;
    color: #9fa9b7;
    background-color: #181c23;
}

QPushButton {
    color: #dbe2ec;
    background-color: #262c35;
    border: 1px solid #3a424f;
    border-radius: 6px;
    min-height: 20px;
    padding: 7px 13px;
    font-size: 13px;
    font-weight: 600;
}

QPushButton:hover {
    color: #ffffff;
    background-color: #303844;
    border-color: #536071;
}

QPushButton:pressed {
    background-color: #1e242d;
}

QPushButton:disabled {
    color: #59616d;
    background-color: #1d2127;
    border-color: #282d35;
}

QPushButton[role="primary"] {
    color: #ffffff;
    background-color: #327eea;
    border-color: #4b94fb;
}

QPushButton[role="primary"]:hover {
    background-color: #438df2;
}

QPushButton[role="primary"]:disabled {
    color: #59616d;
    background-color: #1d2127;
    border-color: #282d35;
}

QPushButton#libraryResourcesButton {
    color: #f4c34d;
    background-color: #262318;
    border: 1px solid #6d5826;
    border-radius: 8px;
    font-size: 15px;
    font-weight: 700;
}

QPushButton#libraryResourcesButton:hover {
    color: #ffe18a;
    background-color: #37301c;
    border-color: #c59a3e;
}

QPushButton#libraryResourcesButton:pressed {
    background-color: #211c12;
}

QPushButton[role="danger"] {
    color: #ffb8b8;
    background-color: #352023;
    border-color: #673238;
}

QPushButton[role="play"] {
    color: #07180f;
    background-color: #4bd386;
    border-color: #72e3a4;
    border-radius: 17px;
    min-width: 78px;
    min-height: 26px;
}

QPushButton[role="play"]:hover {
    background-color: #66df9b;
}

QPushButton[role="transport"] {
    background-color: #202630;
    min-width: 42px;
}

QPushButton[role="tableAction"] {
    color: #9fc4ff;
    background-color: #1b2b42;
    border-color: #315d96;
    min-height: 16px;
    padding: 1px 7px;
}

QPushButton[role="tableAction"]:hover {
    color: #ffffff;
    background-color: #254a78;
    border-color: #4b94fb;
}

QPushButton[role="lock"] {
    min-width: 54px;
    padding-left: 10px;
    padding-right: 10px;
}

QPushButton[role="lock"]:checked {
    color: #f4c34d;
    background-color: #302817;
    border-color: #735d25;
}

QFrame#outputChannelSeparator {
    color: #303743;
    background-color: #303743;
    border: 0;
    min-width: 1px;
    max-width: 1px;
}

QLineEdit,
QComboBox,
QSpinBox,
QPlainTextEdit,
QTableWidget,
QTableWidget#songLibraryTable {
    color: #e6ebf2;
    background-color: #11151a;
    border: 1px solid #343b46;
    border-radius: 6px;
    selection-background-color: #285d9e;
    selection-color: #ffffff;
}

QTableWidget#songEditLyricTable {
    gridline-color: #29323d;
    outline: 0;
}

QTableWidget#songEditLyricTable::item {
    border-bottom: 1px solid #252e38;
    padding: 7px 10px;
}

QTableWidget#songEditLyricTable::item:selected {
    background-color: #254267;
    color: #ffffff;
}

QLineEdit,
QComboBox,
QSpinBox {
    min-height: 22px;
    padding: 5px 8px;
}

QLineEdit:focus,
QComboBox:focus,
QSpinBox:focus,
QPlainTextEdit:focus,
QTableWidget:focus,
QTableWidget#songLibraryTable:focus {
    border-color: #3d8bfd;
}

QScrollArea#chordLyricEditor,
QWidget#chordLyricsContent {
    background-color: #0b0e12;
}

QScrollArea#chordLyricEditor {
    border: 1px solid #252b33;
}

QFrame#chordLyricRow {
    background-color: #0b0e12;
    border: 0;
    border-bottom: 1px solid #20262e;
}

QFrame#chordLyricRow[searchMatch="true"],
QLineEdit#lyricBeatEditor[searchMatch="true"] {
    background-color: #3a3015;
    border: 1px solid #d8aa36;
}

QLabel#lyricSearchResult {
    color: #8e9aad;
    min-width: 48px;
}

QLabel#chordEditorLyricCharacter {
    color: #f4f7fb;
    background-color: transparent;
}

QLabel#instrumentalChordHeading {
    color: #ffd34e;
    background-color: transparent;
    font-size: 15px;
    font-weight: 600;
}

QLabel#instrumentalChordTime {
    color: #8e9aad;
    background-color: transparent;
    font-size: 12px;
}

QLineEdit#chordInlineEditor {
    color: #f2f6fc;
    background-color: #151b23;
    border: 1px solid #3a4553;
    border-radius: 6px;
    min-height: 0;
    padding: 2px 4px;
}

QLineEdit#chordInlineEditor:focus {
    color: #ffffff;
    background-color: #19283b;
    border-color: #4b94fb;
}

QLineEdit#chordInlineEditor[hasChord="true"] {
    color: #123b2a;
    background-color: #b9e8cf;
    border-color: #69c99a;
}

QLineEdit#chordInlineEditor[hasChord="true"]:focus {
    color: #0d3021;
    background-color: #cdf3de;
    border-color: #55d18e;
}

QFrame#chordBeatMeasure {
    background-color: transparent;
    border: 2px solid transparent;
    border-radius: 8px;
}

QFrame#chordBeatMeasure[currentMeasure="true"] {
    background-color: #15263a;
    border-color: #4b94fb;
}

QComboBox::drop-down,
QSpinBox::up-button,
QSpinBox::down-button {
    border: 0;
    width: 22px;
}

QComboBox QAbstractItemView {
    color: #e6ebf2;
    background-color: #20252d;
    border: 1px solid #3a424e;
    selection-background-color: #2f6db9;
}

QComboBox[modelState="missing"] {
    color: #66707e;
}

QComboBox:disabled,
QSpinBox:disabled {
    color: #59616d;
    background-color: #14181e;
    border-color: #282d35;
}

QTableWidget#songLibraryTable {
    gridline-color: #252b33;
    outline: 0;
}

QTableWidget#songLibraryTable::item {
    border-bottom: 1px solid #252b33;
    padding: 9px 10px;
}

QTableWidget#songLibraryTable::item:hover {
    background-color: #1c222a;
}

QTableWidget#songLibraryTable::item:selected {
    background-color: #203c61;
    color: #ffffff;
}

QHeaderView::section {
    color: #aeb8c5;
    background-color: #20252d;
    border: 0;
    border-right: 1px solid #303641;
    border-bottom: 1px solid #303641;
    padding: 7px;
    font-weight: 700;
}

QProgressBar {
    color: transparent;
    background-color: #11151a;
    border: 1px solid #303641;
    border-radius: 4px;
    min-height: 7px;
    max-height: 7px;
}

QProgressBar::chunk {
    background-color: #3d8bfd;
    border-radius: 3px;
}

QProgressBar#analysisProgress {
    background-color: #111923;
    border-color: #385776;
    min-height: 6px;
    max-height: 6px;
}

QProgressBar#analysisProgress::chunk {
    background-color: #55a1fb;
}

QSlider::groove:horizontal {
    background-color: #313844;
    height: 4px;
    border-radius: 2px;
}

QSlider::sub-page:horizontal {
    background-color: #438df2;
    border-radius: 2px;
}

QSlider::handle:horizontal {
    background-color: #e9eef5;
    border: 1px solid #ffffff;
    width: 12px;
    height: 12px;
    margin: -5px 0;
    border-radius: 6px;
}

QCheckBox {
    color: #c7ced8;
    spacing: 8px;
    min-height: 22px;
}

QCheckBox::indicator {
    width: 14px;
    height: 14px;
    border-radius: 3px;
    border: 1px solid #505a68;
    background-color: #11151a;
}

QCheckBox::indicator:checked {
    background-color: #3d8bfd;
    border-color: #64a3ff;
}

QCheckBox[track="vocals"]::indicator {
    border-color: #a94e55;
}

QCheckBox[track="drums"]::indicator {
    border-color: #a9763c;
}

QCheckBox[track="bass"]::indicator {
    border-color: #6e59a9;
}

QCheckBox[track="other"]::indicator {
    border-color: #378f80;
}

QCheckBox[track="vocals"]::indicator:checked {
    background-color: #ee5f67;
    border-color: #ff8187;
}

QCheckBox[track="drums"]::indicator:checked {
    background-color: #f1a84b;
    border-color: #ffc46f;
}

QCheckBox[track="bass"]::indicator:checked {
    background-color: #9674ed;
    border-color: #b49af6;
}

QCheckBox[track="other"]::indicator:checked {
    background-color: #42c8b1;
    border-color: #69ddc9;
}

QScrollBar:vertical {
    background-color: transparent;
    width: 10px;
    margin: 2px;
}

QScrollBar::handle:vertical {
    background-color: #3b434f;
    border-radius: 4px;
    min-height: 28px;
}

QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {
    background: transparent;
    height: 0;
}

QToolTip {
    color: #f3f6fa;
    background-color: #252b34;
    border: 1px solid #4a5462;
    padding: 5px;
}

"""


def apply_professional_theme(application: QApplication) -> None:
    """应用面向音乐工作站的深色视觉主题。"""
    application.setStyle("Fusion")
    font = application.font()
    font.setPointSize(13)
    application.setFont(font)
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor("#0d0f13"))
    palette.setColor(QPalette.ColorRole.WindowText, QColor("#e7ebf1"))
    palette.setColor(QPalette.ColorRole.Base, QColor("#11151a"))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor("#181c23"))
    palette.setColor(QPalette.ColorRole.Text, QColor("#e7ebf1"))
    palette.setColor(QPalette.ColorRole.Button, QColor("#262c35"))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor("#e7ebf1"))
    palette.setColor(QPalette.ColorRole.Highlight, QColor("#327eea"))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    palette.setColor(QPalette.ColorRole.PlaceholderText, QColor("#687383"))
    application.setPalette(palette)
    application.setStyleSheet(PRO_AUDIO_STYLESHEET)
