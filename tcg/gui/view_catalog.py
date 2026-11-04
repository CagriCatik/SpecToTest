"""Unified Operationskatalog Workspace with Vice-Versa Sentence Generator and Mappings Management."""
from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.dialog_editor import MappingEditorDialog
from tcg.gui.facade import CompilationFacade
from tcg.gui.models import MappingItem, MappingStudioState, OperationInfo
from tcg.gui.view_mappings import MappingsView


class SmartParamWidget:
    """Helper holding input widgets and reading values for a parameter placeholder."""

    def __init__(self, val_widget: QWidget, unit_widget: QComboBox | None = None):
        self.val_widget = val_widget
        self.unit_widget = unit_widget
        self.spinbox = val_widget  # convenient alias for test access
        self.unit_combo = unit_widget

    def get_value_string(self) -> str:
        if isinstance(self.val_widget, QDoubleSpinBox):
            val = self.val_widget.value()
            return str(int(val)) if val.is_integer() else str(val)
        elif isinstance(self.val_widget, QComboBox):
            return str(self.val_widget.currentData() or self.val_widget.currentText())
        elif isinstance(self.val_widget, QLineEdit):
            return self.val_widget.text().strip()
        return ""

    def get_unit_string(self) -> str:
        if self.unit_widget and isinstance(self.unit_widget, QComboBox):
            return str(self.unit_widget.currentData() or "")
        return ""


