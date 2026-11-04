"""Specification Editor and translation inspector workspace for SpecToTest GUI."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
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

from tcg.gui.facade import CompilationError, CompilationFacade, CompilationResult, StepInspectionInfo
from tcg.gui.models import MappingStudioState
from tcg.gui.syntax import SpecSyntaxHighlighter


class SpecificationWorkspace(QWidget):
    """Workspace for browsing, editing, and inspecting specifications and generated code."""

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.current_spec_path: Path | None = None
        self.last_compilation_result: CompilationResult | None = None

        self.setup_ui()
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

        btn_refresh_files = QPushButton("Aktualisieren")
        btn_refresh_files.clicked.connect(self.refresh_spec_list)
        file_layout.addWidget(btn_refresh_files)

        main_splitter.addWidget(file_panel)

        # --- CENTER: Editor & Error Panel ---
        editor_panel = QWidget()
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)

        editor_top = QHBoxLayout()
        self.lbl_current_file = QLabel("Keine Datei geöffnet")
        self.lbl_current_file.setFont(QFont("", 10, QFont.Weight.Bold))
        editor_top.addWidget(self.lbl_current_file, stretch=2)

        self.btn_save_spec = QPushButton("Spezifikation speichern")
        self.btn_save_spec.clicked.connect(self.save_current_spec)
        self.btn_save_spec.setEnabled(False)
        editor_top.addWidget(self.btn_save_spec)

        self.btn_recompile = QPushButton("Neu übersetzen")
        self.btn_recompile.clicked.connect(self.compile_current_text)
        self.btn_recompile.setEnabled(False)
        editor_top.addWidget(self.btn_recompile)

        editor_layout.addLayout(editor_top)

        # Editor Splitter (Code Editor above, Error Table below)
        edit_splitter = QSplitter(Qt.Orientation.Vertical)

        # Text Editor
        self.editor = QTextEdit()
        self.editor.setFont(QFont("Monospace", 10))
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.highlighter = SpecSyntaxHighlighter(self.editor.document(), dark_theme=True)
        self.editor.cursorPositionChanged.connect(self.on_cursor_position_changed)
        self.editor.textChanged.connect(self.on_editor_text_changed)
        edit_splitter.addWidget(self.editor)

        # Error / Validation Table
        error_group = QGroupBox("Meldungen & Übersetzungsdiagnose")
        error_layout = QVBoxLayout(error_group)
        error_layout.setContentsMargins(4, 8, 4, 4)

        self.error_table = QTableWidget(0, 3)
        self.error_table.setHorizontalHeaderLabels(["Zeile", "Abschnitt", "Meldung"])
        self.error_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.error_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.error_table.itemDoubleClicked.connect(self.on_error_double_clicked)
        error_layout.addWidget(self.error_table)

        edit_splitter.addWidget(error_group)
        edit_splitter.setStretchFactor(0, 4)
        edit_splitter.setStretchFactor(1, 1)

        editor_layout.addWidget(edit_splitter)
        main_splitter.addWidget(editor_panel)

        # --- RIGHT: Translation Inspector & Code Preview ---
        right_panel = QTabWidget()

        # Tab A: Schritt-Inspektor
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
        self.insp_op_lbl.setStyleSheet("font-weight: bold; color: #0d6efd;")
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

        step_layout.addWidget(QLabel("<b>Erzeugter Python-Aufruf:</b>"))
        self.insp_call_code = QTextEdit()
        self.insp_call_code.setReadOnly(True)
        self.insp_call_code.setFont(QFont("Monospace", 9))
        self.insp_call_code.setMaximumHeight(80)
        step_layout.addWidget(self.insp_call_code)

        step_layout.addStretch()
        right_panel.addTab(step_tab, "Schritt-Inspektor")

        # Tab B: Vollständiger generierter Python-Code
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

        # Splitter sizing
        main_splitter.setStretchFactor(0, 1)
        main_splitter.setStretchFactor(1, 3)
        main_splitter.setStretchFactor(2, 2)

        main_layout.addWidget(main_splitter)

        # Debounce timer for re-compilation while typing
        self.compile_timer = QTimer(self)
        self.compile_timer.setSingleShot(True)
        self.compile_timer.setInterval(400)
        self.compile_timer.timeout.connect(self.compile_current_text)

    def refresh_spec_list(self):
        """Scan specs_dir from current profile and update list."""
        specs_dir = self.state.profile_config.specs_dir
        self.all_spec_files = CompilationFacade.list_spec_files(specs_dir)
        self.filter_file_list()

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

    def on_file_selected(self):
        items = self.file_list.selectedItems()
        if not items:
            return
        path_str = items[0].data(Qt.ItemDataRole.UserRole)
        p = Path(path_str)
        self.load_spec_file(p)

    def load_spec_file(self, path: Path):
        self.current_spec_path = path
        try:
            text = path.read_text(encoding='utf-8-sig')
            self.editor.blockSignals(True)
            self.editor.setPlainText(text)
            self.editor.blockSignals(False)
            self.lbl_current_file.setText(f"{path.name} ({path.parent.name})")
            self.btn_save_spec.setEnabled(True)
            self.btn_recompile.setEnabled(True)
            self.compile_current_text()
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Laden", f"Konnte Datei '{path.name}' nicht öffnen: {e}")

    def on_editor_text_changed(self):
        self.compile_timer.start()

    def compile_current_text(self):
        """Compile editor content in-memory via CompilationFacade."""
        if not self.current_spec_path:
            return

        text = self.editor.toPlainText()
        name = self.current_spec_path.name

        mapping_dicts = [m.to_dict() for m in self.state.mappings if m.is_valid and not m.has_conflict]
        result = CompilationFacade.compile_text(
            text=text,
            source_name=name,
            registry=self.state.registry,
            mapping_dicts=mapping_dicts,
            profile=self.state.profile,
        )
        self.last_compilation_result = result
        self.update_error_table(result.errors)

        if result.success:
            self.code_view.setPlainText(result.python_code)
        else:
            self.code_view.setPlainText(f"# Fehlerhafte Übersetzung:\n# {result.summary}")

        # Update step inspector for current cursor line
        self.on_cursor_position_changed()

    def update_error_table(self, errors: list[CompilationError]):
        self.error_table.setRowCount(len(errors))
        for row, err in enumerate(errors):
            line_str = str(err.line) if err.line is not None else "-"
            line_item = QTableWidgetItem(line_str)
            line_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.error_table.setItem(row, 0, line_item)

            sec_item = QTableWidgetItem(err.section or "-")
            self.error_table.setItem(row, 1, sec_item)

            msg_item = QTableWidgetItem(err.message)
            msg_item.setForeground(QColor("#ef4444"))
            self.error_table.setItem(row, 2, msg_item)

    def on_error_double_clicked(self, item: QTableWidgetItem):
        row = item.row()
        line_item = self.error_table.item(row, 0)
        if line_item and line_item.text().isdigit():
            target_line = int(line_item.text())
            self.goto_line(target_line)

    def goto_line(self, line_num: int):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        for _ in range(line_num - 1):
            cursor.movePosition(QTextCursor.MoveOperation.Down)
        cursor.movePosition(QTextCursor.MoveOperation.StartOfLine)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def on_cursor_position_changed(self):
        """Update step inspector based on current line."""
        cursor = self.editor.textCursor()
        current_line = cursor.blockNumber() + 1

        if not self.last_compilation_result or not self.last_compilation_result.steps_by_line:
            self.clear_step_inspector(f"Zeile {current_line}: Keine Übersetzung verfügbar")
            return

        step_info = self.last_compilation_result.steps_by_line.get(current_line)
        if not step_info:
            self.clear_step_inspector(f"Zeile {current_line}: Kein Testschritt (Überschrift, Kommentar oder Leerzeile)")
            return

        # Populate step inspector
        step_num_str = f"Schritt {step_info.step_number}" if step_info.step_number is not None else "Schritt"
        self.insp_line_lbl.setText(f"Zeile {step_info.line} &nbsp;•&nbsp; {step_num_str} ({step_info.phase})")

        self.insp_map_lbl.setText(f"[{step_info.mapping_id}]<br>\"{step_info.template}\"")
        self.insp_op_lbl.setText(step_info.operation_name)
        self.insp_op_doc.setText(step_info.operation_doc or "Keine Beschreibung vorhanden.")

        args_lines = [f"• {k} = <b>{v!r}</b> <span style='color: #64748b;'>({type(v).__name__})</span>" for k, v in step_info.arguments.items()]
        self.insp_params_lbl.setText("<br>".join(args_lines) if args_lines else "<i>Keine Parameter</i>")

        self.insp_call_code.setPlainText(step_info.rendered_call)

    def clear_step_inspector(self, text: str):
        self.insp_line_lbl.setText(text)
        self.insp_map_lbl.setText("-")
        self.insp_op_lbl.setText("-")
        self.insp_op_doc.setText("-")
        self.insp_params_lbl.setText("-")
        self.insp_call_code.clear()

    def save_current_spec(self):
        if not self.current_spec_path:
            return
        try:
            content = self.editor.toPlainText()
            self.current_spec_path.write_text(content, encoding='utf-8')
            self.on_change()
            self.compile_current_text()
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Konnte Datei nicht speichern: {e}")
