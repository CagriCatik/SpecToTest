"""Modern dark and light stylesheets and design tokens for SpecToTest GUI."""
from __future__ import annotations
from PySide6.QtGui import QFont, QFontDatabase


def get_monospace_font(size: int = 10, bold: bool = False) -> QFont:
    """Return platform-native monospace font without triggering font-alias lookup warnings."""
    font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
    if size > 0:
        font.setPointSize(size)
    if bold:
        font.setWeight(QFont.Weight.Bold)
    return font


def get_monospace_family() -> str:
    """Return the family name of the platform-native monospace font."""
    return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont).family()


# Central Design Tokens
THEME_TOKENS = {
    "dark": {
        "bg_app": "#18181d",
        "bg_surface": "#1e1e24",
        "bg_card": "#25252f",
        "bg_input": "#2b2b36",
        "border": "#33333f",
        "border_subtle": "#2a2a35",
        "text_primary": "#f0f0f4",
        "text_secondary": "#94a3b8",
        "text_muted": "#64748b",
        "accent": "#0d6efd",
        "accent_hover": "#0b5ed7",
        "accent_bg": "rgba(13, 110, 253, 0.15)",
        "success": "#10b981",
        "warning": "#f59e0b",
        "error": "#ef4444",
    },
    "light": {
        "bg_app": "#f1f3f5",
        "bg_surface": "#f8f9fa",
        "bg_card": "#ffffff",
        "bg_input": "#ffffff",
        "border": "#dee2e6",
        "border_subtle": "#e9ecef",
        "text_primary": "#212529",
        "text_secondary": "#495057",
        "text_muted": "#6c757d",
        "accent": "#0d6efd",
        "accent_hover": "#0b5ed7",
        "accent_bg": "rgba(13, 110, 253, 0.08)",
        "success": "#16a34a",
        "warning": "#d97706",
        "error": "#dc2626",
    },
}


def get_theme_tokens(dark_theme: bool = True) -> dict[str, str]:
    """Retrieve theme tokens for dynamic styling in Python widgets."""
    return THEME_TOKENS["dark"] if dark_theme else THEME_TOKENS["light"]


DARK_THEME_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e24;
    color: #f0f0f4;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #33333f;
    background-color: #25252f;
    border-radius: 6px;
}

QTabBar::tab {
    background: #1e1e24;
    color: #94a3b8;
    padding: 7px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid #33333f;
    border-bottom: none;
    font-weight: 500;
}

QTabBar::tab:selected {
    background: #25252f;
    color: #ffffff;
    border-bottom: 2px solid #0d6efd;
    font-weight: 600;
}

