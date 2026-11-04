"""Modern dark and light stylesheets for SpecToTest GUI."""

DARK_THEME_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #1e1e24;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    font-size: 13px;
}

QTabWidget::pane {
    border: 1px solid #33333f;
    background-color: #25252f;
    border-radius: 6px;
}

QTabBar::tab {
    background: #1e1e24;
    color: #a0a0b0;
    padding: 8px 18px;
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
    font-weight: bold;
}

QGroupBox {
    border: 1px solid #33333f;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: bold;
    color: #a0a0b0;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}

QLineEdit, QTextEdit, QComboBox {
    background-color: #2b2b36;
    border: 1px solid #3d3d4d;
    border-radius: 6px;
    padding: 6px 10px;
    color: #f0f0f0;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #0d6efd;
}

QPushButton {
    background-color: #2e2e3b;
    border: 1px solid #454558;
    border-radius: 6px;
    padding: 6px 14px;
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
    color: #666677;
    border-color: #2a2a35;
}

QTableWidget {
    background-color: #25252f;
    border: 1px solid #33333f;
    border-radius: 6px;
    gridline-color: #2f2f3d;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
}

QHeaderView::section {
    background-color: #1e1e24;
    color: #9090a0;
    padding: 6px 8px;
    border: none;
    border-bottom: 1px solid #33333f;
    border-right: 1px solid #2a2a35;
    font-weight: 600;
}

QScrollBar:vertical {
    border: none;
    background: #1e1e24;
    width: 10px;
    margin: 0px;
}

QScrollBar::handle:vertical {
    background: #3e3e4f;
    min-height: 20px;
    border-radius: 5px;
}

QScrollBar::handle:vertical:hover {
    background: #505066;
}

QStatusBar {
    background-color: #18181d;
    color: #888899;
    border-top: 1px solid #2a2a35;
}
"""

LIGHT_THEME_QSS = """
QMainWindow, QDialog, QWidget {
    background-color: #f8f9fa;
    color: #212529;
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
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
    padding: 8px 18px;
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
    font-weight: bold;
}

QGroupBox {
    border: 1px solid #dee2e6;
    border-radius: 8px;
    margin-top: 10px;
    padding-top: 14px;
    font-weight: bold;
    color: #495057;
}

QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    padding: 0 4px;
}

QLineEdit, QTextEdit, QComboBox {
    background-color: #ffffff;
    border: 1px solid #ced4da;
    border-radius: 6px;
    padding: 6px 10px;
    color: #212529;
}

QLineEdit:focus, QTextEdit:focus, QComboBox:focus {
    border: 1px solid #0d6efd;
}

QPushButton {
    background-color: #ffffff;
    border: 1px solid #ced4da;
    border-radius: 6px;
    padding: 6px 14px;
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

QTableWidget {
    background-color: #ffffff;
    border: 1px solid #dee2e6;
    border-radius: 6px;
    gridline-color: #f1f3f5;
    selection-background-color: #0d6efd;
    selection-color: #ffffff;
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

QStatusBar {
    background-color: #ffffff;
    color: #6c757d;
    border-top: 1px solid #dee2e6;
}
"""

