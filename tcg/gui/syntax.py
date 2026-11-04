"""Syntax highlighter for SpecToTest TXT and Markdown specifications."""
from __future__ import annotations

import re

from PySide6.QtCore import QRegularExpression
from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat


class SpecSyntaxHighlighter(QSyntaxHighlighter):
    """Highlights sections, step numbers, control flow loops, and variables in test specifications."""

    def __init__(self, parent=None, dark_theme: bool = True):
        super().__init__(parent)
        self.dark_theme = dark_theme
        self.rules = []
        self._setup_formats()

    def set_dark_theme(self, dark: bool):
        self.dark_theme = dark
        self._setup_formats()
        self.rehighlight()

    def _setup_formats(self):
        self.rules.clear()

        # Color palette
        if self.dark_theme:
            c_section = QColor("#60a5fa")     # Blue
            c_step = QColor("#fbbf24")        # Amber / Yellow
            c_keyword = QColor("#c084fc")     # Purple (FOR / END FOR / BREAK)
            c_comment = QColor("#64748b")     # Slate Gray
            c_string = QColor("#34d399")      # Green
            c_variable = QColor("#38bdf8")    # Sky Blue
            c_quantity = QColor("#f472b6")    # Pink
        else:
            c_section = QColor("#1d4ed8")
            c_step = QColor("#b45309")
            c_keyword = QColor("#7e22ce")
            c_comment = QColor("#64748b")
            c_string = QColor("#047857")
            c_variable = QColor("#0284c7")
            c_quantity = QColor("#be185d")

        # 1. Section Headings (e.g. ## Precondition, ## Action, # Testfall TC_01)
        fmt_section = QTextCharFormat()
        fmt_section.setForeground(c_section)
        fmt_section.setFontWeight(QFont.Weight.Bold)
        self.rules.append((
            QRegularExpression(r'^(#+\s*.*|Preconditions?:?|Vorbedingungen:?|Actions?:?|Ablauf:?|Testschritte:?|Postconditions?:?|Nachbedingungen:?|Expected(?:\s+Results?)?:?|Erwartete(?:\s+Ergebnisse?)?:?|Erwartungen:?|Anforderung:?|Requirements?:?)'),
            fmt_section
        ))

        # 2. Step Numbers (e.g. "10.", "20:")
        fmt_step = QTextCharFormat()
        fmt_step.setForeground(c_step)
        fmt_step.setFontWeight(QFont.Weight.Bold)
        self.rules.append((
            QRegularExpression(r'^\s*([0-9]+)[.:]'),
            fmt_step
        ))

        # 3. Control Flow Keywords (FOR, END FOR, WHILE, END WHILE, BREAK, IF, ELSE IF, ELSE, END IF, SWITCH, CASE, DEFAULT, END SWITCH, AND, OR)
        fmt_keyword = QTextCharFormat()
        fmt_keyword.setForeground(c_keyword)
        fmt_keyword.setFontWeight(QFont.Weight.Bold)
        self.rules.append((
            QRegularExpression(r'\b(FOR|END\s+FOR|WHILE|END\s+WHILE|BREAK|IF|ELSE\s+IF|ELSE|END\s+IF|SWITCH|CASE|DEFAULT|END\s+SWITCH|AND|OR)\b', QRegularExpression.PatternOption.CaseInsensitiveOption),
            fmt_keyword
        ))

        # 4. Variables & Placeholders (e.g. {var} or loop variable in FOR (v; [...]))
        fmt_variable = QTextCharFormat()
        fmt_variable.setForeground(c_variable)
        self.rules.append((
            QRegularExpression(r'\{[A-Za-z0-9_]+\}'),
            fmt_variable
        ))

        # 5. String Literals ("...")
        fmt_string = QTextCharFormat()
        fmt_string.setForeground(c_string)
        self.rules.append((
            QRegularExpression(r'"[^"\\]*(\\.[^"\\]*)*"'),
            fmt_string
        ))

        # 6. Quantities and units (e.g. 13.8V, 7000mV, 500 ms, 1 s, 2500 rpm)
        fmt_quantity = QTextCharFormat()
        fmt_quantity.setForeground(c_quantity)
        fmt_quantity.setFontWeight(QFont.Weight.Bold)
        self.rules.append((
            QRegularExpression(r'\b[0-9]+(?:\.[0-9]+)?\s*(?:V|mV|s|ms|rpm|km/h|°C|degC|Ohm|kOhm|kW|W|A|mA)\b'),
            fmt_quantity
        ))

        # 7. Single-line Comments (# ... or // ...)
        fmt_comment = QTextCharFormat()
        fmt_comment.setForeground(c_comment)
        fmt_comment.setFontItalic(True)
        self.rules.append((
            QRegularExpression(r'(#|//).*$'),
            fmt_comment
        ))

    def highlightBlock(self, text: str):
        for pattern, fmt in self.rules:
            match_iterator = pattern.globalMatch(text)
            while match_iterator.hasNext():
                match = match_iterator.next()
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)
