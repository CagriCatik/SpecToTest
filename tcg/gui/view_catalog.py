"""Unified Operationskatalog Workspace combining Mappings and Operations perspectives."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.models import MappingStudioState
from tcg.gui.view_mappings import MappingsView
from tcg.gui.view_operations import OperationsView


class CatalogWorkspace(QWidget):
    """The Operationskatalog workspace with Mappings and Operations views."""

    test_sentence_requested = Signal(str)

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change

        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.sub_tabs = QTabWidget()

        self.view_mappings = MappingsView(self.state, on_change=self.on_child_change, parent=self)
        self.view_mappings.test_sentence_requested.connect(self.test_sentence_requested.emit)
        self.sub_tabs.addTab(self.view_mappings, "Mappings (Satzmuster ➔ Operation)")

        self.view_operations = OperationsView(self.state, on_change=self.on_child_change, parent=self)
        self.view_operations.test_sentence_requested.connect(self.test_sentence_requested.emit)
        self.sub_tabs.addTab(self.view_operations, "Operationen (Funktionen ➔ Satzmuster)")

        layout.addWidget(self.sub_tabs)

    def on_child_change(self):
        self.view_mappings.refresh()
        self.view_operations.refresh()
        self.on_change()

    def refresh(self):
        self.view_mappings.refresh()
        self.view_operations.refresh()