QGroupBox {
    border: 1px solid #33333f;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: 600;
    color: #94a3b8;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}

QLineEdit, QTextEdit, QComboBox {
    background-color: #2b2b36;
    border: 1px solid #3d3d4d;
    border-radius: 5px;
    padding: 5px 8px;
    color: #f0f0f4;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #0d6efd;
}

QPushButton {
    background-color: #2e2e3b;
    border: 1px solid #454558;
    border-radius: 5px;
    padding: 5px 13px;
    color: #e0e0e0;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #3b3b4c;
    border-color: #55556a;
}

QPushButton:pressed {
    background-color: #22222c;
}

QPushButton:disabled {
    background-color: #1a1a20;
    color: #64748b;
    border-color: #2a2a35;
}

QPushButton[primary="true"] {
    background-color: #0d6efd;
    border: 1px solid #0b5ed7;
    color: #ffffff;
    font-weight: 600;
}

QPushButton[primary="true"]:hover {
    background-color: #0b5ed7;
}

QPushButton[primary="true"]:disabled {
    background-color: #25334d;
    color: #64748b;
    border-color: #1e293b;
}

QTableWidget, QTreeWidget, QListWidget {
    background-color: #25252f;
    border: 1px solid #33333f;
    border-radius: 5px;
    gridline-color: #2f2f3d;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
    color: #f0f0f4;
}

QTableWidget::item, QTreeWidget::item, QListWidget::item {
    padding: 3px 6px;
}

QHeaderView::section {
    background-color: #1e1e24;
    color: #94a3b8;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #33333f;
    border-right: 1px solid #2a2a35;
    font-weight: 600;
}

QSplitter::handle {
    background-color: #282833;
}

QSplitter::handle:horizontal {
    width: 4px;
}

QSplitter::handle:vertical {
    height: 4px;
}

QSplitter::handle:hover {
    background-color: #0d6efd;
}

QScrollBar:vertical {
    border: none;
    background: #1e1e24;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #3e3e4f;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #505066;
}

QScrollBar:horizontal {
    border: none;
    background: #1e1e24;
    height: 8px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #3e3e4f;
    min-width: 20px;
    border-radius: 4px;
}

QStatusBar {
    background-color: #18181d;
    color: #94a3b8;
    border-top: 1px solid #2a2a35;
}

QToolTip {
    background-color: #1e1e24;
    color: #f0f0f4;
    border: 1px solid #454558;
    border-radius: 4px;
    padding: 4px 8px;
}
"""

LIGHT_THEME_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #f8f9fa;
    color: #212529;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #dee2e6;
    background-color: #ffffff;
    border-radius: 6px;
}

QTabBar::tab {
    background: #e9ecef;
    color: #495057;
    padding: 7px 16px;
    margin-right: 4px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    border: 1px solid #ced4da;
    border-bottom: none;
    font-weight: 500;
}

QTabBar::tab:selected {
    background: #ffffff;
    color: #0d6efd;
    border-bottom: 2px solid #0d6efd;
    font-weight: 600;
}

QGroupBox {
    border: 1px solid #dee2e6;
    border-radius: 6px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: 600;
    color: #495057;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
}

QLineEdit, QTextEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #ced4da;
    border-radius: 5px;
    padding: 5px 8px;
    color: #212529;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #0d6efd;
}

QPushButton {
    background-color: #ffffff;
    border: 1px solid #ced4da;
    border-radius: 5px;
    padding: 5px 13px;
    color: #212529;
    font-weight: 500;
}

QPushButton:hover {
    background-color: #f1f3f5;
    border-color: #adb5bd;
}

QPushButton:pressed {
    background-color: #e9ecef;
}

QPushButton:disabled {
    background-color: #e9ecef;
    color: #adb5bd;
    border-color: #dee2e6;
}

QPushButton[primary="true"] {
    background-color: #0d6efd;
    border: 1px solid #0b5ed7;
    color: #ffffff;
    font-weight: 600;
}

QPushButton[primary="true"]:hover {
    background-color: #0b5ed7;
}

QPushButton[primary="true"]:disabled {
    background-color: #e2e8f0;
    color: #94a3b8;
    border-color: #cbd5e1;
}

QTableWidget, QTreeWidget, QListWidget {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-radius: 5px;
    gridline-color: #f1f3f5;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
    color: #212529;
}

QTableWidget::item, QTreeWidget::item, QListWidget::item {
    padding: 3px 6px;
}

QHeaderView::section {
    background-color: #f8f9fa;
    color: #495057;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #dee2e6;
    border-right: 1px solid #e9ecef;
    font-weight: 600;
}

QSplitter::handle {
    background-color: #e2e8f0;
}

QSplitter::handle:horizontal {
    width: 4px;
}

QSplitter::handle:vertical {
    height: 4px;
}

QSplitter::handle:hover {
    background-color: #0d6efd;
}

QScrollBar:vertical {
    border: none;
    background: #f8f9fa;
    width: 8px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #ced4da;
    min-height: 20px;
    border-radius: 4px;
}

QScrollBar::handle:vertical:hover {
    background: #adb5bd;
}

QScrollBar:horizontal {
    border: none;
    background: #f8f9fa;
    height: 8px;
    margin: 0px;
}

QScrollBar::handle:horizontal {
    background: #ced4da;
    min-width: 20px;
    border-radius: 4px;
}

QStatusBar {
    background-color: #ffffff;
    color: #6c757d;
    border-top: 1px solid #dee2e6;
}

QToolTip {
    background-color: #ffffff;
    color: #212529;
    border: 1px solid #ced4da;
    border-radius: 4px;
    padding: 4px 8px;
}
"""