class CatalogWorkspace(QWidget):
    """The Operationskatalog workspace with the interactive Vice-Versa generator and mapping management."""

    test_sentence_requested = Signal(str)
    insert_sentence_into_spec = Signal(str)

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.current_selected_op: OperationInfo | None = None
        self.current_selected_mapping: MappingItem | None = None
        self.param_inputs: dict[str, QWidget] = {}

        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(6)

        self.main_tabs = QTabWidget()

        # Tab 1: Operations-Arbeitsplatz & Satz-Generator (Vice Versa)
        vice_versa_widget = self.build_vice_versa_tab()
        self.main_tabs.addTab(vice_versa_widget, "Operationskatalog & Satz-Generator (Vice Versa)")

        # Tab 2: Globale Mappings-Verwaltung
        self.view_mappings = MappingsView(self.state, on_change=self.on_child_change, parent=self)
        self.view_mappings.test_sentence_requested.connect(self.test_sentence_requested.emit)
        self.main_tabs.addTab(self.view_mappings, "Globale Mappings-Verwaltung")

        layout.addWidget(self.main_tabs)

    def build_vice_versa_tab(self) -> QWidget:
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

        # --- RIGHT: Splitter (Contract/Doc | Mappings Table | Vice-Versa Generator) ---
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

        # 2. Middle Section: Associated Sentence Templates
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

        # 3. Bottom Section: Vice-Versa Parameter Form & Sentence Generator
        bottom_group = QGroupBox("Satz-Generator & Einfüge-Assistent (Vice Versa: Operation ➔ Spezifikationsschritt)")
        bottom_layout = QVBoxLayout(bottom_group)
        bottom_layout.setSpacing(8)

        # Parameter Form container
        self.form_container = QWidget()
        self.form_layout = QVBoxLayout(self.form_container)
        self.form_layout.setContentsMargins(0, 0, 0, 0)
        bottom_layout.addWidget(self.form_container)

        # Sentence Preview Box
        bottom_layout.addWidget(QLabel("<b>Erzeugter Spezifikationssatz:</b>"))
        self.lbl_generated_sentence = QLineEdit()
        self.lbl_generated_sentence.setFont(QFont("Monospace", 10, QFont.Weight.Bold))
        bottom_layout.addWidget(self.lbl_generated_sentence)

        # Verification result
        self.lbl_verify_result = QLabel("")
        self.lbl_verify_result.setWordWrap(True)
        bottom_layout.addWidget(self.lbl_verify_result)

        # Actions
        action_row = QHBoxLayout()
        self.btn_generate_sentence = QPushButton("Satz erzeugen")
        self.btn_generate_sentence.clicked.connect(self.generate_vice_versa_sentence)
        action_row.addWidget(self.btn_generate_sentence)

        self.btn_verify_sentence = QPushButton("Satz prüfen (Gegenprobe)")
        self.btn_verify_sentence.clicked.connect(lambda: self.verify_generated_sentence())
        action_row.addWidget(self.btn_verify_sentence)

        self.btn_insert_spec = QPushButton("In Spezifikation einfügen")
        self.btn_insert_spec.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        self.btn_insert_spec.clicked.connect(self.insert_into_active_specification)
        action_row.addWidget(self.btn_insert_spec)

        action_row.addStretch()
        bottom_layout.addLayout(action_row)

        right_splitter.addWidget(bottom_group)

        right_splitter.setStretchFactor(0, 1)
        right_splitter.setStretchFactor(1, 2)
        right_splitter.setStretchFactor(2, 2)

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

            status_str = f"[{op_info.valid_mappings_count} Muster]" if op_info.is_mapped else "[Lücke]"
            item = QListWidgetItem(f"{op_name}  {status_str}")
            item.setData(Qt.ItemDataRole.UserRole, op_name)
            if not op_info.is_mapped:
                item.setForeground(QColor("#ef4444"))
            else:
                item.setForeground(QColor("#10b981"))
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
            self.build_parameter_form(None)
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
            id_item.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
            self.tmpl_table.setItem(row, 0, id_item)

            tmpl_item = QTableWidgetItem(m.template)
            self.tmpl_table.setItem(row, 1, tmpl_item)

            param_str = ", ".join(f"{k}➔{v}" for k, v in m.parameters.items()) or "(keine)"
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
            self.build_parameter_form(self.current_selected_mapping)
        else:
            self.current_selected_mapping = None
            self.btn_edit_mapping.setEnabled(False)
            self.build_parameter_form(None)

    def on_mapping_selected(self):
        if not self.current_selected_op:
            return
        selected_rows = self.tmpl_table.selectionModel().selectedRows()
        if not selected_rows:
            self.current_selected_mapping = None
            self.btn_edit_mapping.setEnabled(False)
            self.build_parameter_form(None)
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self.current_selected_op.linked_mappings):
            mapping = self.current_selected_op.linked_mappings[row]
            self.current_selected_mapping = mapping
            self.btn_edit_mapping.setEnabled(True)
            self.build_parameter_form(mapping)

    def build_parameter_form(self, mapping: MappingItem | None):
        """Construct smart input fields for all placeholders of the selected template."""
        # Clear existing fields
        while self.form_layout.count():
            child = self.form_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()

        self.param_inputs.clear()
        self.lbl_verify_result.clear()

        if not mapping or not self.current_selected_op:
            self.lbl_generated_sentence.clear()
            self.btn_verify_sentence.setEnabled(False)
            self.btn_insert_spec.setEnabled(False)
            return

        contract = self.state.registry.get(mapping.operation)
        placeholders = mapping.placeholders

        if not placeholders:
            # Static sentence without placeholders (e.g. "Zündung an" or "Dienst neu starten")
            info_lbl = QLabel(f"Dieses Satzmuster benötigt keine Parameter (statischer Befehl).")
            info_lbl.setStyleSheet("color: #64748b; font-style: italic;")
            self.form_layout.addWidget(info_lbl)
            self.lbl_generated_sentence.setText(mapping.template)
            self.btn_verify_sentence.setEnabled(True)
            self.btn_insert_spec.setEnabled(True)
            return

        # Build dynamic rows for each placeholder
        for ph in placeholders:
            target_param_name = mapping.parameters.get(ph)
            param_spec = contract.parameter(target_param_name) if contract and target_param_name else None

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.setSpacing(8)

            lbl = QLabel(f"{{{ph}}} ({target_param_name or 'unbekannt'}):")
            lbl.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
            lbl.setMinimumWidth(140)
            row_layout.addWidget(lbl)

            smart_widget = self.create_smart_input_for_param(param_spec, ph)
            row_layout.addWidget(smart_widget.val_widget, stretch=2)
            if smart_widget.unit_widget:
                row_layout.addWidget(smart_widget.unit_widget)

            self.form_layout.addWidget(row_widget)
            self.param_inputs[ph] = smart_widget

        self.btn_verify_sentence.setEnabled(True)
        self.btn_insert_spec.setEnabled(True)
        self.update_generated_sentence_preview()

    def create_smart_input_for_param(self, param_spec, ph_name: str) -> SmartParamWidget:
        """Create field suited to the parameter type (Quantity, Boolean, Resource, Decimal)."""
        if not param_spec:
            line_edit = QLineEdit("10")
            line_edit.textChanged.connect(self.update_generated_sentence_preview)
            return SmartParamWidget(line_edit, None)

        t = param_spec.type
        type_name = type(t).__name__

        # 1. Quantity with unit (voltage, time, can_signal)
        if hasattr(t, 'unit') and t.unit:
            spinbox = QDoubleSpinBox()
            spinbox.setRange(0, 1000000)
            spinbox.setDecimals(2)

            unit_combo = QComboBox()
            units = [factor[0] for factor in getattr(t, 'factors', ())]
            if not units and t.unit:
                units = [t.unit]
            for u in units:
                unit_combo.addItem(u if u else "(keine Einheit)", u)

            # Heuristics for default values
            if t.dimension == 'voltage':
                spinbox.setValue(12)
            elif t.dimension == 'time':
                spinbox.setValue(500 if "ms" in units else 1)
                if "ms" in units:
                    unit_combo.setCurrentText("ms")
            else:
                spinbox.setValue(10)

            spinbox.valueChanged.connect(self.update_generated_sentence_preview)
            unit_combo.currentIndexChanged.connect(self.update_generated_sentence_preview)
            return SmartParamWidget(spinbox, unit_combo)

        # 2. Boolean ('an' / 'aus', 'aktiv' / 'inaktiv')
        if hasattr(t, 'true_value') and hasattr(t, 'false_value'):
            combo = QComboBox()
            combo.addItem(t.true_value, t.true_value)
            combo.addItem(t.false_value, t.false_value)
            combo.currentIndexChanged.connect(self.update_generated_sentence_preview)
            return SmartParamWidget(combo, None)

        # 3. Resource profile values (controller, diagnostic_code, signal, screen)
        if hasattr(t, 'kind') and t.kind:
            res_list = self.state.profile.resources.get(t.kind, [])
            if res_list:
                combo = QComboBox()
                for r in res_list:
                    combo.addItem(r, r)
                combo.currentIndexChanged.connect(self.update_generated_sentence_preview)
                return SmartParamWidget(combo, None)

        # Default string/decimal input
        line_edit = QLineEdit("10" if "value" in ph_name or "wert" in ph_name else "default")
        line_edit.textChanged.connect(self.update_generated_sentence_preview)
        return SmartParamWidget(line_edit, None)

    def update_generated_sentence_preview(self):
        """Assemble the complete sentence from current parameter inputs."""
        if not self.current_selected_mapping:
            return

        template = self.current_selected_mapping.template
        for ph, widget in self.param_inputs.items():
            val = widget.get_value_string()
            unit = widget.get_unit_string()
            if unit:
                val = f"{val} {unit}" if unit in ('s', 'ms', 'rpm', 'km/h', 'Ohm') else f"{val}{unit}"

            template = template.replace(f"{{{ph}}}", str(val))

        self.lbl_generated_sentence.setText(template)
        self.lbl_verify_result.clear()

    def generate_vice_versa_sentence(self):
        self.update_generated_sentence_preview()

    def verify_generated_sentence(self, sentence: str | None = None) -> tuple[bool, str | None, dict[str, Any], str | None]:
        """Perform reverse check: Resolve generated sentence back through the compiler resolver."""
        if sentence is not None:
            self.lbl_generated_sentence.setText(sentence)
        s = self.lbl_generated_sentence.text().strip()
        if not s:
            return False, None, {}, "Leerer Satz"

        res = self.state.test_sentence(s)
        if res['success'] and res['matched']:
            op_name = res['operation']
            args = res['arguments']
            args_str = ", ".join(f"{k}={v!r}" for k, v in args.items())
            call_code = f"{op_name}(bench, {args_str})"

            is_target_op = (self.current_selected_op and op_name == self.current_selected_op.name)
            if is_target_op:
                self.lbl_verify_result.setText(
                    f"<span style='color: #10b981; font-weight: bold;'>Gültig aufgelöst:</span> "
                    f"<code>{call_code}</code> &nbsp;<span style='color: #64748b;'>(Phasen: {', '.join(res['allowed_phases'])})</span>"
                )
            else:
                self.lbl_verify_result.setText(
                    f"<span style='color: #f59e0b; font-weight: bold;'>Warnung:</span> "
                    f"Satz wurde nicht zu '{self.current_selected_op.name}', sondern zu '<code>{op_name}</code>' aufgelöst."
                )
            return True, op_name, args, None
        else:
            err = res.get('error', 'Unbekannter Fehler')
            self.lbl_verify_result.setText(
                f"<span style='color: #ef4444; font-weight: bold;'>Fehler beim Auflösen:</span> {err}"
            )
            return False, None, {}, err

    @property
    def current_op_name(self) -> str | None:
        return self.current_selected_op.name if self.current_selected_op else None

    @property
    def table_templates(self) -> QTableWidget:
        return self.tmpl_table

    @property
    def txt_preview_sentence(self) -> QLineEdit:
        return self.lbl_generated_sentence

    def select_operation_by_name(self, op_name: str):
        for i in range(self.op_list.count()):
            item = self.op_list.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == op_name:
                self.op_list.setCurrentRow(i)
                return

    def insert_into_active_specification(self):
        """Emit verified sentence to be inserted into the open specification editor."""
        sentence = self.lbl_generated_sentence.text().strip()
        if not sentence:
            return
        self.insert_sentence_into_spec.emit(sentence)

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
            # Find index
            for idx, m in enumerate(self.state.mappings):
                if m.id == self.current_selected_mapping.id:
                    self.state.update_mapping(idx, updated)
                    break
            self.on_child_change()

    def on_child_change(self):
        self.refresh()
        self.on_change()
