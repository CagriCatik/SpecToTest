"""Operationskatalog Workspace for inspecting operations, contracts, and managing sentence mappings."""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.dialog_editor import MappingEditorDialog
from tcg.gui.models import MappingItem, MappingStudioState, OperationInfo
from tcg.gui.styles import get_monospace_font
from tcg.gui.view_mappings import MappingsView


class CatalogWorkspace(QWidget):
    """The Operationskatalog workspace for exploring contracts, documentation, and mapping definitions."""

    test_sentence_requested = Signal(str)

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.current_selected_op: OperationInfo | None = None
        self.current_selected_mapping: MappingItem | None = None

        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.main_tabs = QTabWidget()

        # Tab 1: Operationskatalog (Operationen, Verträge & Satzmuster)
        ops_widget = self.build_operations_tab()
        self.main_tabs.addTab(ops_widget, "Operationen & Verträge")

        # Tab 2: Globale Mappings-Verwaltung
        self.view_mappings = MappingsView(self.state, on_change=self.on_child_change, parent=self)
        self.view_mappings.test_sentence_requested.connect(self.test_sentence_requested.emit)
        self.main_tabs.addTab(self.view_mappings, "Globale Mappings-Verwaltung")

        layout.addWidget(self.main_tabs)

    def build_operations_tab(self) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- LEFT: Operations List ---
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(8)

        left_layout.addWidget(QLabel("<b>Verfügbare Operationen:</b>"))

        self.op_search = QLineEdit()
        self.op_search.setPlaceholderText("Operation filtern...")
        self.op_search.textChanged.connect(self.filter_operations_list)
        left_layout.addWidget(self.op_search)

        self.op_filter_combo = QComboBox()
        self.op_filter_combo.addItems(["Alle Operationen", "Nur mit Satzmuster", "Nur ungemappte Lücken"])
        self.op_filter_combo.currentIndexChanged.connect(self.filter_operations_list)
        left_layout.addWidget(self.op_filter_combo)

        self.op_list = QListWidget()
        self.op_list.itemSelectionChanged.connect(self.on_op_selected)
        left_layout.addWidget(self.op_list)

        splitter.addWidget(left_panel)

        # --- RIGHT: Splitter (Contract/Doc | Associated Templates Table) ---
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(8)

        right_splitter = QSplitter(Qt.Orientation.Vertical)

        # 1. Top Section: Contract & Doc
        top_group = QGroupBox("Operationsvertrag & Dokumentation")
        top_layout = QVBoxLayout(top_group)
        top_layout.setSpacing(6)

        self.lbl_op_title = QLabel("Keine Operation ausgewählt")
        self.lbl_op_title.setFont(QFont("", 11, QFont.Weight.Bold))
        top_layout.addWidget(self.lbl_op_title)

        self.lbl_op_doc = QLabel("-")
        self.lbl_op_doc.setWordWrap(True)
        self.lbl_op_doc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        top_layout.addWidget(self.lbl_op_doc)

        self.lbl_op_meta = QLabel("-")
        top_layout.addWidget(self.lbl_op_meta)

        right_splitter.addWidget(top_group)

        # 2. Bottom Section: Associated Sentence Templates (Mappings)
        mid_group = QGroupBox("Zugeordnete Satzmuster (Mappings)")
        mid_layout = QVBoxLayout(mid_group)
        mid_layout.setSpacing(6)

        self.tmpl_table = QTableWidget(0, 4)
        self.tmpl_table.setHorizontalHeaderLabels(["Mapping-ID", "Satz-Template", "Parameter", "Verwendung im Projekt"])
        self.tmpl_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tmpl_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tmpl_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tmpl_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.tmpl_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.tmpl_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.tmpl_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.tmpl_table.itemSelectionChanged.connect(self.on_mapping_selected)
        mid_layout.addWidget(self.tmpl_table)

        btn_row = QHBoxLayout()
        self.btn_new_mapping = QPushButton("Neues Satzmuster anlegen")
        self.btn_new_mapping.clicked.connect(self.create_mapping_for_current_op)
        btn_row.addWidget(self.btn_new_mapping)

        self.btn_edit_mapping = QPushButton("Ausgewähltes Mapping bearbeiten")
        self.btn_edit_mapping.clicked.connect(self.edit_current_mapping)
        self.btn_edit_mapping.setEnabled(False)
        btn_row.addWidget(self.btn_edit_mapping)

        btn_row.addStretch()
        mid_layout.addLayout(btn_row)

        right_splitter.addWidget(mid_group)

        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 2)

        right_layout.addWidget(right_splitter)
        splitter.addWidget(right_panel)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        layout.addWidget(splitter)
        return container

    def refresh(self):
        self.filter_operations_list()
        self.view_mappings.refresh()

    def filter_operations_list(self):
        query = self.op_search.text().lower().strip()
        filter_mode = self.op_filter_combo.currentIndex()

        self.op_list.clear()
        for op_name, op_info in sorted(self.state.operations.items()):
            if query and query not in op_name.lower():
                continue
            if filter_mode == 1 and not op_info.is_mapped:
                continue
            if filter_mode == 2 and op_info.is_mapped:
                continue

            if not op_info.is_mapped:
                item = QListWidgetItem(f"{op_name}  [Lücke]")
                item.setForeground(QColor("#ef4444"))
            else:
                count_str = f"({op_info.valid_mappings_count})" if op_info.valid_mappings_count > 1 else ""
                item = QListWidgetItem(f"{op_name} {count_str}".strip())
            item.setData(Qt.ItemDataRole.UserRole, op_name)
            self.op_list.addItem(item)

        if self.op_list.count() > 0:
            self.op_list.setCurrentRow(0)

    def on_op_selected(self):
        items = self.op_list.selectedItems()
        if not items:
            self.current_selected_op = None
            self.update_op_details(None)
            return

        op_name = items[0].data(Qt.ItemDataRole.UserRole)
        op_info = self.state.operations.get(op_name)
        self.current_selected_op = op_info
        self.update_op_details(op_info)

    def update_op_details(self, op: OperationInfo | None):
        if not op:
            self.lbl_op_title.setText("Keine Operation ausgewählt")
            self.lbl_op_doc.setText("-")
            self.lbl_op_meta.setText("-")
            self.tmpl_table.setRowCount(0)
            self.btn_edit_mapping.setEnabled(False)
            return

        status_text = f"Gültig verknüpft ({op.valid_mappings_count} Mapping(s))" if op.is_mapped else "Lücke: Noch kein gültiges Satzmuster verknüpft"
        status_color = "#10b981" if op.is_mapped else "#ef4444"
        self.lbl_op_title.setText(f"<code>{op.name}</code> &nbsp; <span style='color: {status_color}; font-size: 11px;'>[{status_text}]</span>")
        self.lbl_op_doc.setText(op.docstring or "Keine Beschreibung vorhanden.")

        req_params = [f"<b>{p}</b>" for p in op.required_parameters]
        opt_params = op.optional_parameters
        param_desc = f"Pflicht: {', '.join(req_params) if req_params else 'keine'}"
        if opt_params:
            param_desc += f" &nbsp;|&nbsp; Optional: {', '.join(opt_params)}"
        self.lbl_op_meta.setText(f"Phasen: <code>{', '.join(op.phases)}</code> &nbsp;|&nbsp; Parameter: {param_desc}")

        # Update templates table
        self.tmpl_table.setRowCount(len(op.linked_mappings))
        for row, m in enumerate(op.linked_mappings):
            id_item = QTableWidgetItem(m.id)
            id_item.setFont(get_monospace_font(9, bold=True))
            self.tmpl_table.setItem(row, 0, id_item)

            tmpl_item = QTableWidgetItem(m.template)
            self.tmpl_table.setItem(row, 1, tmpl_item)

            param_str = ", ".join(f"{k} -> {v}" for k, v in m.parameters.items()) or "(keine)"
            self.tmpl_table.setItem(row, 2, QTableWidgetItem(param_str))

            # Impact
            impact = self.view_mappings.cached_impacts.get(m.id)
            if impact and impact.total_usages > 0:
                imp_str = f"{impact.total_usages}x in {len(impact.affected_cases)} Testfällen"
            else:
                imp_str = "0 Verwendungen"
            self.tmpl_table.setItem(row, 3, QTableWidgetItem(imp_str))

        if op.linked_mappings:
            self.tmpl_table.blockSignals(True)
            self.tmpl_table.selectRow(0)
            self.tmpl_table.blockSignals(False)
            self.current_selected_mapping = op.linked_mappings[0]
            self.btn_edit_mapping.setEnabled(True)
        else:
            self.current_selected_mapping = None
            self.btn_edit_mapping.setEnabled(False)

    def on_mapping_selected(self):
        if not self.current_selected_op:
            return
        selected_rows = self.tmpl_table.selectionModel().selectedRows()
        if not selected_rows:
            self.current_selected_mapping = None
            self.btn_edit_mapping.setEnabled(False)
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self.current_selected_op.linked_mappings):
            mapping = self.current_selected_op.linked_mappings[row]
            self.current_selected_mapping = mapping
            self.btn_edit_mapping.setEnabled(True)

    @property
    def current_op_name(self) -> str | None:
        return self.current_selected_op.name if self.current_selected_op else None

    @property
    def view_operations(self):
        return self

    @property
    def table_templates(self) -> QTableWidget:
        return self.tmpl_table

    def select_operation_by_name(self, op_name: str):
        for i in range(self.op_list.count()):
            item = self.op_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == op_name:
                self.op_list.setCurrentRow(i)
                return

    def create_mapping_for_current_op(self):
        if not self.current_selected_op:
            return
        dialog = MappingEditorDialog(
            self.state.registry,
            preselected_operation=self.current_selected_op.name,
            parent=self,
        )
        if dialog.exec():
            new_item = dialog.get_result_item()
            self.state.add_mapping(new_item)
            self.on_child_change()

    def edit_current_mapping(self):
        if not self.current_selected_mapping:
            return
        dialog = MappingEditorDialog(
            self.state.registry,
            existing_item=self.current_selected_mapping,
            parent=self,
        )
        if dialog.exec():
            updated = dialog.get_result_item()
            for idx, m in enumerate(self.state.mappings):
                if m.id == self.current_selected_mapping.id:
                    self.state.update_mapping(idx, updated)
                    break
            self.on_child_change()

    def on_child_change(self):
        self.refresh()
        self.on_change()
