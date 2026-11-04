"""Main application window for SpecToTest Studio with unified workspaces."""
from __future__ import annotations

import os
from pathlib import Path
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QFont, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
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
from tcg.gui.styles import DARK_THEME_QSS, LIGHT_THEME_QSS, get_theme_tokens
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

        self.setWindowTitle("SpecToTest")
        self.setMinimumSize(960, 560)
        self.resize(1200, 800)

        self.setup_ui()
        self.apply_theme()
        self.update_header_stats()
        self.restore_window_state()

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

        act_save_spec = QAction("Aktive Spezifikation speichern", self)
        act_save_spec.setShortcut(QKeySequence("Ctrl+Alt+S"))
        act_save_spec.triggered.connect(lambda: self.workspace_specs.save_current_spec())
        file_menu.addAction(act_save_spec)

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
        top_vlayout = QVBoxLayout(top_widget)
        top_vlayout.setContentsMargins(14, 8, 14, 6)
        top_vlayout.setSpacing(6)

        header_row = QHBoxLayout()
        header_row.setSpacing(10)

        self.lbl_profile_info = QLabel("SpecToTest")
        self.lbl_profile_info.setFont(QFont("", 11, QFont.Weight.Bold))
        header_row.addWidget(self.lbl_profile_info)

        self.btn_toggle_details = QPushButton("Details ▼")
        self.btn_toggle_details.setCheckable(True)
        self.btn_toggle_details.setChecked(False)
        self.btn_toggle_details.clicked.connect(self.toggle_details_panel)
        header_row.addWidget(self.btn_toggle_details)

        header_row.addStretch()

        self.lbl_stats = QLabel()
        self.lbl_stats.setTextFormat(Qt.TextFormat.RichText)
        self.lbl_stats.setMinimumWidth(0)
        header_row.addWidget(self.lbl_stats)

        self.btn_save_quick = QPushButton("Mappings speichern")
        self.btn_save_quick.clicked.connect(self.action_save_file)
        header_row.addWidget(self.btn_save_quick)

        top_vlayout.addLayout(header_row)

        # Collapsible technical details frame (compact 2x2 grid)
        self.details_frame = QFrame()
        self.details_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self.details_frame.setVisible(False)
        det_grid = QGridLayout(self.details_frame)
        det_grid.setContentsMargins(12, 8, 12, 8)
        det_grid.setHorizontalSpacing(24)
        det_grid.setVerticalSpacing(4)

        self.lbl_det_profile = QLabel()
        self.lbl_det_profile.setTextFormat(Qt.TextFormat.RichText)
        det_grid.addWidget(self.lbl_det_profile, 0, 0)

        self.lbl_det_mapping = QLabel()
        self.lbl_det_mapping.setTextFormat(Qt.TextFormat.RichText)
        det_grid.addWidget(self.lbl_det_mapping, 0, 1)

        self.lbl_det_registry = QLabel()
        self.lbl_det_registry.setTextFormat(Qt.TextFormat.RichText)
        det_grid.addWidget(self.lbl_det_registry, 1, 0)

        self.lbl_det_resources = QLabel()
        self.lbl_det_resources.setTextFormat(Qt.TextFormat.RichText)
        det_grid.addWidget(self.lbl_det_resources, 1, 1)

        top_vlayout.addWidget(self.details_frame)

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

        # Permanent indicator for the active project's CAN signal catalog. It always
        # carries a readable sentence; colour only reinforces the text.
        self.lbl_catalog_status = QLabel()
        self.status_bar.addPermanentWidget(self.lbl_catalog_status)
        self.refresh_catalog_status()

    def refresh_catalog_status(self):
        """Show whether the active project's CAN signal catalog is usable."""
        if not hasattr(self, 'lbl_catalog_status'):
            return
        tokens = get_theme_tokens(self.dark_theme)
        text = self.state.catalog_status_text()
        if self.state.catalog_error:
            colour, prefix = tokens['error'], 'Nicht verfügbar'
        elif self.state.catalog is None:
            colour, prefix = tokens['text_muted'], 'Nicht konfiguriert'
        else:
            colour, prefix = tokens['success'], 'Geladen'
        self.lbl_catalog_status.setText(f"Kommunikationskatalog: {prefix}")
        self.lbl_catalog_status.setToolTip(text)
        self.lbl_catalog_status.setStyleSheet(f"color: {colour}; padding: 0 8px;")

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
        if hasattr(self, 'workspace_specs'):
            self.workspace_specs.set_theme(self.dark_theme)
        if hasattr(self, 'workspace_catalog'):
            self.workspace_catalog.set_theme(self.dark_theme)
        if hasattr(self, 'workspace_tester'):
            self.workspace_tester.set_theme(self.dark_theme)
        self.update_header_stats()

    def toggle_theme(self):
        self.dark_theme = not self.dark_theme
        self.apply_theme()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_header_stats()

    def restore_window_state(self):
        settings = QSettings("SpecToTest", "Studio")
        geom = settings.value("geometry")
        if geom:
            self.restoreGeometry(geom)
        if hasattr(self, 'workspace_specs'):
            self.workspace_specs.restore_splitter_states(settings)
        if hasattr(self, 'workspace_catalog'):
            self.workspace_catalog.restore_splitter_states(settings)

    def closeEvent(self, event):
        settings = QSettings("SpecToTest", "Studio")
        settings.setValue("geometry", self.saveGeometry())
        if hasattr(self, 'workspace_specs'):
            self.workspace_specs.save_splitter_states(settings)
        if hasattr(self, 'workspace_catalog'):
            self.workspace_catalog.save_splitter_states(settings)
        super().closeEvent(event)

    def update_header_stats(self):
        filename = self.state.mapping_file.name if self.state.mapping_file else "Neu.toml"
        dirty_mark = " *" if self.state.is_dirty else ""

        # Left: Clean application name without profile/automotive mentions
        self.lbl_profile_info.setText(f"SpecToTest{dirty_mark}")
        self.setWindowTitle(f"SpecToTest{dirty_mark}")

        tokens = get_theme_tokens(self.dark_theme)

        # Collapsible technical details frame
        prof_name = self.state.profile_config.name
        reg_target = self.state.profile_config.registry_target or "-"
        rf = self.state.profile_config.resources_file
        res_file = Path(rf).name if rf else "-"
        self.lbl_det_profile.setText(f"<span style='color: {tokens['text_secondary']};'>Profil:</span> <code>{prof_name}</code>")
        self.lbl_det_mapping.setText(f"<span style='color: {tokens['text_secondary']};'>Mapping-Datei:</span> <code>{filename}</code>")
        self.lbl_det_registry.setText(f"<span style='color: {tokens['text_secondary']};'>Registry:</span> <code>{reg_target}</code>")
        self.lbl_det_resources.setText(f"<span style='color: {tokens['text_secondary']};'>Ressourcen:</span> <code>{res_file}</code>")

        total_maps = len(self.state.mappings)
        valid_maps = sum(1 for m in self.state.mappings if m.is_valid and not m.has_conflict)
        conflicts = sum(1 for m in self.state.mappings if m.has_conflict)
        total_ops = len(self.state.operations)
        mapped_ops = sum(1 for op in self.state.operations.values() if op.is_mapped)
        unmapped_ops = total_ops - mapped_ops

        # Responsive stats text based on window width
        is_compact = self.width() < 1120
        ops_label = "Ops" if is_compact else "Operationen mit Satzmuster"
        stat_parts = [
            f"<b>{valid_maps}/{total_maps}</b> Mappings",
            f"<b>{mapped_ops}/{total_ops}</b> {ops_label}",
        ]
        if unmapped_ops > 0:
            stat_parts.append(f"<span style='color: {tokens['error']};'>({unmapped_ops} Lücken)</span>")
        if conflicts > 0:
            stat_parts.append(f"<span style='color: {tokens['error']}; font-weight: bold;'>{conflicts} Konflikt(e)</span>")

        self.lbl_stats.setText(" | ".join(stat_parts))

        # Update save button styling
        if hasattr(self, 'btn_save_quick'):
            if self.state.is_dirty:
                self.btn_save_quick.setProperty("primary", "true")
                self.btn_save_quick.setText("Mappings speichern *")
            else:
                self.btn_save_quick.setProperty("primary", "false")
                self.btn_save_quick.setText("Mappings speichern")
            self.btn_save_quick.style().unpolish(self.btn_save_quick)
            self.btn_save_quick.style().polish(self.btn_save_quick)

    def toggle_details_panel(self, checked: bool):
        self.details_frame.setVisible(checked)
        self.btn_toggle_details.setText("Details ▲" if checked else "Details ▼")

    def on_state_changed(self):
        self.update_header_stats()
        self.refresh_catalog_status()
        self.workspace_catalog.refresh()
        if hasattr(self, 'workspace_specs'):
            self.workspace_specs.compile_timer.stop()
            self.workspace_specs.analysis_manager.next_doc_revision()
            self.workspace_specs.analysis_manager.next_project_revision()
            self.workspace_specs.compile_current_text(sync=True)
            self.workspace_specs.trigger_background_project_analysis()
        self.status_bar.showMessage(f"Änderung erfasst ({len(self.state.mappings)} Mappings)", 4000)

    def switch_to_tester_with_sentence(self, sentence: str):
        self.tabs.setCurrentIndex(2)
        self.workspace_tester.set_sentence(sentence)

    def switch_project_profile(self, profile: ProjectProfile, prompt_save: bool = True):
        if prompt_save:
            if hasattr(self, 'workspace_specs') and not self.workspace_specs.prompt_save_spec_if_dirty():
                return
            if self.state.is_dirty:
                reply = QMessageBox.question(
                    self,
                    "Ungespeicherte Änderungen",
                    f"Es gibt ungespeicherte Mappings im aktuellen Profil '{self.state.profile_config.name}'.\n"
                    f"Möchtest du die Änderungen speichern, bevor das Profil gewechselt wird?",
                    QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Save,
                )
                if reply == QMessageBox.StandardButton.Save:
                    self.action_save_file()
                elif reply == QMessageBox.StandardButton.Cancel:
                    return

        ok, err = self.state.set_project_profile(profile)
        if not ok:
            QMessageBox.critical(
                self,
                "Fehler beim Profilwechsel",
                f"Projektprofil '{profile.name}' konnte nicht aktiviert werden:\n\n{err}",
            )
            return

        if hasattr(self, 'workspace_specs'):
            self.workspace_specs.compile_timer.stop()
            self.workspace_specs.analysis_manager.next_doc_revision()
            self.workspace_specs.analysis_manager.next_project_revision()
        self.workspace_specs.refresh_spec_list()
        self.on_state_changed()
        self.refresh_catalog_status()
        self.status_bar.showMessage(f"Projektprofil gewechselt zu: {profile.name}", 5000)

    def switch_registry(self, target: str, resources: str | None = None, prompt_save: bool = True):
        """Backwards compatibility helper."""
        if prompt_save:
            if hasattr(self, 'workspace_specs') and not self.workspace_specs.prompt_save_spec_if_dirty():
                return
            if self.state.is_dirty:
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
        if hasattr(self, 'workspace_specs'):
            self.workspace_specs.compile_timer.stop()
            self.workspace_specs.analysis_manager.next_doc_revision()
            self.workspace_specs.analysis_manager.next_project_revision()
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
        success, msg = self.state.save_all_mapping_files()
        if success:
            self.on_state_changed()
            # Non-blocking status bar confirmation as requested by the reviewer
            self.status_bar.showMessage(msg, 5000)
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
            p = Path(path)
            self.state.mapping_file = p
            for m in self.state.mappings:
                m.source_file = str(p)
            self.action_save_file()

    def closeEvent(self, event):
        if hasattr(self, 'workspace_specs'):
            if not self.workspace_specs.prompt_save_spec_if_dirty():
                event.ignore()
                return
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
    
    app.setApplicationName("SpecToTest")
    window = MappingStudioWindow(
        project_profile=project_profile,
        registry_target=registry_target,
        mapping_file=mapping_file,
        resources_file=resources_file,
        dark_theme=dark_theme,
    )
    window.show()
    return app.exec()
