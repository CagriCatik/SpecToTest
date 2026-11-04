"""Specification Workspace with background analysis, multi-tier problem tracking, and integrated Step Assistant."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Callable

from PySide6.QtCore import QRegularExpression, QSize, Qt, QTimer, Signal
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
    QMenu,
    QMessageBox,
    QPushButton,
    QToolButton,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.analysis_worker import BackgroundAnalysisManager, InspectionProblem
from tcg.gui.facade import CompilationError, CompilationFacade, CompilationResult, StepInspectionInfo
from tcg.gui.models import MappingStudioState
from tcg.gui.styles import get_monospace_font, get_theme_tokens
from tcg.gui.syntax import SpecSyntaxHighlighter
from tcg.gui.widget_smart_param import SmartParamWidget, build_smart_param_widget


class CompactPathLabel(QLabel):
    """QLabel that shrinks below its text width, eliding the text and keeping it in a tooltip.

    The full text always stays reachable: whenever the visible text is shortened, the
    untruncated value is offered as the tooltip.
    """

    def __init__(self, text: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self._full_text = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt naming
        self._full_text = text or ""
        self.setToolTip(self._full_text)
        self._apply_elided_text()

    def full_text(self) -> str:
        return self._full_text

    def minimumSizeHint(self) -> QSize:
        return QSize(40, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._apply_elided_text()

    def _apply_elided_text(self) -> None:
        available = max(0, self.width() - 4)
        if not self._full_text or available <= 0:
            QLabel.setText(self, self._full_text)
            return
        elided = self.fontMetrics().elidedText(self._full_text, Qt.TextElideMode.ElideMiddle,
                                               available)
        QLabel.setText(self, elided)


class OverflowToolBar(QWidget):
    """A one-row action bar that moves actions into an overflow menu when space runs short.

    Buttons are kept at their natural width so a label is never squeezed into an
    unreadable fragment. When the row does not fit, the lowest-priority actions move
    into a labelled overflow menu, where they stay reachable with their full text.
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._entries: list[dict[str, Any]] = []
        self._stretch_widget: QWidget | None = None
        self._stretch_factor = 1
        self._stretch_reserve = 160

        self._layout = QHBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)

        self._overflow = QToolButton(self)
        self._overflow.setText("Weitere Aktionen")
        self._overflow.setToolTip("Weitere Aktionen dieser Werkzeugleiste anzeigen")
        self._overflow.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        self._overflow_menu = QMenu(self._overflow)
        self._overflow.setMenu(self._overflow_menu)
        # Leave room for the menu indicator so the caption is never clipped.
        self._overflow.setMinimumWidth(self._overflow.sizeHint().width() + 14)
        self._overflow.hide()

    def add_button(self, button: QPushButton, priority: int = 0) -> QPushButton:
        """Add an action. Lower `priority` moves into the overflow menu first."""
        button.setParent(self)
        button.setMinimumWidth(button.sizeHint().width())
        self._entries.append({'button': button, 'priority': priority})
        self._rebuild()
        return button

    def add_stretch_widget(self, widget: QWidget, stretch: int = 1,
                           readable_width: int = 160) -> QWidget:
        """Add the one widget that absorbs the remaining space (e.g. the file name).

        `readable_width` is the space kept free for it before any action is moved into
        the overflow menu, so a file name is never crushed to a meaningless stub while
        buttons keep their place.
        """
        widget.setParent(self)
        self._stretch_widget = widget
        self._stretch_factor = stretch
        self._stretch_reserve = readable_width
        self._rebuild()
        return widget

    def minimum_full_width(self) -> int:
        """Width needed to show every action plus a minimum for the stretch widget."""
        spacing = self._layout.spacing() * max(0, len(self._entries))
        buttons = sum(entry['button'].sizeHint().width() for entry in self._entries)
        stretch = self._stretch_reserve if self._stretch_widget else 0
        return buttons + stretch + spacing

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._relayout()

    def _rebuild(self) -> None:
        while self._layout.count():
            self._layout.takeAt(0)
        for entry in self._entries:
            self._layout.addWidget(entry['button'])
            if self._stretch_widget is not None and entry is self._entries[0]:
                self._layout.addWidget(self._stretch_widget, stretch=self._stretch_factor)
        if self._stretch_widget is not None and not self._entries:
            self._layout.addWidget(self._stretch_widget, stretch=self._stretch_factor)
        self._layout.addWidget(self._overflow)
        self._relayout()

    def _relayout(self) -> None:
        """Decide which actions stay in the row and which move into the overflow menu."""
        available = self.width()
        if available <= 0:
            return
        spacing = self._layout.spacing()
        reserve = self._stretch_reserve if self._stretch_widget else 0

        # Highest priority first: these are the actions we keep in the row the longest.
        ordered = sorted(self._entries, key=lambda e: -e['priority'])
        used, visible = reserve, []
        for entry in ordered:
            width = entry['button'].sizeHint().width() + spacing
            if used + width <= available:
                used += width
                visible.append(entry)

        hidden = [entry for entry in self._entries if entry not in visible]
        if hidden:
            overflow_width = self._overflow.sizeHint().width() + spacing
            # Make room for the overflow button itself.
            while visible and used + overflow_width > available:
                dropped = min(visible, key=lambda e: e['priority'])
                visible.remove(dropped)
                hidden.append(dropped)
                used -= dropped['button'].sizeHint().width() + spacing

        for entry in self._entries:
            entry['button'].setVisible(entry in visible)

        self._overflow_menu.clear()
        for entry in sorted(hidden, key=lambda e: self._entries.index(e)):
            button = entry['button']
            action = self._overflow_menu.addAction(button.text())
            action.setToolTip(button.toolTip())
            action.setEnabled(button.isEnabled())
            action.setCheckable(button.isCheckable())
            action.setChecked(button.isChecked())
            action.triggered.connect(button.click)
        self._overflow.setVisible(bool(hidden))

    def refresh(self) -> None:
        """Re-evaluate the row, e.g. after an action's enabled state changed."""
        self._relayout()


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


