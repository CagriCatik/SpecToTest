"""Main application window for SpecToTest Studio with unified workspaces."""
from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QFont, QKeySequence
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
    QVBoxLayout,
    QWidget,
)

from tcg.gui.models import MappingStudioState
from tcg.gui.profiles import ProjectProfile, get_builtin_profiles
from tcg.gui.styles import DARK_THEME_QSS, LIGHT_THEME_QSS
from tcg.gui.toml_io import load_mapping_file, save_mapping_file
from tcg.gui.view_catalog import CatalogWorkspace
from tcg.gui.view_specifications import SpecificationWorkspace
from tcg.gui.widget_tester import SentenceTesterWidget


class MappingStudioWindow(QMainWindow):
    """SpecToTest Studio Main Window with modular workspaces."""

    def __init__(
        self,
        project_profile: ProjectProfile | None = None,
        registry_target: str = 'operations.registry:REGISTRY',
        mapping_file: str | Path | None = 'inputs/operation_mapping.toml',
        resources_file: str | Path | None = 'inputs/resources.json',
        dark_theme: bool = True,
    ):
        super().__init__()
        self.dark_theme = dark_theme
        self.builtin_profiles = get_builtin_profiles()

        if project_profile is not None:
            self.state = MappingStudioState(project_profile=project_profile)
        else:
            self.state = MappingStudioState(
                registry_target=registry_target,
                mapping_file=mapping_file,
                resources_file=resources_file,
            )

        self.setWindowTitle("SpecToTest Studio")
        self.resize(1200, 800)

        self.setup_ui()
        self.apply_theme()
        self.update_header_stats()

    def setup_ui(self):
        # 1. Menu Bar
        menubar = self.menuBar()

        # File Menu
        file_menu = menubar.addMenu("&Datei")

        act_save = QAction("&Mappings speichern", self)
        act_save.setShortcut(QKeySequence.StandardKey.Save)
        act_save.triggered.connect(self.action_save_file)
        file_menu.addAction(act_save)

        act_save_as = QAction("Mappings speichern &unter...", self)
        act_save_as.setShortcut(QKeySequence("Ctrl+Shift+S"))
        act_save_as.triggered.connect(self.action_save_file_as)
        file_menu.addAction(act_save_as)

        act_open = QAction("Mapping-Datei &öffnen...", self)
        act_open.setShortcut(QKeySequence.StandardKey.Open)
        act_open.triggered.connect(self.action_open_file)
        file_menu.addAction(act_open)

        file_menu.addSeparator()

        act_quit = QAction("&Beenden", self)
        act_quit.setShortcut(QKeySequence.StandardKey.Quit)
        act_quit.triggered.connect(self.close)
        file_menu.addAction(act_quit)

        # Profile Menu
        profile_menu = menubar.addMenu("&Projektprofil")
        for prof in self.builtin_profiles:
            act_prof = QAction(f"{prof.name}", self)
            act_prof.triggered.connect(lambda checked=False, p=prof: self.switch_project_profile(p))
            profile_menu.addAction(act_prof)

        # View Menu
        view_menu = menubar.addMenu("&Ansicht")
        act_theme = QAction("Farbschema wechseln (Dunkel / Hell)", self)
        act_theme.triggered.connect(self.toggle_theme)
        view_menu.addAction(act_theme)

        # 2. Top Summary Bar
        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)
        top_layout.setContentsMargins(14, 8, 14, 8)

        self.lbl_profile_info = QLabel()
        self.lbl_profile_info.setFont(QFont("", 10, QFont.Weight.Bold))
        top_layout.addWidget(self.lbl_profile_info, stretch=2)

        self.lbl_stats = QLabel()
        self.lbl_stats.setTextFormat(Qt.TextFormat.RichText)
        top_layout.addWidget(self.lbl_stats, stretch=2)

        btn_save_quick = QPushButton("Mappings speichern")
        btn_save_quick.setStyleSheet("background-color: #16a34a; color: white; font-weight: bold; padding: 4px 12px; border-radius: 4px;")
        btn_save_quick.clicked.connect(self.action_save_file)
        top_layout.addWidget(btn_save_quick)

        # 3. Main Central Workspaces (Tabs)
        self.tabs = QTabWidget()

        # Workspace 1: Spezifikationen (Priority 1)
        self.workspace_specs = SpecificationWorkspace(self.state, on_change=self.on_state_changed, parent=self)
        self.tabs.addTab(self.workspace_specs, "Spezifikationen")

        # Workspace 2: Operationskatalog (Mappings & Operationen)
        self.workspace_catalog = CatalogWorkspace(self.state, on_change=self.on_state_changed, parent=self)
        self.workspace_catalog.test_sentence_requested.connect(self.switch_to_tester_with_sentence)
        self.tabs.addTab(self.workspace_catalog, "Operationskatalog")

        # Workspace 3: Satzprüfung
        self.workspace_tester = SentenceTesterWidget(self.state, parent=self)
        self.tabs.addTab(self.workspace_tester, "Satzprüfung")

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

    @property
    def view_mappings(self):
        return self.workspace_catalog.view_mappings

    @property
    def view_operations(self):
        return self.workspace_catalog.view_operations

    @property
    def view_tester(self):
        return self.workspace_tester

    def apply_theme(self):
        style = DARK_THEME_QSS if self.dark_theme else LIGHT_THEME_QSS
        self.setStyleSheet(style)
        if hasattr(self, 'workspace_specs') and hasattr(self.workspace_specs, 'highlighter'):
            self.workspace_specs.highlighter.set_dark_theme(self.dark_theme)

    def toggle_theme(self):
        self.dark_theme = not self.dark_theme
        self.apply_theme()

    def update_header_stats(self):
        prof_name = self.state.profile_config.name
        filename = self.state.mapping_file.name if self.state.mapping_file else "Neu.toml"
        dirty_mark = " (ungespeichert)" if self.state.is_dirty else ""

        self.lbl_profile_info.setText(
            f"Profil: <b>{prof_name}</b> &nbsp;|&nbsp; Datei: <code>{filename}{dirty_mark}</code>"
        )

        total_maps = len(self.state.mappings)
        valid_maps = sum(1 for m in self.state.mappings if m.is_valid and not m.has_conflict)
        conflicts = sum(1 for m in self.state.mappings if m.has_conflict)
        total_ops = len(self.state.operations)
        mapped_ops = sum(1 for op in self.state.operations.values() if op.is_mapped)
        unmapped_ops = total_ops - mapped_ops

        conflict_badge = f"<span style='color: #ef4444; font-weight: bold;'>{conflicts} Konflikt(e)</span>" if conflicts else ""
        unmapped_badge = (
            f"<span style='color: #10b981; font-weight: bold;'>0 Lücken</span>"
            if unmapped_ops == 0 else
            f"<span style='color: #ef4444; font-weight: bold;'>{unmapped_ops} ungemappte Lücken</span>"
        )

        stat_parts = [
            f"<b>Mappings:</b> {valid_maps}/{total_maps} gültig",
            f"<b>Operationen:</b> {mapped_ops}/{total_ops} abgedeckt ({unmapped_badge})"
        ]
        if conflict_badge:
            stat_parts.append(conflict_badge)

        self.lbl_stats.setText(" &nbsp;|&nbsp; ".join(stat_parts))
        self.setWindowTitle(f"SpecToTest Studio — {prof_name} [{filename}{dirty_mark}]")

    def on_state_changed(self):
        self.update_header_stats()
        self.workspace_catalog.refresh()
        self.workspace_specs.compile_current_text()
        self.status_bar.showMessage(f"Änderung erfasst ({len(self.state.mappings)} Mappings)", 4000)

    def switch_to_tester_with_sentence(self, sentence: str):
        self.tabs.setCurrentIndex(2)
        self.workspace_tester.set_sentence(sentence)

    def switch_project_profile(self, profile: ProjectProfile, prompt_save: bool = True):
        if prompt_save and self.state.is_dirty:
            reply = QMessageBox.question(
                self,
                "Ungespeicherte Änderungen",
                f"Es gibt ungespeicherte Änderungen im aktuellen Profil '{self.state.profile_config.name}'.\n"
                f"Möchtest du die Änderungen speichern, bevor das Profil gewechselt wird?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if reply == QMessageBox.StandardButton.Save:
                self.action_save_file()
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        self.state.set_project_profile(profile)
        self.workspace_specs.refresh_spec_list()
        self.on_state_changed()
        self.status_bar.showMessage(f"Projektprofil gewechselt zu: {profile.name}", 5000)

    def switch_registry(self, target: str, resources: str | None = None, prompt_save: bool = True):
        """Backwards compatibility helper."""
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
            # Non-blocking status bar confirmation as requested by the reviewer
            self.status_bar.showMessage(f"Gespeichert: {len(self.state.mappings)} Mappings in '{self.state.mapping_file.name}'", 5000)
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
    project_profile: ProjectProfile | None = None,
    registry_target: str = 'operations.registry:REGISTRY',
    mapping_file: str | Path | None = 'inputs/operation_mapping.toml',
    resources_file: str | Path | None = 'inputs/resources.json',
    dark_theme: bool = True,
):
    """Launch the SpecToTest Studio application."""
    app = QApplication.instance()
    if not app:
        app = QApplication(sys.argv)
    
    app.setApplicationName("SpecToTest Studio")
    window = MappingStudioWindow(
        project_profile=project_profile,
        registry_target=registry_target,
        mapping_file=mapping_file,
        resources_file=resources_file,
        dark_theme=dark_theme,
    )
    window.show()
    return app.exec()
