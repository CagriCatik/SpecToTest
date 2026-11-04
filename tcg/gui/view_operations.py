"""Operations-to-Mappings view ("Vice Versa") for SpecToTest GUI."""
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
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.dialog_editor import MappingEditorDialog
from tcg.gui.models import MappingStudioState, OperationInfo


class OperationsView(QWidget):
    """View showing all registered operations and the sentence mappings linked to them."""

    test_sentence_requested = Signal(str)

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.current_selected_op_name: str | None = None
        self.filtered_op_names: list[str] = []

        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 1. Filter Bar
        filter_box = QHBoxLayout()
        filter_box.setSpacing(10)

        filter_box.addWidget(QLabel("🔍 Suche:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Nach Operationsname oder Docstring filtern...")
        self.search_edit.textChanged.connect(self.apply_filter)
        filter_box.addWidget(self.search_edit, stretch=2)

        filter_box.addWidget(QLabel("Filter:"))
        self.coverage_filter = QComboBox()
        self.coverage_filter.addItems(["Alle Operationen", "Nur mit Verknüpfung", "⚠️ Nur ungemappte Lücken"])
        self.coverage_filter.currentIndexChanged.connect(self.apply_filter)
        filter_box.addWidget(self.coverage_filter)

        filter_box.addWidget(QLabel("Phase:"))
        self.phase_filter = QComboBox()
        self.phase_filter.addItems(["Alle Phasen", "Nur SETUP (Action/Pre/Post)", "Nur CHECK (Expected)"])
        self.phase_filter.currentIndexChanged.connect(self.apply_filter)
        filter_box.addWidget(self.phase_filter)

        main_layout.addLayout(filter_box)

        # 2. Splitter with Operations Table (Left) and Detail Inspector (Right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Operations Table
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels([
            "Verknüpfung", "Operation", "Zulässige Phasen", "Parameter (Pflicht/Opt)", "Verknüpfte Mappings"
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        table_layout.addWidget(self.table)
        splitter.addWidget(table_container)

        # Right: Detail Inspector
        self.inspector = QGroupBox("Operations-Inspektor")
        self.inspector.setMinimumWidth(380)
        inspector_layout = QVBoxLayout(self.inspector)
        inspector_layout.setSpacing(10)

        self.insp_name_lbl = QLabel("Keine Operation ausgewählt")
        self.insp_name_lbl.setFont(QFont("sans-serif", 12, QFont.Weight.Bold))
        inspector_layout.addWidget(self.insp_name_lbl)

        self.insp_status_lbl = QLabel("")
        inspector_layout.addWidget(self.insp_status_lbl)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        inspector_layout.addWidget(sep1)

        inspector_layout.addWidget(QLabel("<b>Dokumentation / Zweck:</b>"))
        self.insp_doc_lbl = QLabel("-")
        self.insp_doc_lbl.setWordWrap(True)
        inspector_layout.addWidget(self.insp_doc_lbl)

        self.insp_phases_lbl = QLabel("-")
        inspector_layout.addWidget(self.insp_phases_lbl)

        # Parameters Table
        inspector_layout.addWidget(QLabel("<b>Erwartete Funktionsparameter:</b>"))
        self.params_table = QTableWidget(0, 3)
        self.params_table.setHorizontalHeaderLabels(["Parameter", "Typ / Einheit", "Pflicht?"])
        self.params_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.params_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.params_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        inspector_layout.addWidget(self.params_table)

        # Linked Mappings Section
        inspector_layout.addWidget(QLabel("<b>Verknüpfte Satzmuster (Mappings):</b>"))
        self.linked_mappings_lbl = QLabel("-")
        self.linked_mappings_lbl.setWordWrap(True)
        self.linked_mappings_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 8px; border-radius: 4px;")
        inspector_layout.addWidget(self.linked_mappings_lbl)

        inspector_layout.addStretch()

        # Action Button: Link New Mapping to this Operation
        self.btn_link_mapping = QPushButton("➕ Neues Satzmuster für diese Operation anlegen")
        self.btn_link_mapping.setStyleSheet("background-color: #198754; color: white; font-weight: bold; padding: 8px 14px; border-radius: 4px;")
        self.btn_link_mapping.clicked.connect(self.create_mapping_for_operation)
        inspector_layout.addWidget(self.btn_link_mapping)

        splitter.addWidget(self.inspector)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        main_layout.addWidget(splitter)

        self.update_inspector(None)

    def refresh(self):
        """Reload table content from state."""
        self.apply_filter()

    def apply_filter(self):
        search_query = self.search_edit.text().lower().strip()
        cov_filter = self.coverage_filter.currentIndex()
        phase_filter = self.phase_filter.currentIndex()

        self.table.setRowCount(0)
        self.filtered_op_names = []

        for op_name, op_info in sorted(self.state.operations.items()):
            # Text filter
            if search_query:
                combined = f"{op_name} {op_info.docstring}".lower()
                if search_query not in combined:
                    continue

            # Coverage filter
            if cov_filter == 1 and not op_info.is_mapped:
                continue
            if cov_filter == 2 and op_info.is_mapped:
                continue

            # Phase filter
            is_setup = any(p in ('PRECONDITION', 'ACTION', 'CLEANUP') for p in op_info.phases)
            is_check = 'EXPECTED' in op_info.phases
            if phase_filter == 1 and not is_setup:
                continue
            if phase_filter == 2 and not is_check:
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.filtered_op_names.append(op_name)

            # 0. Status
            status_item = QTableWidgetItem("✅ Mapped" if op_info.is_mapped else "⚠️ Lücke")
            status_item.setForeground(QColor("#198754" if op_info.is_mapped else "#d63384"))
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, status_item)

            # 1. Operation Name
            name_item = QTableWidgetItem(op_name)
            name_item.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
            self.table.setItem(row, 1, name_item)

            # 2. Phases
            phases_str = ", ".join(op_info.phases)
            self.table.setItem(row, 2, QTableWidgetItem(phases_str))

            # 3. Parameters count
            req_count = len(op_info.required_parameters)
            opt_count = len(op_info.optional_parameters)
            param_str = f"{req_count} Pflicht" + (f", {opt_count} opt" if opt_count else "")
            self.table.setItem(row, 3, QTableWidgetItem(param_str))

            # 4. Linked mappings summary
            if op_info.linked_mappings:
                map_titles = [f"[{m.id}] \"{m.template}\"" for m in op_info.linked_mappings]
                map_str = "; ".join(map_titles)
            else:
                map_str = "— Keine Verknüpfung vorhanden —"
            self.table.setItem(row, 4, QTableWidgetItem(map_str))

        if self.filtered_op_names:
            self.table.selectRow(0)
        else:
            self.update_inspector(None)

    def on_selection_changed(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            self.update_inspector(None)
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self.filtered_op_names):
            op_name = self.filtered_op_names[row]
            op_info = self.state.operations.get(op_name)
            self.current_selected_op_name = op_name
            self.update_inspector(op_info)
        else:
            self.update_inspector(None)

    def update_inspector(self, op_info: OperationInfo | None):
        has_op = op_info is not None
        self.btn_link_mapping.setEnabled(has_op)

        if not op_info:
            self.insp_name_lbl.setText("Keine Operation ausgewählt")
            self.insp_status_lbl.setText("")
            self.insp_doc_lbl.setText("-")
            self.insp_phases_lbl.setText("-")
            self.params_table.setRowCount(0)
            self.linked_mappings_lbl.setText("-")
            return

        self.insp_name_lbl.setText(f"<code>{op_info.name}</code>")
        if op_info.is_mapped:
            count = len(op_info.linked_mappings)
            self.insp_status_lbl.setText(f"✅ <b>{count} Satz-Mapping(s)</b> verknüpft")
            self.insp_status_lbl.setStyleSheet("color: #198754;")
        else:
            self.insp_status_lbl.setText("⚠️ <b>Nicht verknüpft!</b> Noch kein Satzmuster vorhanden.")
            self.insp_status_lbl.setStyleSheet("color: #dc3545;")

        self.insp_doc_lbl.setText(op_info.docstring or "<i>Keine Beschreibung vorhanden.</i>")
        self.insp_phases_lbl.setText(f"<b>Zulässige Phasen:</b> {', '.join(op_info.phases)}")

        # Populate parameters table
        self.params_table.setRowCount(len(op_info.parameters))
        for r, p in enumerate(op_info.parameters):
            p_name_item = QTableWidgetItem(p.name)
            p_name_item.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
            self.params_table.setItem(r, 0, p_name_item)

            # Type description
            t = p.type
            desc = type(t).__name__
            if hasattr(t, 'unit') and t.unit:
                desc += f" ({t.dimension}, [{t.minimum} .. {t.maximum}] {t.unit})"
            elif hasattr(t, 'kind'):
                desc += f" (Ressource: {t.kind})"
            elif hasattr(t, 'true_value'):
                desc += f" ('{t.true_value}' / '{t.false_value}')"
            self.params_table.setItem(r, 1, QTableWidgetItem(desc))

            req_item = QTableWidgetItem("Ja (Pflicht)" if p.required else f"Opt (Default: {p.default})")
            req_item.setForeground(QColor("#dc3545" if p.required else "#6c757d"))
            self.params_table.setItem(r, 2, req_item)

        # Populate linked mappings list
        if op_info.linked_mappings:
            lines = []
            for m in op_info.linked_mappings:
                params_str = ", ".join(f"{k}➔{v}" for k, v in m.parameters.items())
                status_icon = "✅" if m.is_valid else "⚠️"
                lines.append(f"• {status_icon} <b>{m.id}</b>: <code>\"{m.template}\"</code><br>&nbsp;&nbsp;&nbsp;<span style='color: #888;'>({params_str})</span>")
            self.linked_mappings_lbl.setText("<br>".join(lines))
        else:
            self.linked_mappings_lbl.setText(
                "<span style='color: #842029; background-color: #f8d7da; padding: 4px 8px; border-radius: 4px;'>"
                "Kein Satzmuster verknüpft. Klicke unten, um ein neues anzulegen."
                "</span>"
            )

    def create_mapping_for_operation(self):
        if not self.current_selected_op_name:
            return
        dialog = MappingEditorDialog(
            self.state.registry,
            preselected_operation=self.current_selected_op_name,
            parent=self,
        )
        if dialog.exec():
            new_item = dialog.get_result_item()
            self.state.add_mapping(new_item)
            self.on_change()
            self.refresh()
