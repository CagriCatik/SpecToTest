"""Interactive Mapping & Operation Linker Dialog in PySide6."""
from __future__ import annotations

import re
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from tcg.core.contracts import OperationContract, ParameterSpec
from tcg.gui.models import MappingItem, extract_template_placeholders, validate_single_mapping


class MappingEditorDialog(QDialog):
    """Dialog for creating or editing a sentence template mapping and linking it to an operation."""

    def __init__(
        self,
        registry: dict[str, OperationContract],
        existing_item: MappingItem | None = None,
        preselected_operation: str | None = None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.registry = registry
        self.existing_item = existing_item
        self.preselected_operation = preselected_operation
        self.param_combos: dict[str, QComboBox] = {}

        self.setWindowTitle("Mapping & Operation verknüpfen" if not existing_item else f"Mapping bearbeiten: {existing_item.id}")
        self.setMinimumSize(700, 620)
        self.setup_ui()
        self.load_data()
        self.validate_live()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(14)

        # 1. Header info
        header_lbl = QLabel(
            "<b>Verknüpfe ein natürliches Satzmuster mit einer Python-Operation</b><br>"
            "<span style='color: #888;'>Definiere Platzhalter in geschweiften Klammern (z.B. {spannung}) und binde sie an Operationsparameter.</span>"
        )
        header_lbl.setTextFormat(Qt.TextFormat.RichText)
        main_layout.addWidget(header_lbl)

        # 2. Main Form (ID, Template, Operation)
        form_group = QGroupBox("Mapping-Definition")
        form_layout = QFormLayout(form_group)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Mapping ID
        id_layout = QHBoxLayout()
        self.id_edit = QLineEdit()
        self.id_edit.setPlaceholderText("z.B. MAP_BATTERY_VOLTAGE")
        self.id_edit.textChanged.connect(self.validate_live)
        id_layout.addWidget(self.id_edit)

        self.btn_auto_id = QPushButton("ID generieren")
        self.btn_auto_id.setToolTip("ID automatisch aus Operation oder Template ableiten")
        self.btn_auto_id.clicked.connect(self.auto_generate_id)
        id_layout.addWidget(self.btn_auto_id)
        form_layout.addRow("Mapping-ID:", id_layout)

        # Template
        self.template_edit = QLineEdit()
        self.template_edit.setPlaceholderText("z.B. Batteriespannung = {spannung} oder Warte {dauer}")
        self.template_edit.textChanged.connect(self.on_template_changed)
        form_layout.addRow("Satz-Template:", self.template_edit)

        # Detected placeholders info
        self.placeholders_lbl = QLabel("Keine Platzhalter erkannt")
        self.placeholders_lbl.setStyleSheet("color: #0d6efd; font-weight: bold;")
        form_layout.addRow("Erkannte Platzhalter:", self.placeholders_lbl)

        # Operation Dropdown
        self.op_combo = QComboBox()
        self.op_combo.addItem("-- Operation auswählen --", None)
        for op_name in sorted(self.registry.keys()):
            self.op_combo.addItem(op_name, op_name)
        self.op_combo.currentIndexChanged.connect(self.on_operation_changed)
        form_layout.addRow("Ziel-Operation:", self.op_combo)

        main_layout.addWidget(form_group)

        # 3. Operation Info Card
        self.op_info_group = QGroupBox("Operations-Details")
        op_info_layout = QVBoxLayout(self.op_info_group)
        self.op_doc_lbl = QLabel("Keine Operation gewählt.")
        self.op_doc_lbl.setWordWrap(True)
        self.op_phases_lbl = QLabel("")
        op_info_layout.addWidget(self.op_doc_lbl)
        op_info_layout.addWidget(self.op_phases_lbl)
        main_layout.addWidget(self.op_info_group)

        # 4. Parameter Binding Matrix
        self.binding_group = QGroupBox("Parameter-Verknüpfungen (Platzhalter ➔ Parameter)")
        binding_layout = QVBoxLayout(self.binding_group)

        self.binding_table = QTableWidget(0, 4)
        self.binding_table.setHorizontalHeaderLabels([
            "Platzhalter im Satz", "➔ Operations-Parameter", "Erwarteter Typ / Einheit", "Status"
        ])
        self.binding_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.binding_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.binding_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.binding_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        binding_layout.addWidget(self.binding_table)

        main_layout.addWidget(self.binding_group)

        # 5. Live Validation Status Banner
        self.status_banner = QLabel()
        self.status_banner.setWordWrap(True)
        self.status_banner.setContentsMargins(10, 8, 10, 8)
        self.status_banner.setTextFormat(Qt.TextFormat.RichText)
        main_layout.addWidget(self.status_banner)

        # 6. Dialog Buttons
        self.button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.btn_ok = self.button_box.button(QDialogButtonBox.StandardButton.Ok)
        self.btn_ok.setText("Mapping übernehmen")
        self.button_box.accepted.connect(self.on_accept)
        self.button_box.rejected.connect(self.reject)
        main_layout.addWidget(self.button_box)

    def load_data(self):
        """Populate fields from existing item or preselected operation."""
        if self.existing_item:
            self.id_edit.setText(self.existing_item.id)
            self.template_edit.setText(self.existing_item.template)
            idx = self.op_combo.findData(self.existing_item.operation)
            if idx >= 0:
                self.op_combo.setCurrentIndex(idx)
        elif self.preselected_operation:
            idx = self.op_combo.findData(self.preselected_operation)
            if idx >= 0:
                self.op_combo.setCurrentIndex(idx)
            self.auto_generate_id()

        self.rebuild_binding_table()

    def on_template_changed(self):
        placeholders = extract_template_placeholders(self.template_edit.text())
        if placeholders:
            self.placeholders_lbl.setText(", ".join(f"{{{p}}}" for p in placeholders))
        else:
            self.placeholders_lbl.setText("Keine Platzhalter erkannt (statischer Befehl)")
        self.rebuild_binding_table()
        self.validate_live()

    def on_operation_changed(self):
        op_name = self.op_combo.currentData()
        if op_name and op_name in self.registry:
            contract = self.registry[op_name]
            doc = ''
            if contract.function and hasattr(contract.function, '__doc__') and contract.function.__doc__:
                doc = contract.function.__doc__.strip()
            self.op_doc_lbl.setText(f"<b>Dokumentation:</b> {doc or 'Keine Dokumentation vorhanden.'}")
            phases = ", ".join(sorted(contract.phases))
            self.op_phases_lbl.setText(f"<b>Zulässige Phasen:</b> {phases}")
        else:
            self.op_doc_lbl.setText("Keine Operation gewählt.")
            self.op_phases_lbl.setText("")

        self.rebuild_binding_table()
        self.validate_live()

    def rebuild_binding_table(self):
        """Reconstruct the parameter binding table based on detected placeholders and operation params."""
        template = self.template_edit.text()
        placeholders = extract_template_placeholders(template)
        op_name = self.op_combo.currentData()
        contract = self.registry.get(op_name) if op_name else None

        existing_bindings = {}
        if self.existing_item and self.existing_item.operation == op_name:
            existing_bindings = dict(self.existing_item.parameters)

        self.binding_table.setRowCount(len(placeholders))
        self.param_combos.clear()

        op_params = list(contract.parameters) if contract else []
        param_names = [p.name for p in op_params]

        for row, ph in enumerate(placeholders):
            # 1. Placeholder item
            ph_item = QTableWidgetItem(f"{{{ph}}}")
            ph_item.setFont(QFont("Monospace", 10, QFont.Weight.Bold))
            ph_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.binding_table.setItem(row, 0, ph_item)

            # 2. Combo for operation parameter
            combo = QComboBox()
            combo.addItem("-- Nicht zugeordnet --", "")
            for p in op_params:
                label = f"{p.name} {'(Pflicht)' if p.required else '(optional)'}"
                combo.addItem(label, p.name)

            # Preselection heuristic
            target_param = existing_bindings.get(ph)
            if not target_param:
                if ph in param_names:
                    target_param = ph
                elif len(op_params) == 1:
                    target_param = op_params[0].name
                elif ph in ('spannung', 'wert', 'dauer', 'zeit', 'seconds', 'val') and 'value' in param_names:
                    target_param = 'value'
                elif ph in ('dauer', 'zeit', 'zeitgrenze') and 'seconds' in param_names:
                    target_param = 'seconds'
                elif ph in ('dauer', 'zeit') and 'duration' in param_names:
                    target_param = 'duration'
                elif ph in ('steuergeraet', 'ecu', 'controller') and 'ecu' in param_names:
                    target_param = 'ecu'
                elif ph in ('steuergeraet', 'ecu', 'controller') and 'controller' in param_names:
                    target_param = 'controller'
                elif ph in ('signal', 'can_signal') and 'signal' in param_names:
                    target_param = 'signal'
                elif ph in ('zustand', 'status', 'state') and 'state' in param_names:
                    target_param = 'state'
                elif ph in ('code', 'dtc') and 'code' in param_names:
                    target_param = 'code'

            if target_param:
                idx = combo.findData(target_param)
                if idx >= 0:
                    combo.setCurrentIndex(idx)

            combo.currentIndexChanged.connect(self.validate_live)
            self.param_combos[ph] = combo
            self.binding_table.setCellWidget(row, 1, combo)

            # 3. Type description item
            type_item = QTableWidgetItem()
            type_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.binding_table.setItem(row, 2, type_item)

            # 4. Status item
            status_item = QTableWidgetItem()
            status_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.binding_table.setItem(row, 3, status_item)

        self.update_binding_row_types()

    def update_binding_row_types(self):
        """Update type and status descriptions in the binding table."""
        op_name = self.op_combo.currentData()
        contract = self.registry.get(op_name) if op_name else None

        for row in range(self.binding_table.rowCount()):
            ph_item = self.binding_table.item(row, 0)
            if not ph_item:
                continue
            ph = ph_item.text().strip('{}')
            combo = self.param_combos.get(ph)
            selected_param = combo.currentData() if combo else None

            type_item = self.binding_table.item(row, 2)
            status_item = self.binding_table.item(row, 3)

            if contract and selected_param:
                param_spec = contract.parameter(selected_param)
                if param_spec:
                    t = param_spec.type
                    type_str = type(t).__name__
                    if hasattr(t, 'unit') and t.unit:
                        type_str += f" ({t.dimension}, Einheit: {t.unit})"
                    elif hasattr(t, 'kind') and t.kind:
                        type_str += f" (Ressource: {t.kind})"
                    elif hasattr(t, 'true_value'):
                        type_str += f" (Bool: '{t.true_value}' / '{t.false_value}')"
                    if type_item:
                        type_item.setText(type_str)

                    if status_item:
                        status_item.setText("✅ Zugeordnet")
                        status_item.setForeground(QColor("#198754"))
                else:
                    if type_item:
                        type_item.setText("-")
                    if status_item:
                        status_item.setText("⚠️ Unbekannt")
                        status_item.setForeground(QColor("#dc3545"))
            else:
                if type_item:
                    type_item.setText("-")
                if status_item:
                    status_item.setText("❌ Nicht gebunden")
                    status_item.setForeground(QColor("#dc3545"))

    def get_bindings(self) -> dict[str, str]:
        bindings = {}
        for ph, combo in self.param_combos.items():
            param = combo.currentData()
            if param:
                bindings[ph] = param
        return bindings

    def auto_generate_id(self):
        op_name = self.op_combo.currentData()
        template = self.template_edit.text()
        if op_name:
            candidate = f"MAP_{op_name.upper()}"
        elif template:
            clean = re.sub(r'\{[a-z0-9_]+\}', '', template)
            words = [w for w in re.split(r'[^a-zA-Z0-9]+', clean) if w]
            candidate = "MAP_" + "_".join(words[:4]).upper()
        else:
            candidate = "MAP_NEW"
        self.id_edit.setText(candidate)

    def validate_live(self):
        """Validate live and update status banner and OK button."""
        self.update_binding_row_types()

        ident = self.id_edit.text().strip()
        template = self.template_edit.text().strip()
        op_name = self.op_combo.currentData() or ""
        bindings = self.get_bindings()

        is_valid, error, _ = validate_single_mapping(
            ident, template, op_name, bindings, self.registry
        )

        if is_valid:
            contract = self.registry[op_name]
            phases = ", ".join(sorted(contract.phases))
            self.status_banner.setStyleSheet(
                "background-color: #d1e7dd; color: #0f5132; border: 1px solid #badbcc; border-radius: 6px; padding: 8px;"
            )
            self.status_banner.setText(
                f"<b>✅ Gültig verknüpft!</b> Alle Pflichtparameter sind zugewiesen. Erlaubte Phasen: <code>{phases}</code>"
            )
            self.btn_ok.setEnabled(True)
        else:
            self.status_banner.setStyleSheet(
                "background-color: #f8d7da; color: #842029; border: 1px solid #f5c2c7; border-radius: 6px; padding: 8px;"
            )
            self.status_banner.setText(f"<b>⚠️ Noch nicht vollständig:</b> {error}")
            self.btn_ok.setEnabled(False)

    def on_accept(self):
        ident = self.id_edit.text().strip()
        template = self.template_edit.text().strip()
        op_name = self.op_combo.currentData() or ""
        bindings = self.get_bindings()

        is_valid, error, _ = validate_single_mapping(
            ident, template, op_name, bindings, self.registry
        )
        if not is_valid:
            QMessageBox.warning(self, "Ungültiges Mapping", f"Das Mapping kann so nicht gespeichert werden:\n\n{error}")
            return

        self.accept()

    def get_result_item(self) -> MappingItem:
        return MappingItem(
            id=self.id_edit.text().strip(),
            template=self.template_edit.text().strip(),
            operation=self.op_combo.currentData() or "",
            parameters=self.get_bindings(),
        )
