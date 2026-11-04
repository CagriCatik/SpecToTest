"""Main application window for SpecToTest Mapping Studio."""
from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from tcg.gui.models import MappingStudioState
from tcg.gui.styles import DARK_THEME_QSS, LIGHT_THEME_QSS
from tcg.gui.toml_io import load_mapping_file, save_mapping_file
from tcg.gui.view_mappings import MappingsView
from tcg.gui.view_operations import OperationsView
from tcg.gui.widget_tester import SentenceTesterWidget


class MappingStudioWindow(QMainWindow):
    """SpecToTest Mapping Studio Main Window."""

    def __init__(
        self,
        registry_target: str = 'operations.registry:REGISTRY',
        mapping_file: str | Path | None = 'inputs/operation_mapping.toml',
        resources_file: str | Path | None = 'inputs/resources.json',
        dark_theme: bool = True,
    ):
        super().__init__()
        self.dark_theme = dark_theme
        self.state = MappingStudioState(
            registry_target=registry_target,
            mapping_file=mapping_file,
            resources_file=resources_file,
        )

        self.setWindowTitle("SpecToTest — Mapping Studio")
        self.resize(1150, 780)

        self.setup_ui()
        self.apply_theme()
        self.update_header_stats()

    def setup_ui(self):
        # 1. Menu Bar
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&Datei")

        act_new = QAction("&Neu", self)
        act_new.setShortcut(QKeySequence.StandardKey.New)
        act_new.triggered.connect(self.action_new_file)
        file_menu.addAction(act_new)

        act_open = QAction("Mapping-Datei &öffnen...", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.action_open_file)
        file_menu.addAction(act_open)

        act_save = QAction("&Speichern", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self.action_save_file)
        file_menu.addAction(act_save)

        act_save_as = QAction("Speichern &unter...", self)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_as.triggered.connect(self.action_save_file_as)
        file_menu.addAction(act_save_as)

        file_menu.addSeparator()

        act_quit = QAction("&Beenden", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # Registry Menu
        reg_menu = menubar.addMenu("&Registry")

        act_reg_hil = QAction("Automotive HIL (operations.registry:REGISTRY)", self)
        act_reg_hil.triggered.connect(lambda: self.switch_registry('operations.registry:REGISTRY', 'inputs/resources.json'))
        reg_menu.addAction(act_reg_hil)

        act_reg_service = QAction("Software Service (examples.service_pilot.registry:SERVICE_REGISTRY)", self)
        act_reg_service.triggered.connect(lambda: self.switch_registry('examples.service_pilot.registry:SERVICE_REGISTRY', 'examples/service_pilot/inputs/resources.json'))
        reg_menu.addAction(act_reg_service)

        act_reg_ext = QAction("Externe Beispiel-Registry (examples.external_registry:REGISTRY)", self)
        act_reg_ext.triggered.connect(lambda: self.switch_registry('examples.external_registry:REGISTRY', None))
        reg_menu.addAction(act_reg_ext)

        reg_menu.addSeparator()
        act_reg_custom = QAction("Eigene Registry laden...", self)
        act_reg_custom.triggered.connect(self.action_custom_registry)
        reg_menu.addAction(act_reg_custom)

        # View Menu
        view_menu = menubar.addMenu("&Ansicht")
        act_theme = QAction("Farbschema wechseln (Dark / Light)", self)
        act_theme.triggered.connect(self.toggle_theme)
        view_menu.addAction(act_theme)

        # 2. Top Summary Bar
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(14, 8, 14, 8)

        self.lbl_file_info = QLabel()
        self.lbl_file_info.setFont(QFont("sans-serif", 10, QFont.Weight.Bold))
        top_layout.addWidget(self.lbl_file_info, stretch=2)

        self.lbl_stats = QLabel()
        self.lbl_stats.setTextFormat(Qt.TextFormat.RichText)
        top_layout.addWidget(self.lbl_stats, stretch=2)

        btn_save_quick = QPushButton("💾 Speichern")
        btn_save_quick.setStyleSheet("background-color: #198754; color: white; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
        btn_save_quick.clicked.connect(self.action_save_file)
        top_layout.addWidget(btn_save_quick)

        # 3. Main Central Tabs
        self.tabs = QTabWidget()

        # Tab 1: Mappings View (Mappings -> Operations)
        self.view_mappings = MappingsView(self.state, on_change=self.on_state_changed, parent=self)
        self.view_mappings.test_sentence_requested.connect(self.switch_to_tester_with_sentence)
        self.tabs.addTab(self.view_mappings, "📑 Mappings ➔ Operationen")

        # Tab 2: Operations View (Operations -> Mappings - Vice Versa!)
        self.view_operations = OperationsView(self.state, on_change=self.on_state_changed, parent=self)
        self.view_operations.test_sentence_requested.connect(self.switch_to_tester_with_sentence)
        self.tabs.addTab(self.view_operations, "⚙️ Operationen ➔ Mappings (Vice Versa)")

        # Tab 3: Sentence Tester & Playground
        self.view_tester = SentenceTesterWidget(self.state, parent=self)
        self.tabs.addTab(self.view_tester, "🎯 Satzprüfer & Matcher-Playground")

        # Combine in central widget
        central = QWidget()
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(top_widget)
        central_layout.addWidget(self.tabs)
        self.setCentralWidget(central)

        # 4. Status Bar
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Bereit")

    def apply_theme(self):
        style = DARK_THEME_QSS if self.dark_theme else LIGHT_THEME_QSS
        self.setStyleSheet(style)

    def toggle_theme(self):
        self.dark_theme = not self.dark_theme
        self.apply_theme()

    def update_header_stats(self):
        filename = self.state.mapping_file.name if self.state.mapping_file else "Neue_Datei.toml"
        dirty_mark = " • (ungespeichert)" if self.state.is_dirty else ""
        self.lbl_file_info.setText(f"📁 {filename}{dirty_mark} &nbsp;|&nbsp; 🔌 <code>{self.state.registry_target}</code>")

        total_maps = len(self.state.mappings)
        valid_maps = sum(1 for m in self.state.mappings if m.is_valid)
        total_ops = len(self.state.operations)
        mapped_ops = sum(1 for op in self.state.operations.values() if op.is_mapped)
        unmapped_ops = total_ops - mapped_ops

        unmapped_badge = (
            f"<span style='color: #198754; font-weight: bold;'>0 Lücken</span>"
            if unmapped_ops == 0 else
            f"<span style='color: #dc3545; font-weight: bold;'>⚠️ {unmapped_ops} ungemappte Operationen</span>"
        )

        self.lbl_stats.setText(
            f"<b>Mappings:</b> {valid_maps}/{total_maps} gültig &nbsp;|&nbsp; "
            f"<b>Operationen:</b> {mapped_ops}/{total_ops} abgedeckt &nbsp;({unmapped_badge})"
        )
        self.setWindowTitle(f"SpecToTest Mapping Studio — {filename}{dirty_mark}")

    def on_state_changed(self):
        self.update_header_stats()
        self.view_mappings.refresh()
        self.view_operations.refresh()
        self.status_bar.showMessage(f"Änderung erfasst ({len(self.state.mappings)} Mappings)", 4000)

    def switch_to_tester_with_sentence(self, sentence: str):
        self.tabs.setCurrentIndex(2)
        self.view_tester.set_sentence(sentence)

    def switch_registry(self, target: str, resources: str | None = None, prompt_save: bool = True):
        if prompt_save and self.state.is_dirty:
            reply = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                "Es gibt ungespeicherte Änderungen. Möchtest du wirklich die Registry wechseln?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.state.registry_target = target
        if resources:
            self.state.resources_file = Path(resources)
        self.state.reload_all()
        self.on_state_changed()
        self.status_bar.showMessage(f"Registry gewechselt zu: {target}", 5000)

    def action_custom_registry(self):
        text, ok = QInputDialog.getText(
            self,
            "Eigene Registry laden",
            "Gib den Python-Importpfad an (z.B. 'mein_modul:REGISTRY'):",
            text=self.state.registry_target,
        )
        if ok and text.strip():
            self.switch_registry(text.strip())

    def action_new_file(self):
        if self.state.is_dirty:
            reply = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                "Möchtest du vor dem Erstellen einer neuen Datei die aktuellen Änderungen verwerfen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        self.state.mapping_file = None
        self.state.mappings = []
        self.state.recalculate()
        self.state.is_dirty = False
        self.on_state_changed()
        self.status_bar.showMessage("Neues leeres Mapping-Dokument erstellt", 4000)

    def action_open_file(self):
        if self.state.is_dirty:
            reply = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                "Möchtest du vor dem Öffnen die aktuellen Änderungen verwerfen?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        start_dir = str(self.state.mapping_file.parent) if self.state.mapping_file else "."
        path, _ = QFileDialog.getOpenFileName(
            self, "Mapping TOML-Datei öffnen", start_dir, "TOML Files (*.toml);;All Files (*)"
        )
        if path:
            self.state.mapping_file = Path(path)
            raw, err = load_mapping_file(self.state.mapping_file)
            if err:
                QMessageBox.critical(self, "Fehler beim Öffnen", f"Konnte Datei nicht laden:\n\n{err}")
                return
            self.state.set_mappings_from_dicts(raw)
            self.state.is_dirty = False
            self.on_state_changed()
            self.status_bar.showMessage(f"Geladen: {path}", 5000)

    def action_save_file(self):
        if not self.state.mapping_file:
            self.action_save_file_as()
            return

        success, msg = save_mapping_file(self.state.mapping_file, self.state.get_mappings_dicts())
        if success:
            self.state.is_dirty = False
            self.on_state_changed()
            QMessageBox.information(self, "Erfolgreich gespeichert", msg)
        else:
            QMessageBox.critical(self, "Fehler beim Speichern", msg)

    def action_save_file_as(self):
        start_dir = str(self.state.mapping_file.parent) if self.state.mapping_file else "."
        path, _ = QFileDialog.getSaveFileName(
            self, "Mapping TOML-Datei speichern unter...", start_dir, "TOML Files (*.toml);;All Files (*)"
        )
        if path:
            if not path.endswith('.toml'):
                path += '.toml'
            self.state.mapping_file = Path(path)
            self.action_save_file()

    def closeEvent(self, event):
        if self.state.is_dirty:
            reply = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                "Es gibt ungespeicherte Änderungen im Mapping. Möchtest du das Programm wirklich beenden?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        event.accept()


def run_gui(
    registry_target: str = 'operations.registry:REGISTRY',
    mapping_file: str | Path | None = 'inputs/operation_mapping.toml',
    resources_file: str | Path | None = 'inputs/resources.json',
    dark_theme: bool = True,
):
    """Launch the SpecToTest Mapping Studio application."""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    app.setApplicationName("SpecToTest Mapping Studio")
    window = MappingStudioWindow(
        registry_target=registry_target,
        mapping_file=mapping_file,
        resources_file=resources_file,
        dark_theme=dark_theme,
    )
    window.show()
    return app.exec()
