"""Mappings-to-Operations view for SpecToTest GUI."""
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
    QMessageBox,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.dialog_editor import MappingEditorDialog
from tcg.gui.facade import CompilationFacade
from tcg.gui.models import MappingItem, MappingStudioState


class MappingsView(QWidget):
    """View showing all mappings and their links to operations."""

    test_sentence_requested = Signal(str)

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.current_selected_index: int | None = None
        self.cached_impacts = {}

        self.setup_ui()
        self.refresh()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 1. Search and Filter Bar
        filter_box = QHBoxLayout()
        filter_box.setSpacing(10)

        filter_box.addWidget(QLabel("Suche:"))
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Nach ID, Satzmuster oder Operation filtern...")
        self.search_edit.textChanged.connect(self.apply_filter)
        filter_box.addWidget(self.search_edit, stretch=2)

        filter_box.addWidget(QLabel("Phase:"))
        self.phase_filter = QComboBox()
        self.phase_filter.addItems(["Alle Phasen", "Nur SETUP (Action/Pre/Post)", "Nur CHECK (Expected)"])
        self.phase_filter.currentIndexChanged.connect(self.apply_filter)
        filter_box.addWidget(self.phase_filter)

        filter_box.addWidget(QLabel("Status:"))
        self.status_filter = QComboBox()
        self.status_filter.addItems(["Alle Status", "Nur Gültige", "Nur Konflikte & Fehler"])
        self.status_filter.currentIndexChanged.connect(self.apply_filter)
        filter_box.addWidget(self.status_filter)

        self.btn_new = QPushButton("Neues Mapping anlegen")
        self.btn_new.setStyleSheet("background-color: #2563eb; color: white; font-weight: bold; padding: 6px 14px; border-radius: 4px;")
        self.btn_new.clicked.connect(self.create_new_mapping)
        filter_box.addWidget(self.btn_new)

        main_layout.addLayout(filter_box)

        # 2. Splitter with Table (Left) and Detail Inspector (Right)
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: Mappings Table
        table_container = QWidget()
        table_layout = QVBoxLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "Status", "Mapping-ID", "Satz-Template", "Verknüpfte Operation", "Parameter-Zuordnungen", "Erlaubte Phasen"
        ])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)

        self.table.itemSelectionChanged.connect(self.on_selection_changed)
        self.table.itemDoubleClicked.connect(self.edit_selected_mapping)
        table_layout.addWidget(self.table)
        splitter.addWidget(table_container)

        # Right: Detail Inspector
        self.inspector = QGroupBox("Mapping-Inspektor")
        self.inspector.setMinimumWidth(320)
        inspector_layout = QVBoxLayout(self.inspector)
        inspector_layout.setSpacing(10)

        self.insp_id_lbl = QLabel("Kein Mapping ausgewählt")
        self.insp_id_lbl.setFont(QFont("", 12, QFont.Weight.Bold))
        inspector_layout.addWidget(self.insp_id_lbl)

        self.insp_status_lbl = QLabel("")
        self.insp_status_lbl.setWordWrap(True)
        inspector_layout.addWidget(self.insp_status_lbl)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        inspector_layout.addWidget(sep1)

        inspector_layout.addWidget(QLabel("<b>Satzmuster:</b>"))
        self.insp_template_lbl = QLabel("-")
        self.insp_template_lbl.setWordWrap(True)
        self.insp_template_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 8px; border-radius: 4px; font-family: monospace;")
        inspector_layout.addWidget(self.insp_template_lbl)

        inspector_layout.addWidget(QLabel("<b>Ziel-Operation:</b>"))
        self.insp_op_lbl = QLabel("-")
        self.insp_op_lbl.setStyleSheet("font-weight: bold; color: #2563eb;")
        inspector_layout.addWidget(self.insp_op_lbl)

        self.insp_phases_lbl = QLabel("-")
        inspector_layout.addWidget(self.insp_phases_lbl)

        inspector_layout.addWidget(QLabel("<b>Parameter-Bindings:</b>"))
        self.insp_bindings_lbl = QLabel("-")
        self.insp_bindings_lbl.setWordWrap(True)
        self.insp_bindings_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 8px; border-radius: 4px; font-family: monospace;")
        inspector_layout.addWidget(self.insp_bindings_lbl)

        # Impact Section
        inspector_layout.addWidget(QLabel("<b>Verwendung im Projekt:</b>"))
        self.insp_impact_lbl = QLabel("-")
        self.insp_impact_lbl.setWordWrap(True)
        self.insp_impact_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 8px; border-radius: 4px; font-size: 11px;")
        inspector_layout.addWidget(self.insp_impact_lbl)

        inspector_layout.addStretch()

        # Action Buttons
        btn_box = QVBoxLayout()
        btn_box.setSpacing(6)

        self.btn_edit = QPushButton("Mapping bearbeiten")
        self.btn_edit.clicked.connect(self.edit_selected_mapping)
        btn_box.addWidget(self.btn_edit)

        self.btn_test = QPushButton("Im Satzprüfer testen")
        self.btn_test.clicked.connect(self.send_to_tester)
        btn_box.addWidget(self.btn_test)

        self.btn_duplicate = QPushButton("Duplizieren")
        self.btn_duplicate.clicked.connect(self.duplicate_selected_mapping)
        btn_box.addWidget(self.btn_duplicate)

        self.btn_delete = QPushButton("Mapping löschen")
        self.btn_delete.setStyleSheet("color: #ef4444;")
        self.btn_delete.clicked.connect(self.delete_selected_mapping)
        btn_box.addWidget(self.btn_delete)

        inspector_layout.addLayout(btn_box)
        splitter.addWidget(self.inspector)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        main_layout.addWidget(splitter)

        self.update_inspector(None)

    def refresh(self):
        """Reload table content from state and recalculate impact."""
        self.calculate_impacts()
        self.apply_filter()

    def calculate_impacts(self):
        """Calculate usage impacts across the project specifications."""
        specs_files = CompilationFacade.list_spec_files(self.state.profile_config.specs_dir)
        mapping_dicts = [m.to_dict() for m in self.state.mappings if m.is_valid and not m.has_conflict]
        self.cached_impacts = CompilationFacade.analyze_impact(
            specs_files=specs_files,
            registry=self.state.registry,
            mapping_dicts=mapping_dicts,
            profile=self.state.profile,
        )

    def apply_filter(self):
        search_query = self.search_edit.text().lower().strip()
        phase_filter = self.phase_filter.currentIndex()
        status_filter = self.status_filter.currentIndex()

        self.table.setRowCount(0)
        self.filtered_indices = []

        for original_idx, item in enumerate(self.state.mappings):
            # Text filter
            if search_query:
                combined = f"{item.id} {item.template} {item.operation} {' '.join(item.parameters.keys())} {' '.join(item.parameters.values())}".lower()
                if search_query not in combined:
                    continue

            # Phase filter
            is_setup = any(p in ('PRECONDITION', 'ACTION', 'CLEANUP') for p in item.allowed_phases)
            is_check = 'EXPECTED' in item.allowed_phases
            if phase_filter == 1 and not is_setup:
                continue
            if phase_filter == 2 and not is_check:
                continue

            # Status filter
            if status_filter == 1 and not item.is_valid:
                continue
            if status_filter == 2 and item.is_valid:
                continue

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.filtered_indices.append(original_idx)

            # 0. Status
            if item.has_conflict:
                status_text = "Konflikt"
                status_color = QColor("#ef4444")
            elif item.is_valid:
                status_text = "Gültig"
                status_color = QColor("#10b981")
            else:
                status_text = "Fehler"
                status_color = QColor("#f59e0b")

            status_item = QTableWidgetItem(status_text)
            status_item.setForeground(status_color)
            status_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row, 0, status_item)

            # 1. ID
            id_item = QTableWidgetItem(item.id)
            id_item.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
            self.table.setItem(row, 1, id_item)

            # 2. Template
            tmpl_item = QTableWidgetItem(item.template)
            self.table.setItem(row, 2, tmpl_item)

            # 3. Operation
            op_item = QTableWidgetItem(item.operation)
            op_item.setForeground(QColor("#2563eb" if item.operation in self.state.registry else "#ef4444"))
            self.table.setItem(row, 3, op_item)

            # 4. Parameters
            param_str = ", ".join(f"{k} ➔ {v}" for k, v in item.parameters.items()) or "(keine)"
            self.table.setItem(row, 4, QTableWidgetItem(param_str))

            # 5. Phases
            phases_str = ", ".join(item.allowed_phases) or "-"
            self.table.setItem(row, 5, QTableWidgetItem(phases_str))

        if self.filtered_indices:
            self.table.selectRow(0)
        else:
            self.update_inspector(None)

    def on_selection_changed(self):
        selected_rows = self.table.selectionModel().selectedRows()
        if not selected_rows:
            self.update_inspector(None)
            return

        row = selected_rows[0].row()
        if 0 <= row < len(self.filtered_indices):
            original_idx = self.filtered_indices[row]
            item = self.state.mappings[original_idx]
            self.current_selected_index = original_idx
            self.update_inspector(item)
        else:
            self.update_inspector(None)

    def update_inspector(self, item: MappingItem | None):
        has_item = item is not None
        self.btn_edit.setEnabled(has_item)
        self.btn_test.setEnabled(has_item)
        self.btn_duplicate.setEnabled(has_item)
        self.btn_delete.setEnabled(has_item)

        if not item:
            self.insp_id_lbl.setText("Kein Mapping ausgewählt")
            self.insp_status_lbl.setText("")
            self.insp_template_lbl.setText("-")
            self.insp_op_lbl.setText("-")
            self.insp_phases_lbl.setText("-")
            self.insp_bindings_lbl.setText("-")
            self.insp_impact_lbl.setText("-")
            return

        self.insp_id_lbl.setText(item.id)
        if item.has_conflict:
            self.insp_status_lbl.setText(f"<b>Status:</b> Konflikt — {item.validation_error}")
            self.insp_status_lbl.setStyleSheet("color: #ef4444;")
        elif item.is_valid:
            self.insp_status_lbl.setText("<b>Status:</b> Gültig und einsatzbereit")
            self.insp_status_lbl.setStyleSheet("color: #10b981;")
        else:
            self.insp_status_lbl.setText(f"<b>Status:</b> Fehler — {item.validation_error or 'Ungültig'}")
            self.insp_status_lbl.setStyleSheet("color: #f59e0b;")

        self.insp_template_lbl.setText(item.template)
        self.insp_op_lbl.setText(item.operation)
        self.insp_phases_lbl.setText(f"<b>Erlaubte Phasen:</b> {', '.join(item.allowed_phases) or 'Keine'}")

        bindings_lines = [f"• {{{k}}} ➔ <b>{v}</b>" for k, v in item.parameters.items()]
        self.insp_bindings_lbl.setText("<br>".join(bindings_lines) if bindings_lines else "<i>Keine Parameter (statischer Befehl)</i>")

        # Impact display
        impact = self.cached_impacts.get(item.id)
        if impact and impact.total_usages > 0:
            cases_str = ", ".join(sorted(impact.affected_cases)[:3])
            more_cases = f" und {len(impact.affected_cases) - 3} weitere" if len(impact.affected_cases) > 3 else ""
            files_count = len(impact.affected_files)
            self.insp_impact_lbl.setText(
                f"Dieses Satzmuster wird in <b>{impact.total_usages} Schritten</b> aus "
                f"<b>{len(impact.affected_cases)} Testfällen</b> ({files_count} Datei(en)) verwendet.<br>"
                f"<span style='color: #64748b;'>Testfälle: {cases_str}{more_cases}</span>"
            )
        else:
            self.insp_impact_lbl.setText("Wird in den aktuellen Spezifikationen noch nicht verwendet (0 Verwendungen).")

    def create_new_mapping(self):
        dialog = MappingEditorDialog(self.state.registry, parent=self)
        if dialog.exec():
            new_item = dialog.get_result_item()
            self.state.add_mapping(new_item)
            self.on_change()
            self.refresh()
            self.search_edit.setText(new_item.id)

    def edit_selected_mapping(self):
        if self.current_selected_index is None or not (0 <= self.current_selected_index < len(self.state.mappings)):
            return
        item = self.state.mappings[self.current_selected_index]
        dialog = MappingEditorDialog(self.state.registry, existing_item=item, parent=self)
        if dialog.exec():
            updated_item = dialog.get_result_item()
            self.state.update_mapping(self.current_selected_index, updated_item)
            self.on_change()
            self.refresh()

    def duplicate_selected_mapping(self):
        if self.current_selected_index is None or not (0 <= self.current_selected_index < len(self.state.mappings)):
            return
        item = self.state.mappings[self.current_selected_index]
        dup = MappingItem(
            id=f"{item.id}_COPY",
            template=item.template,
            operation=item.operation,
            parameters=dict(item.parameters),
        )
        self.state.add_mapping(dup)
        self.on_change()
        self.refresh()
        self.search_edit.setText(dup.id)

    def delete_selected_mapping(self):
        if self.current_selected_index is None or not (0 <= self.current_selected_index < len(self.state.mappings)):
            return
        item = self.state.mappings[self.current_selected_index]
        impact = self.cached_impacts.get(item.id)
        impact_warning = ""
        if impact and impact.total_usages > 0:
            impact_warning = f"\n\nACHTUNG: Dieses Mapping wird in {impact.total_usages} Schritten aus {len(impact.affected_cases)} Testfällen verwendet!"

        confirm = QMessageBox.question(
            self,
            "Mapping löschen",
            f"Möchtest du das Mapping '{item.id}' wirklich entfernen?{impact_warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm == QMessageBox.StandardButton.Yes:
            self.state.remove_mapping(self.current_selected_index)
            self.on_change()
            self.refresh()

    def send_to_tester(self):
        if self.current_selected_index is None or not (0 <= self.current_selected_index < len(self.state.mappings)):
            return
        item = self.state.mappings[self.current_selected_index]
        sample = item.template
        for ph in item.placeholders:
            sample = sample.replace(f"{{{ph}}}", "10")
        self.test_sentence_requested.emit(sample)
