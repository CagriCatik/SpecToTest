"""Specification Workspace with background analysis, multi-tier problem tracking, and integrated Step Assistant."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from PySide6.QtCore import QRegularExpression, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QPalette, QSyntaxHighlighter, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QCompleter,
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

from tcg.gui.analysis_worker import BackgroundAnalysisManager, InspectionProblem
from tcg.gui.facade import CompilationError, CompilationFacade, CompilationResult, StepInspectionInfo
from tcg.gui.models import MappingStudioState
from tcg.gui.syntax import SpecSyntaxHighlighter
from tcg.gui.widget_smart_param import SmartParamWidget, build_smart_param_widget


def detect_phase_at_cursor(editor: QTextEdit) -> str:
    """Detect current test specification phase based on the nearest preceding section header."""
    cursor = editor.textCursor()
    block = cursor.block()
    while block.isValid():
        text = block.text().strip()
        text_lower = text.lower()
        if re.search(r'precondition|vorbedingung', text_lower):
            return "PRECONDITION"
        if re.search(r'expected\s*result|erwartetes\s*ergebnis|ergebnis', text_lower):
            return "EXPECTED"
        if re.search(r'postcondition|nachbedingung', text_lower):
            return "POSTCONDITION"
        if re.search(r'cleanup|aufräumen', text_lower):
            return "CLEANUP"
        if re.search(r'action|aktion', text_lower):
            return "ACTION"
        block = block.previous()
    return "ACTION"


class SpecCodeEditor(QTextEdit):
    """QTextEdit with custom autocompletion support for test sentence templates."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.completer: QCompleter | None = None

    def set_completer(self, completer: QCompleter):
        if self.completer:
            self.completer.activated.disconnect()
        self.completer = completer
        if not self.completer:
            return
        self.completer.setWidget(self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.PopupCompletion)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.activated.connect(self.insert_completion)

    def insert_completion(self, completion: str):
        tc = self.textCursor()
        prefix_len = len(self.completer.completionPrefix())
        tc.movePosition(QTextCursor.MoveOperation.Left, QTextCursor.MoveMode.KeepAnchor, prefix_len)
        tc.insertText(completion)
        self.setTextCursor(tc)

    def text_under_cursor(self) -> str:
        tc = self.textCursor()
        tc.select(QTextCursor.SelectionType.WordUnderCursor)
        return tc.selectedText()

    def keyPressEvent(self, event):
        if self.completer and self.completer.popup() and self.completer.popup().isVisible():
            if event.key() in (Qt.Key.Key_Enter, Qt.Key.Key_Return, Qt.Key.Key_Escape, Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                event.ignore()
                return

        is_shortcut = (event.modifiers() == Qt.KeyboardModifier.ControlModifier and event.key() == Qt.Key.Key_Space)
        super().keyPressEvent(event)

        if not self.completer:
            return

        ctrl_or_shift = event.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
        if ctrl_or_shift and not is_shortcut:
            return

        prefix = self.text_under_cursor()
        if not is_shortcut and (len(prefix) < 2 or event.text().strip() == ''):
            self.completer.popup().hide()
            return

        if prefix != self.completer.completionPrefix():
            self.completer.setCompletionPrefix(prefix)
            self.completer.popup().setCurrentIndex(self.completer.completionModel().index(0, 0))

        cr = self.cursorRect()
        cr.setWidth(self.completer.popup().sizeHintForColumn(0) + self.completer.popup().verticalScrollBar().sizeHint().width() + 20)
        self.completer.complete(cr)


class StepAssistantWidget(QWidget):
    """Context-aware step assistant offering valid operations for current phase, smart forms, and insertion."""

    insert_requested = Signal(str)

    def __init__(self, state: MappingStudioState, parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.current_phase = "ACTION"
        self.param_widgets: dict[str, SmartParamWidget] = {}
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 1. Phase Context Banner
        self.lbl_phase_badge = QLabel("Phase: ACTION (Setup)")
        self.lbl_phase_badge.setStyleSheet(
            "background-color: rgba(59, 130, 246, 0.15); color: #60a5fa; padding: 6px; border-radius: 4px; font-weight: bold;"
        )
        layout.addWidget(self.lbl_phase_badge)

        # 2. Operation Selection (filtered by phase)
        layout.addWidget(QLabel("<b>Erlaubte Operation wählen:</b>"))
        self.combo_ops = QComboBox()
        self.combo_ops.currentIndexChanged.connect(self.on_operation_changed)
        layout.addWidget(self.combo_ops)

        # 3. Sentence Template Selection
        layout.addWidget(QLabel("<b>Satzmuster wählen:</b>"))
        self.combo_tmpl = QComboBox()
        self.combo_tmpl.currentIndexChanged.connect(self.on_template_changed)
        layout.addWidget(self.combo_tmpl)

        # 4. Dynamic Parameter Form
        self.form_group = QGroupBox("Parameter eingeben")
        self.form_layout = QVBoxLayout(self.form_group)
        self.form_layout.setSpacing(6)
        layout.addWidget(self.form_group)

        # 5. Live Sentence Preview & Auto-Verification
        layout.addWidget(QLabel("<b>Erzeugter Satz:</b>"))
        self.txt_preview = QLineEdit()
        self.txt_preview.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
        self.txt_preview.textChanged.connect(self.verify_preview_sentence)
        layout.addWidget(self.txt_preview)

        self.lbl_verify = QLabel("-")
        self.lbl_verify.setWordWrap(True)
        layout.addWidget(self.lbl_verify)

        # 6. Action Button
        self.btn_insert = QPushButton("Schritt in Spezifikation einfügen")
        self.btn_insert.setStyleSheet(
            "background-color: #16a34a; color: white; font-weight: bold; padding: 8px 14px; border-radius: 4px;"
        )
        self.btn_insert.clicked.connect(self.on_insert_clicked)
        layout.addWidget(self.btn_insert)

        layout.addStretch()

    def set_phase(self, phase: str):
        if phase == self.current_phase and self.combo_ops.count() > 0:
            return
        self.current_phase = phase
        is_check = phase in ("EXPECTED_RESULT", "EXPECTED", "CHECK")
        phase_label = "EXPECTED RESULT (Prüfung)" if is_check else f"{phase} (Setup)"
        color = "#34d399" if is_check else "#60a5fa"
        self.lbl_phase_badge.setText(f"Erkannte Phase am Cursor: <b>{phase_label}</b>")
        self.lbl_phase_badge.setStyleSheet(
            f"background-color: rgba(59, 130, 246, 0.15); color: {color}; padding: 6px; border-radius: 4px;"
        )

        prev_op = self.combo_ops.currentData()
        self.combo_ops.blockSignals(True)
        self.combo_ops.clear()

        for op_name, op_info in sorted(self.state.operations.items()):
            contract = self.state.registry.get(op_name)
            if not contract:
                continue
            contract_phases = set(contract.phases)
            if is_check:
                match = bool(contract_phases & {"EXPECTED_RESULT", "EXPECTED", "CHECK"})
            else:
                match = bool(contract_phases & {phase, "SETUP", "ACTION", "PRECONDITION", "POSTCONDITION", "CLEANUP"})

            if match and op_info.is_mapped:
                self.combo_ops.addItem(f"{op_name} ({len(op_info.linked_mappings)} Muster)", op_name)

        self.combo_ops.blockSignals(False)

        idx = self.combo_ops.findData(prev_op)
        if idx >= 0:
            self.combo_ops.setCurrentIndex(idx)
        elif self.combo_ops.count() > 0:
            self.combo_ops.setCurrentIndex(0)
        else:
            self.combo_tmpl.clear()
            self.txt_preview.clear()
            self.lbl_verify.setText("Keine passenden Operationen für diese Phase verfügbar.")

        self.on_operation_changed()

    def on_operation_changed(self):
        op_name = self.combo_ops.currentData()
        self.combo_tmpl.blockSignals(True)
        self.combo_tmpl.clear()

        if not op_name:
            self.combo_tmpl.blockSignals(False)
            self.build_parameter_form(None)
            return

        op_info = self.state.operations.get(op_name)
        if op_info and op_info.linked_mappings:
            for m in op_info.linked_mappings:
                if m.is_valid and not m.has_conflict:
                    self.combo_tmpl.addItem(m.template, m)

        self.combo_tmpl.blockSignals(False)
        if self.combo_tmpl.count() > 0:
            self.combo_tmpl.setCurrentIndex(0)
        self.on_template_changed()

    def on_template_changed(self):
        mapping = self.combo_tmpl.currentData()
        self.build_parameter_form(mapping)

    def build_parameter_form(self, mapping):
        while self.form_layout.count():
            item = self.form_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.param_widgets.clear()

        if not mapping:
            self.txt_preview.clear()
            self.lbl_verify.clear()
            self.btn_insert.setEnabled(False)
            return

        contract = self.state.registry.get(mapping.operation)
        placeholders = mapping.placeholders

        if not placeholders:
            info = QLabel("Dieses Satzmuster benötigt keine Parameter.")
            info.setStyleSheet("color: #64748b; font-style: italic;")
            self.form_layout.addWidget(info)
            self.txt_preview.setText(mapping.template)
            self.btn_insert.setEnabled(True)
            self.verify_preview_sentence()
            return

        resources = self.state.profile.resources if self.state.profile else {}
        for ph in placeholders:
            target_name = mapping.parameters.get(ph)
            param_spec = contract.parameter(target_name) if contract and target_name else None

            row_widget = QWidget()
            row_layout = QHBoxLayout(row_widget)
            row_layout.setContentsMargins(0, 1, 0, 1)
            row_layout.setSpacing(6)

            lbl = QLabel(f"{{{ph}}}:")
            lbl.setFont(QFont("Monospace", 9, QFont.Weight.Bold))
            lbl.setMinimumWidth(80)
            row_layout.addWidget(lbl)

            smart_widget = build_smart_param_widget(
                param_spec=param_spec,
                ph_name=ph,
                profile_resources=resources,
                on_change=self.update_preview_from_inputs,
            )
            row_layout.addWidget(smart_widget, stretch=2)
            self.form_layout.addWidget(row_widget)
            self.param_widgets[ph] = smart_widget

        self.btn_insert.setEnabled(True)
        self.update_preview_from_inputs()

    def update_preview_from_inputs(self):
        mapping = self.combo_tmpl.currentData()
        if not mapping:
            return
        tmpl = mapping.template
        for ph, widget in self.param_widgets.items():
            val = widget.get_value_string()
            unit = widget.get_unit_string()
            if unit:
                val = f"{val} {unit}" if unit in ('s', 'ms', 'rpm', 'km/h', 'Ohm') else f"{val}{unit}"
            tmpl = tmpl.replace(f"{{{ph}}}", str(val))

        self.txt_preview.setText(tmpl)

    def verify_preview_sentence(self):
        sentence = self.txt_preview.text().strip()
        if not sentence:
            self.lbl_verify.setText("-")
            return

        res = self.state.test_sentence(sentence, phase=self.current_phase)
        if res['success'] and res['matched']:
            op = res['operation']
            args = ", ".join(f"{k}={v!r}" for k, v in res['arguments'].items())
            self.lbl_verify.setText(
                f"<span style='color: #10b981; font-weight: bold;'>Gültig:</span> <code>{op}({args})</code>"
            )
        else:
            err = res.get('error') or res.get('phase_msg') or 'Nicht auflösbar'
            self.lbl_verify.setText(f"<span style='color: #ef4444;'>Hinweis:</span> {err}")

    def on_insert_clicked(self):
        sentence = self.txt_preview.text().strip()
        if sentence:
            self.insert_requested.emit(sentence)


class SpecificationWorkspace(QWidget):
    """Workspace for browsing, editing, and inspecting specifications and generated code."""

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.current_spec_path: Path | None = None
        self.all_spec_files: list[Path] = []
        self.last_compilation_result: CompilationResult | None = None
        self.is_spec_dirty: bool = False
        self.is_loading_file: bool = False
        self.target_jump_line: int | None = None
        self.all_problems: list[InspectionProblem] = []
        self.current_problem_filter: str = "ALL"

        # Background analysis manager
        self.analysis_manager = BackgroundAnalysisManager(self)
        self.analysis_manager.sig_doc_analysis_started.connect(self.on_doc_analysis_started)
        self.analysis_manager.sig_doc_analysis_finished.connect(self.on_doc_analysis_finished)
        self.analysis_manager.sig_doc_analysis_failed.connect(self.on_doc_analysis_failed)
        self.analysis_manager.sig_project_analysis_finished.connect(self.on_project_analysis_finished)

        self.setup_ui()
        self.setup_autocompletion()
        self.refresh_spec_list()

    def setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        # 3-way Splitter: File Explorer (Left) | Editor (Center) | Translation Inspector & Code (Right)
        main_splitter = QSplitter(Qt.Orientation.Horizontal)

        # --- LEFT: Spec File Explorer ---
        file_panel = QWidget()
        file_layout = QVBoxLayout(file_panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(8)

        file_header = QLabel("<b>Spezifikationsdateien</b>")
        file_layout.addWidget(file_header)

        self.file_search = QLineEdit()
        self.file_search.setPlaceholderText("Filter...")
        self.file_search.textChanged.connect(self.filter_file_list)
        file_layout.addWidget(self.file_search)

        self.file_list = QListWidget()
        self.file_list.itemSelectionChanged.connect(self.on_file_selected)
        file_layout.addWidget(self.file_list)

        btn_refresh_files = QPushButton("Dateiliste aktualisieren")
        btn_refresh_files.clicked.connect(self.refresh_spec_list)
        file_layout.addWidget(btn_refresh_files)

        main_splitter.addWidget(file_panel)

        # --- CENTER: Editor & Problem Panel ---
        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)

        editor_top = QHBoxLayout()
        self.lbl_current_file = QLabel("Keine Datei geöffnet")
        self.lbl_current_file.setFont(QFont("", 10, QFont.Weight.Bold))
        editor_top.addWidget(self.lbl_current_file, stretch=2)

        # Status badge for background analysis
        self.lbl_analysis_status = QLabel("Bereit")
        self.lbl_analysis_status.setFont(QFont("", 9, QFont.Weight.Bold))
        editor_top.addWidget(self.lbl_analysis_status)

        self.btn_save_spec = QPushButton("Spezifikation speichern")
        self.btn_save_spec.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
        self.btn_save_spec.clicked.connect(self.save_current_spec)
        self.btn_save_spec.setEnabled(False)
        editor_top.addWidget(self.btn_save_spec)

        self.btn_recompile = QPushButton("Neu übersetzen")
        self.btn_recompile.clicked.connect(lambda: self.compile_current_text(sync=True))
        self.btn_recompile.setEnabled(False)
        editor_top.addWidget(self.btn_recompile)

        editor_layout.addLayout(editor_top)

        # Vertical Splitter: Editor above, Multi-Tier Problem Table below
        edit_splitter = QSplitter(Qt.Orientation.Vertical)

        self.editor = SpecCodeEditor()
        self.editor.setFont(QFont("Monospace", 10))
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.highlighter = SpecSyntaxHighlighter(self.editor.document(), dark_theme=True)
        self.editor.cursorPositionChanged.connect(self.on_cursor_position_changed)
        self.editor.textChanged.connect(self.on_editor_text_changed)
        edit_splitter.addWidget(self.editor)

        # Multi-Tier Problem List Panel
        problem_group = QGroupBox("Gemeinsame Problemliste (Schritt • Dokument • Projekt)")
        prob_layout = QVBoxLayout(problem_group)
        prob_layout.setContentsMargins(4, 8, 4, 4)
        prob_layout.setSpacing(6)

        filter_row = QHBoxLayout()
        self.btn_filter_all = QPushButton("Alle (0)")
        self.btn_filter_all.setCheckable(True)
        self.btn_filter_all.setChecked(True)
        self.btn_filter_all.clicked.connect(lambda: self.set_problem_filter("ALL"))
        filter_row.addWidget(self.btn_filter_all)

        self.btn_filter_step = QPushButton("Schritt (0)")
        self.btn_filter_step.setCheckable(True)
        self.btn_filter_step.clicked.connect(lambda: self.set_problem_filter("Schritt"))
        filter_row.addWidget(self.btn_filter_step)

        self.btn_filter_doc = QPushButton("Dokument (0)")
        self.btn_filter_doc.setCheckable(True)
        self.btn_filter_doc.clicked.connect(lambda: self.set_problem_filter("Dokument"))
        filter_row.addWidget(self.btn_filter_doc)

        self.btn_filter_proj = QPushButton("Projekt (0)")
        self.btn_filter_proj.setCheckable(True)
        self.btn_filter_proj.clicked.connect(lambda: self.set_problem_filter("Projekt"))
        filter_row.addWidget(self.btn_filter_proj)

        self.filter_btn_group = QButtonGroup(self)
        self.filter_btn_group.addButton(self.btn_filter_all)
        self.filter_btn_group.addButton(self.btn_filter_step)
        self.filter_btn_group.addButton(self.btn_filter_doc)
        self.filter_btn_group.addButton(self.btn_filter_proj)

        filter_row.addStretch()
        prob_layout.addLayout(filter_row)

        self.error_table = QTableWidget(0, 5)
        self.error_table.setHorizontalHeaderLabels(["Ebene", "Typ", "Datei", "Zeile", "Meldung / Ursache"])
        self.error_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.error_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.error_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        self.error_table.itemDoubleClicked.connect(self.on_problem_double_clicked)
        prob_layout.addWidget(self.error_table)

        edit_splitter.addWidget(problem_group)
        edit_splitter.setStretchFactor(0, 4)
        edit_splitter.setStretchFactor(1, 1)

        editor_layout.addWidget(edit_splitter)
        main_splitter.addWidget(editor_panel)

        # --- RIGHT: Translation Inspector, Step Assistant & Code Preview ---
        right_panel = QTabWidget()

        # Tab 1: Schritt-Inspektor
        step_tab = QWidget()
        step_layout = QVBoxLayout(step_tab)
        step_layout.setContentsMargins(10, 10, 10, 10)
        step_layout.setSpacing(10)

        self.insp_line_lbl = QLabel("Wähle eine Zeile im Editor aus")
        self.insp_line_lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        step_layout.addWidget(self.insp_line_lbl)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        step_layout.addWidget(sep1)

        step_layout.addWidget(QLabel("<b>Zugeordnetes Satzmuster:</b>"))
        self.insp_map_lbl = QLabel("-")
        self.insp_map_lbl.setWordWrap(True)
        self.insp_map_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 6px; border-radius: 4px; font-family: monospace;")
        step_layout.addWidget(self.insp_map_lbl)

        step_layout.addWidget(QLabel("<b>Aufgerufene Operation:</b>"))
        self.insp_op_lbl = QLabel("-")
        self.insp_op_lbl.setStyleSheet("font-weight: bold; color: #2563eb;")
        step_layout.addWidget(self.insp_op_lbl)

        self.insp_op_doc = QLabel("-")
        self.insp_op_doc.setWordWrap(True)
        self.insp_op_doc.setStyleSheet("color: #94a3b8; font-size: 11px;")
        step_layout.addWidget(self.insp_op_doc)

        step_layout.addWidget(QLabel("<b>Extrahierte & normalisierte Parameter:</b>"))
        self.insp_params_lbl = QLabel("-")
        self.insp_params_lbl.setWordWrap(True)
        self.insp_params_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 6px; border-radius: 4px; font-family: monospace;")
        step_layout.addWidget(self.insp_params_lbl)

        # Action <-> Expectation Link
        step_layout.addWidget(QLabel("<b>Verknüpfte Aktion / Erwartung:</b>"))
        self.insp_linked_step_lbl = QLabel("Keine Verknüpfung")
        self.insp_linked_step_lbl.setWordWrap(True)
        self.insp_linked_step_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 6px; border-radius: 4px; font-size: 11px;")
        step_layout.addWidget(self.insp_linked_step_lbl)

        self.btn_jump_linked = QPushButton("Zur verknüpften Zeile springen")
        self.btn_jump_linked.clicked.connect(self.jump_to_linked_line)
        self.btn_jump_linked.setEnabled(False)
        step_layout.addWidget(self.btn_jump_linked)

        step_layout.addWidget(QLabel("<b>Erzeugter Python-Aufruf:</b>"))
        self.insp_call_code = QTextEdit()
        self.insp_call_code.setReadOnly(True)
        self.insp_call_code.setFont(QFont("Monospace", 9))
        self.insp_call_code.setMaximumHeight(80)
        step_layout.addWidget(self.insp_call_code)

        step_layout.addStretch()
        right_panel.addTab(step_tab, "Schritt-Inspektor")

        # Tab 2: Schritt einfügen (Integrated Step Assistant)
        self.step_assistant = StepAssistantWidget(self.state, parent=self)
        self.step_assistant.insert_requested.connect(self.insert_statement_at_cursor)
        right_panel.addTab(self.step_assistant, "Schritt einfügen")

        # Tab 3: Python-Vorschau
        code_tab = QWidget()
        code_layout = QVBoxLayout(code_tab)
        code_layout.setContentsMargins(10, 10, 10, 10)
        code_layout.setSpacing(8)

        code_header = QLabel("<b>Generierte Python-Testdatei</b> (render_python)")
        code_layout.addWidget(code_header)

        self.code_view = QTextEdit()
        self.code_view.setReadOnly(True)
        self.code_view.setFont(QFont("Monospace", 9))
        self.code_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        code_layout.addWidget(self.code_view)

        right_panel.addTab(code_tab, "Python-Vorschau")

        main_splitter.addWidget(right_panel)

        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setStretchFactor(2, 2)

        main_layout.addWidget(main_splitter)

        # Debounce timer for asynchronous background re-compilation
        self.compile_timer = QTimer(self)
        self.compile_timer.setSingleShot(True)
        self.compile_timer.setInterval(400)
        self.compile_timer.timeout.connect(self.trigger_background_doc_analysis)

    def setup_autocompletion(self):
        templates = [m.template for m in self.state.mappings if m.is_valid and not m.has_conflict]
        completer = QCompleter(templates, self)
        self.editor.set_completer(completer)

    def refresh_spec_list(self):
        if not self.prompt_save_spec_if_dirty():
            return

        specs_dir = self.state.profile_config.specs_dir
        self.all_spec_files = CompilationFacade.list_spec_files(specs_dir)
        self.filter_file_list()
        self.trigger_background_project_analysis()

    def filter_file_list(self):
        query = self.file_search.text().lower().strip()
        self.file_list.clear()

        for f in self.all_spec_files:
            if query and query not in f.name.lower():
                continue
            item = QListWidgetItem(f.name)
            item.setData(Qt.ItemDataRole.UserRole, str(f))
            self.file_list.addItem(item)

        if self.file_list.count() > 0 and not self.current_spec_path:
            self.file_list.setCurrentRow(0)

    def prompt_save_spec_if_dirty(self) -> bool:
        if not self.is_spec_dirty or not self.current_spec_path:
            return True

        reply = QMessageBox.question(
            self,
            "Ungespeicherte Spezifikationsänderungen",
            f"Die Datei '{self.current_spec_path.name}' hat ungespeicherte Änderungen.\n"
            f"Möchtest du die Änderungen speichern?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )

        if reply == QMessageBox.StandardButton.Save:
            return self.save_current_spec()
        elif reply == QMessageBox.StandardButton.Discard:
            self.is_spec_dirty = False
            return True
        else:
            return False

    def on_file_selected(self):
        items = self.file_list.selectedItems()
        if not items:
            return
        path_str = items[0].data(Qt.ItemDataRole.UserRole)
        p = Path(path_str)

        if self.current_spec_path and p == self.current_spec_path:
            return

        if not self.prompt_save_spec_if_dirty():
            for i in range(self.file_list.count()):
                it = self.file_list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == str(self.current_spec_path):
                    self.file_list.blockSignals(True)
                    self.file_list.setCurrentItem(it)
                    self.file_list.blockSignals(False)
                    break
            return

        self.load_spec_file(p)

    def load_spec_file(self, path: Path):
        self.current_spec_path = path
        try:
            text = path.read_text(encoding='utf-8-sig')
            self.is_loading_file = True
            self.editor.setPlainText(text)
            self.editor.document().setModified(False)
            self.is_loading_file = False
            self.is_spec_dirty = False

            self.lbl_current_file.setText(f"{path.name} ({path.parent.name})")
            self.btn_save_spec.setEnabled(True)
            self.btn_recompile.setEnabled(True)
            self.compile_current_text(sync=True)
        except Exception as e:
            self.is_loading_file = False
            QMessageBox.critical(self, "Fehler beim Laden", f"Konnte Datei '{path.name}' nicht öffnen: {e}")

    def on_editor_text_changed(self):
        if self.is_loading_file:
            return
        if not self.editor.document().isModified():
            return
        self.is_spec_dirty = True
        if self.current_spec_path:
            self.lbl_current_file.setText(f"{self.current_spec_path.name} (ungespeichert)")
        self.compile_timer.start()

    def trigger_background_doc_analysis(self):
        """Debounced background compilation task."""
        if not self.current_spec_path:
            return
        text = self.editor.toPlainText()
        name = self.current_spec_path.name
        mapping_dicts = self.state.get_mappings_dicts()

        self.analysis_manager.schedule_doc_analysis(
            text=text,
            source_name=name,
            registry=self.state.registry,
            mapping_dicts=mapping_dicts,
            profile=self.state.profile,
        )

    def trigger_background_project_analysis(self):
        """Asynchronous project-wide impact and consistency check."""
        if not self.all_spec_files:
            return
        mapping_dicts = self.state.get_mappings_dicts()
        self.analysis_manager.schedule_project_analysis(
            specs_files=self.all_spec_files,
            registry=self.state.registry,
            mapping_dicts=mapping_dicts,
            profile=self.state.profile,
        )

    def compile_current_text(self, sync: bool = True):
        """Compile editor content in-memory.
        
        If sync=True, compiles synchronously (for tests/immediate button clicks).
        Otherwise triggers background analysis.
        """
        if not self.current_spec_path:
            return

        text = self.editor.toPlainText()
        name = self.current_spec_path.name
        mapping_dicts = self.state.get_mappings_dicts()

        if sync:
            result = CompilationFacade.compile_text(
                text=text,
                source_name=name,
                registry=self.state.registry,
                mapping_dicts=mapping_dicts,
                profile=self.state.profile,
                strict_project_check=True,
            )
            self.apply_doc_result(result, self.analysis_manager.current_doc_revision)
        else:
            self.trigger_background_doc_analysis()

    def on_doc_analysis_started(self, revision: int):
        self.lbl_analysis_status.setText(f"<span style='color: #3b82f6;'>● Prüfung läuft (Rev. {revision})...</span>")

    def on_doc_analysis_finished(self, result: CompilationResult, revision: int):
        if revision != self.analysis_manager.current_doc_revision:
            self.lbl_analysis_status.setText("<span style='color: #94a3b8;'>Ergebnis veraltet</span>")
            return
        self.apply_doc_result(result, revision)

    def on_doc_analysis_failed(self, error_msg: str, revision: int):
        if revision != self.analysis_manager.current_doc_revision:
            return
        self.lbl_analysis_status.setText("<span style='color: #ef4444;'>⚠ Analysefehler</span>")

    def apply_doc_result(self, result: CompilationResult, revision: int):
        self.last_compilation_result = result
        if result.success:
            self.lbl_analysis_status.setText(f"<span style='color: #10b981;'>✔ Aktuell geprüft (Rev. {revision})</span>")
            self.code_view.setPlainText(result.python_code)
        else:
            self.lbl_analysis_status.setText(f"<span style='color: #ef4444;'>⚠ Fehler erfasst (Rev. {revision})</span>")
            self.code_view.setPlainText(f"# FEHLERHAFTE ÜBERSETZUNG:\n# {result.summary}\n\n{result.python_code}")

        self.rebuild_problem_list()
        self.on_cursor_position_changed()

    def on_project_analysis_finished(self, impacts: Any, problems: list[InspectionProblem], revision: int):
        if revision != self.analysis_manager.current_project_revision:
            return
        self.all_problems = [p for p in self.all_problems if p.level != "Projekt"] + problems
        self.update_problem_table()

    def rebuild_problem_list(self):
        """Consolidate problems across the 3 tiers (Schritt, Dokument, Projekt)."""
        curr_file = self.current_spec_path.name if self.current_spec_path else "Unbekannt"
        problems: list[InspectionProblem] = []

        # 1. Tier 2: Dokument
        if self.last_compilation_result and not self.last_compilation_result.success:
            for err in self.last_compilation_result.errors:
                problems.append(
                    InspectionProblem(
                        level="Dokument",
                        severity="Fehler",
                        file_name=curr_file,
                        file_path=self.current_spec_path,
                        line=err.line,
                        message=err.message,
                        details=self.last_compilation_result.summary,
                    )
                )

        # 2. Tier 1: Schritt (Current cursor step evaluation)
        cursor_line = self.editor.textCursor().blockNumber() + 1
        if self.last_compilation_result and self.last_compilation_result.steps_by_line:
            step_info = self.last_compilation_result.steps_by_line.get(cursor_line)
            if step_info:
                # Step is mapped and valid
                pass
        else:
            line_txt = self.editor.textCursor().block().text().strip()
            if line_txt and re.match(r'^[0-9]+[.:]', line_txt):
                test_res = self.state.test_sentence(line_txt)
                if not test_res['matched']:
                    problems.append(
                        InspectionProblem(
                            level="Schritt",
                            severity="Warnung",
                            file_name=curr_file,
                            file_path=self.current_spec_path,
                            line=cursor_line,
                            message="Satzmuster im aktuellen Kontext nicht erkannt",
                            details=test_res.get('error', ''),
                        )
                    )

        # Keep existing project problems
        proj_problems = [p for p in self.all_problems if p.level == "Projekt"]
        self.all_problems = problems + proj_problems
        self.update_problem_table()

    def set_problem_filter(self, filter_level: str):
        self.current_problem_filter = filter_level
        self.update_problem_table()

    def update_problem_table(self):
        # Update badge counts
        n_all = len(self.all_problems)
        n_step = sum(1 for p in self.all_problems if p.level == "Schritt")
        n_doc = sum(1 for p in self.all_problems if p.level == "Dokument")
        n_proj = sum(1 for p in self.all_problems if p.level == "Projekt")

        self.btn_filter_all.setText(f"Alle ({n_all})")
        self.btn_filter_step.setText(f"Schritt ({n_step})")
        self.btn_filter_doc.setText(f"Dokument ({n_doc})")
        self.btn_filter_proj.setText(f"Projekt ({n_proj})")

        # Filter items
        filtered = self.all_problems
        if self.current_problem_filter != "ALL":
            filtered = [p for p in self.all_problems if p.level == self.current_problem_filter]

        self.error_table.setRowCount(len(filtered))
        for row, prob in enumerate(filtered):
            # 0. Ebene
            ebene_item = QTableWidgetItem(prob.level)
            ebene_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.error_table.setItem(row, 0, ebene_item)

            # 1. Typ
            typ_item = QTableWidgetItem(prob.severity)
            typ_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            if prob.severity == "Fehler":
                typ_item.setForeground(QColor("#ef4444"))
            elif prob.severity == "Warnung":
                typ_item.setForeground(QColor("#f59e0b"))
            else:
                typ_item.setForeground(QColor("#3b82f6"))
            self.error_table.setItem(row, 1, typ_item)

            # 2. Datei
            datei_item = QTableWidgetItem(prob.file_name)
            self.error_table.setItem(row, 2, datei_item)

            # 3. Zeile
            line_str = str(prob.line) if prob.line is not None else "-"
            line_item = QTableWidgetItem(line_str)
            line_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.error_table.setItem(row, 3, line_item)

            # 4. Meldung
            msg_item = QTableWidgetItem(prob.message)
            msg_item.setData(Qt.ItemDataRole.UserRole, prob)
            self.error_table.setItem(row, 4, msg_item)

    def on_problem_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        msg_item = self.error_table.item(row, 4)
        if not msg_item:
            return
        prob: InspectionProblem = msg_item.data(Qt.ItemDataRole.UserRole)
        if not prob:
            return

        # If problem belongs to another file, open it first
        if prob.file_path and self.current_spec_path != prob.file_path:
            self.load_spec_file(prob.file_path)

        if prob.line is not None:
            self.goto_line(prob.line)

    def goto_line(self, line_num: int):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(line_num - 1):
            cursor.movePosition(QTextCursor.MoveOperation.Down)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def on_cursor_position_changed(self):
        cursor = self.editor.textCursor()
        current_line = cursor.blockNumber() + 1

        # 1. Update Step Assistant with detected phase
        detected_phase = detect_phase_at_cursor(self.editor)
        self.step_assistant.set_phase(detected_phase)

        # 2. Update Step Inspector
        if not self.last_compilation_result or not self.last_compilation_result.steps_by_line:
            self.clear_step_inspector(f"Zeile {current_line}: Keine Übersetzung verfügbar")
            return

        step_info = self.last_compilation_result.steps_by_line.get(current_line)
        if not step_info:
            self.clear_step_inspector(f"Zeile {current_line}: Kein Testschritt (Überschrift, Kommentar oder Leerzeile)")
            return

        step_num_str = f"Schritt {step_info.step_number}" if step_info.step_number is not None else "Schritt"
        self.insp_line_lbl.setText(f"Zeile {step_info.line} &nbsp;•&nbsp; {step_num_str} ({step_info.phase})")

        self.insp_map_lbl.setText(f"[{step_info.mapping_id}]<br>\"{step_info.template}\"")
        self.insp_op_lbl.setText(step_info.operation_name)
        self.insp_op_doc.setText(step_info.operation_doc or "Keine Beschreibung vorhanden.")

        args_lines = [f"• {k} = <b>{v!r}</b> <span style='color: #64748b;'>({type(v).__name__})</span>" for k, v in step_info.arguments.items()]
        self.insp_params_lbl.setText("<br>".join(args_lines) if args_lines else "<i>Keine Parameter</i>")

        # Action <-> Expectation Link
        if step_info.linked_step_desc and step_info.linked_step_line:
            self.insp_linked_step_lbl.setText(step_info.linked_step_desc)
            self.btn_jump_linked.setText(f"Zu Zeile {step_info.linked_step_line} springen")
            self.btn_jump_linked.setEnabled(True)
            self.target_jump_line = step_info.linked_step_line
        else:
            self.insp_linked_step_lbl.setText("Keine Verknüpfung vorhanden.")
            self.btn_jump_linked.setEnabled(False)
            self.target_jump_line = None

        self.insp_call_code.setPlainText(step_info.rendered_call)

    @property
    def current_linked_line(self) -> int | None:
        return self.target_jump_line

    def inspect_current_line(self):
        self.on_cursor_position_changed()

    def jump_to_linked_line(self):
        if self.target_jump_line:
            self.goto_line(self.target_jump_line)

    def clear_step_inspector(self, text: str):
        self.insp_line_lbl.setText(text)
        self.insp_map_lbl.setText("-")
        self.insp_op_lbl.setText("-")
        self.insp_op_doc.setText("-")
        self.insp_params_lbl.setText("-")
        self.insp_linked_step_lbl.setText("-")
        self.btn_jump_linked.setEnabled(False)
        self.target_jump_line = None
        self.insp_call_code.clear()

    def insert_statement_at_cursor(self, statement: str):
        cursor = self.editor.textCursor()
        line_text = cursor.block().text()

        has_step_prefix = bool(re.match(r'^\s*[0-9]+[.:]', statement))
        if not has_step_prefix:
            prev_block = cursor.block().previous()
            prev_text = prev_block.text() if prev_block.isValid() else ""
            m = re.match(r'^\s*([0-9]+)[.:]', prev_text)
            if m:
                next_step = int(m.group(1)) + 10
                statement = f"{next_step}. {statement}"
            else:
                statement = f"10. {statement}"

        cursor.beginEditBlock()
        if cursor.atBlockStart():
            cursor.insertText(statement + "\n")
        else:
            cursor.insertText("\n" + statement + "\n")
        cursor.endEditBlock()

        self.editor.setTextCursor(cursor)
        self.editor.setFocus()
        self.is_spec_dirty = True
        self.compile_current_text(sync=True)

    def save_current_spec(self) -> bool:
        if not self.current_spec_path:
            return False
        try:
            content = self.editor.toPlainText()
            self.current_spec_path.write_text(content, encoding='utf-8')
            self.editor.document().setModified(False)
            self.is_spec_dirty = False
            self.lbl_current_file.setText(f"{self.current_spec_path.name} ({self.current_spec_path.parent.name})")
            self.on_change()
            self.compile_current_text(sync=True)
            self.trigger_background_project_analysis()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Konnte Datei nicht speichern: {e}")
            return False
