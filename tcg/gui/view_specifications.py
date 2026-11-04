"""Specification Editor and translation inspector workspace for SpecToTest GUI."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Callable

from PySide6.QtCore import QStringListModel, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
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

from tcg.gui.facade import CompilationError, CompilationFacade, CompilationResult, StepInspectionInfo
from tcg.gui.models import MappingStudioState
from tcg.gui.syntax import SpecSyntaxHighlighter


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
        # Insert remaining part
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

        # Trigger autocompletion on Ctrl+Space
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


class SpecificationWorkspace(QWidget):
    """Workspace for browsing, editing, and inspecting specifications and generated code."""

    def __init__(self, state: MappingStudioState, on_change: Callable[[], None], parent: QWidget | None = None):
        super().__init__(parent)
        self.state = state
        self.on_change = on_change
        self.current_spec_path: Path | None = None
        self.last_compilation_result: CompilationResult | None = None
        self.is_spec_dirty: bool = False
        self.is_loading_file: bool = False
        self.target_jump_line: int | None = None

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
        self.btn_save_spec.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
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

        # Custom Code Editor with Autocompletion
        self.editor = SpecCodeEditor()
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

    def setup_autocompletion(self):
        """Build autocomplete model from all valid mapping templates."""
        templates = [m.template for m in self.state.mappings if m.is_valid and not m.has_conflict]
        completer = QCompleter(templates, self)
        self.editor.set_completer(completer)

    def refresh_spec_list(self):
        """Scan specs_dir from current profile and update list."""
        if not self.prompt_save_spec_if_dirty():
            return

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

    def prompt_save_spec_if_dirty(self) -> bool:
        """Prompt to save unsaved specification changes before switching files or profiles.
        
        Returns True if safe to proceed, False if user cancelled.
        """
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
            # Revert selection in list without switching file
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
            self.compile_current_text()
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

    def compile_current_text(self):
        """Compile editor content in-memory via CompilationFacade."""
        if not self.current_spec_path:
            return

        text = self.editor.toPlainText()
        name = self.current_spec_path.name

        mapping_dicts = self.state.get_mappings_dicts()
        result = CompilationFacade.compile_text(
            text=text,
            source_name=name,
            registry=self.state.registry,
            mapping_dicts=mapping_dicts,
            profile=self.state.profile,
            strict_project_check=True,
        )
        self.last_compilation_result = result
        self.update_error_table(result.errors)

        if result.success:
            self.code_view.setPlainText(result.python_code)
        else:
            self.code_view.setPlainText(f"# FEHLERHAFTE ÜBERSETZUNG:\n# {result.summary}\n\n{result.python_code}")

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
        """Update step inspector for the current cursor position."""
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
        """Insert a verified statement into the specification text at cursor or on a new step line."""
        cursor = self.editor.textCursor()
        line_text = cursor.block().text()

        # Check if line already has a step number like "10." or "20:"
        has_step_prefix = bool(re.match(r'^\s*[0-9]+[.:]', statement))

        if not has_step_prefix:
            # Check previous line step number to auto-increment (e.g. 10 -> 20)
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
        self.compile_current_text()

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
            self.compile_current_text()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Konnte Datei nicht speichern: {e}")
            return False