class SpecFileTreeWidget(QTreeWidget):
    """Hierarchical category tree for test specification files."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setIndentation(14)
        self.setAnimated(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setTextElideMode(Qt.TextElideMode.ElideMiddle)

    def count(self) -> int:
        """Return total number of file items across all categories for test compatibility."""
        total = 0
        for i in range(self.topLevelItemCount()):
            cat = self.topLevelItem(i)
            total += cat.childCount()
        return total


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
        self.txt_preview.setFont(get_monospace_font(9, bold=True))
        self.txt_preview.textChanged.connect(self.verify_preview_sentence)
        layout.addWidget(self.txt_preview)

        self.lbl_verify = QLabel("-")
        self.lbl_verify.setWordWrap(True)
        layout.addWidget(self.lbl_verify)

        # 6. Action Button
        self.btn_insert = QPushButton("Schritt einfügen")
        self.btn_insert.setToolTip("Schritt an Cursor-Position in Spezifikation einfügen")
        self.btn_insert.setProperty("primary", "true")
        self.btn_insert.clicked.connect(self.on_insert_clicked)
        layout.addWidget(self.btn_insert)

        layout.addStretch()

    def set_phase(self, phase: str):
        if phase == self.current_phase and self.combo_ops.count() > 0:
            return
        self.current_phase = phase
        is_check = phase in ("EXPECTED_RESULT", "EXPECTED", "CHECK")
        phase_label = "EXPECTED RESULT (Prüfung)" if is_check else f"{phase} (Setup)"
        self.lbl_phase_badge.setWordWrap(True)
        self.lbl_phase_badge.setText(f"Erkannte Phase: <b>{phase_label}</b>")
        self.lbl_phase_badge.setStyleSheet(
            "border: 1px solid rgba(13, 110, 253, 0.3); background-color: rgba(13, 110, 253, 0.08); padding: 5px 8px; border-radius: 4px;"
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
            lbl.setFont(get_monospace_font(9, bold=True))
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
        self.main_splitter = QSplitter(Qt.Orientation.Horizontal)
        main_splitter = self.main_splitter

        # --- LEFT: Spec File Explorer ---
        self.file_panel = QWidget()
        file_panel = self.file_panel
        file_panel.setMinimumWidth(0)
        file_layout = QVBoxLayout(file_panel)
        file_layout.setContentsMargins(0, 0, 0, 0)
        file_layout.setSpacing(6)

        file_header = QLabel("<b>Spezifikationsdateien</b>")
        file_layout.addWidget(file_header)

        self.file_search = QLineEdit()
        self.file_search.setPlaceholderText("Filter...")
        self.file_search.textChanged.connect(self.filter_file_list)
        file_layout.addWidget(self.file_search)

        self.file_tree = SpecFileTreeWidget(self)
        self.file_tree.itemSelectionChanged.connect(self.on_file_selected)
        file_layout.addWidget(self.file_tree)
        self.file_list = self.file_tree  # Backward compatibility alias

        btn_refresh_files = QPushButton("Aktualisieren")
        btn_refresh_files.clicked.connect(self.refresh_spec_list)
        file_layout.addWidget(btn_refresh_files)

        main_splitter.addWidget(file_panel)

        # --- CENTER: Editor & Problem Panel ---
        editor_panel = QWidget()
        editor_panel.setMinimumWidth(250)
        editor_layout = QVBoxLayout(editor_panel)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(6)

        # The editor toolbar keeps full button labels and moves the least important
        # actions into an overflow menu on narrow windows, so no action is lost and no
        # caption is squeezed into an unreadable fragment.
        editor_top = OverflowToolBar()

        self.btn_toggle_tree = QPushButton("Dateibaum")
        self.btn_toggle_tree.setCheckable(True)
        self.btn_toggle_tree.setChecked(True)
        self.btn_toggle_tree.setToolTip("Dateibaum links ein-/ausblenden")
        self.btn_toggle_tree.clicked.connect(self.toggle_tree_panel)
        editor_top.add_button(self.btn_toggle_tree, priority=1)

        self.lbl_current_file = CompactPathLabel("Keine Datei geöffnet")
        self.lbl_current_file.setFont(QFont("", 10, QFont.Weight.Bold))
        editor_top.add_stretch_widget(self.lbl_current_file, stretch=2)

        self.btn_save_spec = QPushButton("Speichern")
        self.btn_save_spec.setToolTip("Aktuelle Spezifikation speichern")
        self.btn_save_spec.clicked.connect(self.save_current_spec)
        self.btn_save_spec.setEnabled(False)
        editor_top.add_button(self.btn_save_spec, priority=4)

        self.btn_recompile = QPushButton("Neu übersetzen")
        self.btn_recompile.setToolTip("Aktuelle Spezifikation erneut übersetzen")
        self.btn_recompile.clicked.connect(lambda: self.compile_current_text(sync=True))
        self.btn_recompile.setEnabled(False)
        editor_top.add_button(self.btn_recompile, priority=3)

        self.btn_toggle_inspector = QPushButton("Inspektor")
        self.btn_toggle_inspector.setCheckable(True)
        self.btn_toggle_inspector.setChecked(True)
        self.btn_toggle_inspector.setToolTip("Rechte Seitenleiste (Inspektor / Assistent / Python) ein-/ausblenden")
        self.btn_toggle_inspector.clicked.connect(self.toggle_inspector_panel)
        editor_top.add_button(self.btn_toggle_inspector, priority=2)

        self.editor_toolbar = editor_top
        editor_layout.addWidget(editor_top)

        # Status line for the background analysis: always a readable word, never colour alone.
        self.lbl_analysis_status = CompactPathLabel("Bereit")
        self.lbl_analysis_status.setFont(QFont("", 9, QFont.Weight.Bold))
        editor_layout.addWidget(self.lbl_analysis_status)

        # Vertical Splitter: Editor above, Multi-Tier Problem Table below
        self.edit_splitter = QSplitter(Qt.Orientation.Vertical)

        self.editor = SpecCodeEditor()
        self.editor.setFont(get_monospace_font(10))
        self.editor.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.highlighter = SpecSyntaxHighlighter(self.editor.document(), dark_theme=True)
        self.editor.cursorPositionChanged.connect(self.on_cursor_position_changed)
        self.editor.textChanged.connect(self.on_editor_text_changed)
        self.edit_splitter.addWidget(self.editor)

        # Multi-Tier Problem List Panel (Collapsible)
        problem_group = QWidget()
        prob_main_layout = QVBoxLayout(problem_group)
        prob_main_layout.setContentsMargins(0, 4, 0, 0)
        prob_main_layout.setSpacing(4)

        prob_header = QHBoxLayout()
        prob_header.setSpacing(8)

        self.btn_toggle_problems = QPushButton("Problemliste (0) ▼")
        self.btn_toggle_problems.setCheckable(True)
        self.btn_toggle_problems.setChecked(False)
        self.btn_toggle_problems.clicked.connect(self.toggle_problems_panel)
        prob_header.addWidget(self.btn_toggle_problems)

        prob_header.addStretch()
        prob_main_layout.addLayout(prob_header)

        self.problem_content = QWidget()
        prob_content_layout = QVBoxLayout(self.problem_content)
        prob_content_layout.setContentsMargins(0, 0, 0, 0)
        prob_content_layout.setSpacing(6)

        filter_row = QHBoxLayout()
        filter_row.setSpacing(6)

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
        prob_content_layout.addLayout(filter_row)

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
        prob_content_layout.addWidget(self.error_table)

        prob_main_layout.addWidget(self.problem_content)
        self.problem_content.setVisible(False)

        self.edit_splitter.addWidget(problem_group)
        self.edit_splitter.setStretchFactor(0, 5)
        self.edit_splitter.setStretchFactor(1, 1)

        editor_layout.addWidget(self.edit_splitter)
        main_splitter.addWidget(editor_panel)

        # --- RIGHT: Translation Inspector, Step Assistant & Code Preview ---
        self.right_panel = QTabWidget()
        self.right_sidebar = self.right_panel
        self.right_panel.setMinimumWidth(0)
        # On narrow windows elide the tab captions instead of hiding whole tabs behind
        # scroll arrows: every tab stays clickable, and its full name stays in the tooltip.
        self.right_panel.tabBar().setUsesScrollButtons(False)
        self.right_panel.tabBar().setElideMode(Qt.TextElideMode.ElideRight)
        self.right_panel.tabBar().setExpanding(False)

        # Tab 1: Details (Schritt-Inspektor)
        step_tab = QWidget()
        step_layout = QVBoxLayout(step_tab)
        step_layout.setContentsMargins(10, 10, 10, 10)
        step_layout.setSpacing(10)

        # Empty State Container (for headings, blank lines, comments)
        self.insp_empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.insp_empty_widget)
        empty_layout.setContentsMargins(12, 30, 12, 30)
        empty_layout.setSpacing(10)

        self.lbl_empty_state = QLabel("Wähle eine Testanweisung, um Operation, Parameter und Erwartung anzuzeigen.")
        self.lbl_empty_state.setWordWrap(True)
        self.lbl_empty_state.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_empty_state.setProperty("muted", "true")
        self.lbl_empty_state.setStyleSheet("font-size: 12px; line-height: 1.5;")
        empty_layout.addStretch()
        empty_layout.addWidget(self.lbl_empty_state)
        empty_layout.addStretch()
        step_layout.addWidget(self.insp_empty_widget)

        # Details Content Container (only shown on actual test steps)
        self.insp_details_widget = QWidget()
        self.insp_details_widget.setVisible(False)
        det_box = QVBoxLayout(self.insp_details_widget)
        det_box.setContentsMargins(0, 0, 0, 0)
        det_box.setSpacing(8)

        self.insp_line_lbl = QLabel("Wähle eine Zeile im Editor aus")
        self.insp_line_lbl.setFont(QFont("", 11, QFont.Weight.Bold))
        self.insp_line_lbl.setWordWrap(True)
        det_box.addWidget(self.insp_line_lbl)

        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFrameShadow(QFrame.Shadow.Sunken)
        det_box.addWidget(sep1)

        det_box.addWidget(QLabel("<b>Zugeordnetes Satzmuster:</b>"))
        self.insp_map_lbl = QLabel("-")
        self.insp_map_lbl.setFont(get_monospace_font(9))
        self.insp_map_lbl.setWordWrap(True)
        self.insp_map_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 6px; border-radius: 4px;")
        det_box.addWidget(self.insp_map_lbl)

        det_box.addWidget(QLabel("<b>Aufgerufene Operation:</b>"))
        self.insp_op_lbl = QLabel("-")
        self.insp_op_lbl.setStyleSheet("font-weight: bold; color: #0d6efd;")
        det_box.addWidget(self.insp_op_lbl)

        self.insp_op_doc = QLabel("-")
        self.insp_op_doc.setWordWrap(True)
        self.insp_op_doc.setProperty("doc", "true")
        det_box.addWidget(self.insp_op_doc)

        det_box.addWidget(QLabel("<b>Extrahierte & normalisierte Parameter:</b>"))
        self.insp_params_lbl = QLabel("-")
        self.insp_params_lbl.setFont(get_monospace_font(9))
        self.insp_params_lbl.setWordWrap(True)
        self.insp_params_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 6px; border-radius: 4px;")
        det_box.addWidget(self.insp_params_lbl)

        # Action <-> Expectation Link
        det_box.addWidget(QLabel("<b>Verknüpfte Aktion / Erwartung:</b>"))
        self.insp_linked_step_lbl = QLabel("Keine Verknüpfung")
        self.insp_linked_step_lbl.setWordWrap(True)
        self.insp_linked_step_lbl.setStyleSheet("background-color: rgba(128,128,128,0.1); padding: 6px; border-radius: 4px; font-size: 11px;")
        det_box.addWidget(self.insp_linked_step_lbl)

        self.btn_jump_linked = QPushButton("Zur verknüpften Zeile springen")
        self.btn_jump_linked.clicked.connect(self.jump_to_linked_line)
        self.btn_jump_linked.setEnabled(False)
        det_box.addWidget(self.btn_jump_linked)

        det_box.addWidget(QLabel("<b>Erzeugter Python-Aufruf:</b>"))
        self.insp_call_code = QTextEdit()
        self.insp_call_code.setReadOnly(True)
        self.insp_call_code.setFont(get_monospace_font(9))
        self.insp_call_code.setMaximumHeight(80)
        det_box.addWidget(self.insp_call_code)

        det_box.addStretch()
        step_layout.addWidget(self.insp_details_widget)

        self.right_panel.addTab(step_tab, "Details")
        self.right_panel.setTabToolTip(0, "Details zum gewählten Schritt")
        self.right_panel.setTabToolTip(0, "Schritt-Inspektor für die ausgewählte Zeile")

        # Tab 2: Schritt einfügen (Integrated Step Assistant)
        self.step_assistant = StepAssistantWidget(self.state, parent=self)
        self.step_assistant.insert_requested.connect(self.insert_statement_at_cursor)
        self.right_panel.addTab(self.step_assistant, "Einfügen")
        self.right_panel.setTabToolTip(1, "Schritt einfügen (Assistent)")
        self.right_panel.setTabToolTip(1, "Kontextbezogenen Testschritt formulieren und einfügen")

        # Tab 3: Python (Python-Vorschau)
        code_tab = QWidget()
        code_layout = QVBoxLayout(code_tab)
        code_layout.setContentsMargins(10, 10, 10, 10)
        code_layout.setSpacing(8)

        code_header = QLabel("<b>Generierte Python-Testdatei</b> (render_python)")
        code_header.setWordWrap(True)
        code_header.setMinimumWidth(0)
        code_layout.addWidget(code_header)

        self.code_view = QTextEdit()
        self.code_view.setReadOnly(True)
        self.code_view.setFont(get_monospace_font(9))
        self.code_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        code_layout.addWidget(self.code_view)

        self.right_panel.addTab(code_tab, "Python")
        self.right_panel.setTabToolTip(2, "Erzeugter Python-Code")
        self.right_panel.setTabToolTip(2, "Generierter Python-Testfallcode")

        main_splitter.addWidget(self.right_panel)

        main_splitter.setCollapsible(0, True)
        main_splitter.setCollapsible(1, False)
        main_splitter.setCollapsible(2, True)
        main_splitter.setStretchFactor(0, 0)
        main_splitter.setStretchFactor(1, 4)
        main_splitter.setStretchFactor(2, 2)
        main_splitter.setSizes([240, 560, 320])

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
        self.file_tree.clear()

        # Group files by category (immediate parent folder)
        categories: dict[str, list[Path]] = {}
        for f in self.all_spec_files:
            cat = f.parent.name or "Allgemein"
            categories.setdefault(cat, []).append(f)

        first_file_item: QTreeWidgetItem | None = None
        selected_item: QTreeWidgetItem | None = None

        for cat_name, files in sorted(categories.items()):
            matching = [
                f for f in files
                if not query or query in f.name.lower() or query in cat_name.lower()
            ]
            if not matching and query:
                continue

            cat_item = QTreeWidgetItem(self.file_tree)
            cat_item.setText(0, f"{cat_name} ({len(matching)})")
            cat_item.setToolTip(0, f"Kategorie: {cat_name} ({len(matching)} Datei(en))")
            cat_item.setFont(0, QFont("", 10, QFont.Weight.Bold))
            cat_item.setData(0, Qt.ItemDataRole.UserRole, "")
            cat_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            cat_item.setExpanded(True)

            for f in matching:
                f_item = QTreeWidgetItem(cat_item)
                f_item.setText(0, f.name)
                f_item.setToolTip(0, f"{f.name}\n({f.resolve()})")
                f_item.setData(0, Qt.ItemDataRole.UserRole, str(f.resolve()))
                if first_file_item is None:
                    first_file_item = f_item
                if self.current_spec_path and f.resolve() == self.current_spec_path.resolve():
                    selected_item = f_item

        if selected_item:
            self.file_tree.setCurrentItem(selected_item)
        elif first_file_item and not self.current_spec_path:
            self.file_tree.setCurrentItem(first_file_item)

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
        items = self.file_tree.selectedItems()
        if not items:
            return
        path_str = items[0].data(0, Qt.ItemDataRole.UserRole)
        if not path_str:
            # Clicked a category header -> toggle expand
            items[0].setExpanded(not items[0].isExpanded())
            return

        p = Path(path_str)
        if self.current_spec_path and p.resolve() == self.current_spec_path.resolve():
            return

        if not self.prompt_save_spec_if_dirty():
            self._select_file_in_tree(self.current_spec_path)
            return

        self.load_spec_file(p)

    def _select_file_in_tree(self, path: Path | None):
        if not path:
            return
        target = str(path.resolve())
        for i in range(self.file_tree.topLevelItemCount()):
            cat = self.file_tree.topLevelItem(i)
            for j in range(cat.childCount()):
                child = cat.child(j)
                if child.data(0, Qt.ItemDataRole.UserRole) == target:
                    self.file_tree.blockSignals(True)
                    self.file_tree.setCurrentItem(child)
                    self.file_tree.blockSignals(False)
                    return

    def load_spec_file(self, path: Path):
        self.compile_timer.stop()
        doc_identity = str(path.resolve())
        self.analysis_manager.next_doc_revision(doc_identity)
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
            self.btn_save_spec.setProperty("primary", "false")
            self.btn_save_spec.setText("Speichern")
            self.btn_save_spec.style().unpolish(self.btn_save_spec)
            self.btn_save_spec.style().polish(self.btn_save_spec)
            self.btn_recompile.setEnabled(True)
            self._select_file_in_tree(path)
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
            self.analysis_manager.next_doc_revision(str(self.current_spec_path.resolve()))
        self.btn_save_spec.setProperty("primary", "true")
        self.btn_save_spec.setText("Speichern *")
        self.btn_save_spec.style().unpolish(self.btn_save_spec)
        self.btn_save_spec.style().polish(self.btn_save_spec)
        tokens = get_theme_tokens(getattr(self, "dark_theme", True))
        self.lbl_analysis_status.setText(f"<span style='color: {tokens['text_muted']};'>Ergebnis veraltet</span>")
        self.lbl_analysis_status.setToolTip("Dokument geändert, Neuübersetzung steht aus")
        self.compile_timer.start()

    def trigger_background_doc_analysis(self):
        """Debounced background compilation task."""
        if not self.current_spec_path:
            return
        text = self.editor.toPlainText()
        name = self.current_spec_path.name
        mapping_dicts = self.state.get_mappings_dicts()
        doc_identity = str(self.current_spec_path.resolve())

        self.analysis_manager.schedule_doc_analysis(
            text=text,
            source_name=name,
            doc_identity=doc_identity,
            registry=self.state.registry,
            mapping_dicts=mapping_dicts,
            profile=self.state.profile,
            revision=self.analysis_manager.current_doc_revision,
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
            revision=self.analysis_manager.current_project_revision,
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

    def on_doc_analysis_started(self, doc_identity: str = "", revision: int = 0):
        curr_identity = str(self.current_spec_path.resolve()) if self.current_spec_path else ""
        if revision != self.analysis_manager.current_doc_revision:
            return
        if doc_identity and curr_identity and doc_identity != curr_identity:
            return
        tokens = get_theme_tokens(getattr(self, "dark_theme", True))
        self.lbl_analysis_status.setText(f"<span style='color: {tokens['accent']};'>Prüfung läuft...</span>")
        self.lbl_analysis_status.setToolTip(f"Revision {revision} in Bearbeitung...")

    def on_doc_analysis_finished(self, result: CompilationResult, doc_identity: str = "", revision: int = 0):
        curr_identity = str(self.current_spec_path.resolve()) if self.current_spec_path else ""

        is_stale_revision = (revision != self.analysis_manager.current_doc_revision)
        is_different_doc = bool(curr_identity and doc_identity and doc_identity != curr_identity)

        if is_stale_revision or is_different_doc:
            # Stale or mismatched result: discard without mutating the current document's status
            return

        self.apply_doc_result(result, revision)

    def on_doc_analysis_failed(self, error_msg: str, doc_identity: str = "", revision: int = 0):
        curr_identity = str(self.current_spec_path.resolve()) if self.current_spec_path else ""
        if revision != self.analysis_manager.current_doc_revision:
            return
        if doc_identity and curr_identity and doc_identity != curr_identity:
            return
        tokens = get_theme_tokens(getattr(self, "dark_theme", True))
        self.lbl_analysis_status.setText(f"<span style='color: {tokens['error']};'>Analysefehler</span>")
        self.lbl_analysis_status.setToolTip(error_msg)

    def apply_doc_result(self, result: CompilationResult, revision: int):
        self.last_compilation_result = result
        tokens = get_theme_tokens(getattr(self, "dark_theme", True))
        if result.success:
            self.lbl_analysis_status.setText(f"<span style='color: {tokens['success']}; font-weight: 600;'>Prüfung aktuell</span>")
            self.lbl_analysis_status.setToolTip(f"Revision {revision} erfolgreich übersetzt")
            self.code_view.setPlainText(result.python_code)
        else:
            self.lbl_analysis_status.setText(f"<span style='color: {tokens['error']}; font-weight: 600;'>Prüfung fehlerhaft</span>")
            self.lbl_analysis_status.setToolTip(f"Revision {revision}: {result.summary}")
            self.code_view.setPlainText(f"# FEHLERHAFTE ÜBERSETZUNG:\n# {result.summary}\n\n{result.python_code}")

        self.rebuild_problem_list()
        self.on_cursor_position_changed()

    def toggle_problems_panel(self, checked: bool):
        self.problem_content.setVisible(checked)
        count = len(self.all_problems)
        self.btn_toggle_problems.setText(f"Problemliste ({count}) {'▲' if checked else '▼'}")
        if checked:
            self.edit_splitter.setSizes([450, 150])
        else:
            self.edit_splitter.setSizes([600, 30])

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
        n_errors = sum(1 for p in self.all_problems if p.severity == "Fehler")

        if hasattr(self, 'btn_toggle_problems'):
            if n_errors > 0 and not self.btn_toggle_problems.isChecked():
                self.btn_toggle_problems.setChecked(True)
                self.problem_content.setVisible(True)
                self.edit_splitter.setSizes([450, 150])
            is_open = self.btn_toggle_problems.isChecked()
            self.btn_toggle_problems.setText(f"Problemliste ({n_all}) {'▲' if is_open else '▼'}")

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

        tokens = get_theme_tokens(getattr(self, "dark_theme", True))
        if hasattr(self, 'insp_empty_widget'):
            self.insp_empty_widget.setVisible(False)
        if hasattr(self, 'insp_details_widget'):
            self.insp_details_widget.setVisible(True)

        step_num_str = f"Schritt {step_info.step_number}" if step_info.step_number is not None else "Schritt"
        self.insp_line_lbl.setText(f"Zeile {step_info.line} · {step_num_str} ({step_info.phase})")

        self.insp_map_lbl.setText(f"[{step_info.mapping_id}]<br>\"{step_info.template}\"")
        self.insp_op_lbl.setText(step_info.operation_name)
        self.insp_op_doc.setText(step_info.operation_doc or "Keine Beschreibung vorhanden.")

        args_lines = [f"• {k} = <b>{v!r}</b> <span style='color: {tokens['text_muted']};'>({type(v).__name__})</span>" for k, v in step_info.arguments.items()]
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
        if hasattr(self, 'insp_empty_widget'):
            self.insp_empty_widget.setVisible(True)
        if hasattr(self, 'insp_details_widget'):
            self.insp_details_widget.setVisible(False)
        if hasattr(self, 'lbl_empty_state'):
            self.lbl_empty_state.setText("Wähle eine Testanweisung, um Operation, Parameter und Erwartung anzuzeigen.")
        self.insp_line_lbl.setText(text)
        self.insp_map_lbl.setText("-")
        self.insp_op_lbl.setText("-")
        self.insp_op_doc.setText("-")
        self.insp_params_lbl.setText("-")
        self.insp_linked_step_lbl.setText("-")
        self.btn_jump_linked.setEnabled(False)
        self.target_jump_line = None
        self.insp_call_code.clear()

    def toggle_tree_panel(self, checked: bool):
        if hasattr(self, 'file_panel'):
            self.file_panel.setVisible(checked)
        if hasattr(self, 'btn_toggle_tree'):
            self.btn_toggle_tree.setChecked(checked)

    def toggle_inspector_panel(self, checked: bool):
        if hasattr(self, 'right_panel'):
            self.right_panel.setVisible(checked)
        if hasattr(self, 'btn_toggle_inspector'):
            self.btn_toggle_inspector.setChecked(checked)

    def set_theme(self, dark_theme: bool):
        self.dark_theme = dark_theme
        if hasattr(self, 'highlighter'):
            self.highlighter.set_dark_theme(dark_theme)
        if hasattr(self, 'insp_op_doc'):
            self.insp_op_doc.style().unpolish(self.insp_op_doc)
            self.insp_op_doc.style().polish(self.insp_op_doc)
        if hasattr(self, 'lbl_empty_state'):
            self.lbl_empty_state.style().unpolish(self.lbl_empty_state)
            self.lbl_empty_state.style().polish(self.lbl_empty_state)
        self.on_cursor_position_changed()

    def save_splitter_states(self, settings):
        if hasattr(self, 'main_splitter'):
            settings.setValue("specs_main_splitter", self.main_splitter.saveState())
        if hasattr(self, 'edit_splitter'):
            settings.setValue("specs_edit_splitter", self.edit_splitter.saveState())

    def restore_splitter_states(self, settings):
        st1 = settings.value("specs_main_splitter")
        if st1 and hasattr(self, 'main_splitter'):
            self.main_splitter.restoreState(st1)
        st2 = settings.value("specs_edit_splitter")
        if st2 and hasattr(self, 'edit_splitter'):
            self.edit_splitter.restoreState(st2)

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
            self.btn_save_spec.setProperty("primary", "false")
            self.btn_save_spec.setText("Speichern")
            self.btn_save_spec.style().unpolish(self.btn_save_spec)
            self.btn_save_spec.style().polish(self.btn_save_spec)
            self.on_change()
            self.compile_current_text(sync=True)
            self.trigger_background_project_analysis()
            return True
        except Exception as e:
            QMessageBox.critical(self, "Fehler beim Speichern", f"Konnte Datei nicht speichern: {e}")
            return False
