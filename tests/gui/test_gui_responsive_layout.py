"""Layout regression tests for narrow windows and for the CAN catalog status display.

These assert measurable layout properties at the window widths the product has to
support. They do not replace looking at the running GUI, but they keep the
regressions that were found there from coming back silently.
"""
import json
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tcg.gui.app import MappingStudioWindow
from tcg.gui.profiles import ProjectProfile

WIDTHS = (1024, 1280, 1440)


class ResponsiveLayoutTests(unittest.TestCase):
    """Important actions stay reachable and readable at every supported width."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MappingStudioWindow()
        self.window.show()
        self.addCleanup(self.window.close)
        self.specs = self.window.workspace_specs

    def settle(self, width):
        self.window.resize(width, 800)
        for _ in range(4):
            self.app.processEvents()

    def toolbar_buttons(self):
        return [self.specs.btn_toggle_tree, self.specs.btn_save_spec,
                self.specs.btn_recompile, self.specs.btn_toggle_inspector]

    def test_visible_toolbar_labels_are_never_squeezed(self):
        """A visible button is at least as wide as its caption needs."""
        for width in WIDTHS:
            self.settle(width)
            for button in self.toolbar_buttons():
                if not button.isVisible():
                    continue
                with self.subTest(width=width, button=button.text()):
                    self.assertGreaterEqual(
                        button.width(), button.sizeHint().width(),
                        f'{button.text()!r} is squeezed below its caption at {width}px')

    def test_every_action_stays_reachable(self):
        """An action is either in the row or in the overflow menu -- never lost."""
        for width in WIDTHS:
            self.settle(width)
            toolbar = self.specs.editor_toolbar
            in_menu = {action.text() for action in toolbar._overflow_menu.actions()}
            for button in self.toolbar_buttons():
                with self.subTest(width=width, button=button.text()):
                    self.assertTrue(
                        button.isVisible() or button.text() in in_menu,
                        f'{button.text()!r} is neither shown nor in the overflow menu '
                        f'at {width}px')

    def test_overflow_menu_appears_only_when_needed(self):
        self.settle(1440)
        self.assertFalse(self.specs.editor_toolbar._overflow.isVisible(),
                         'a wide window needs no overflow menu')

    def test_overflow_menu_entries_keep_their_full_caption(self):
        self.settle(1024)
        toolbar = self.specs.editor_toolbar
        captions = {button.text() for button in self.toolbar_buttons()}
        for action in toolbar._overflow_menu.actions():
            with self.subTest(action=action.text()):
                self.assertIn(action.text(), captions)
                self.assertNotIn('…', action.text())

    def test_file_name_is_shortened_but_reachable_as_a_tooltip(self):
        self.specs.refresh_spec_list()
        files = self.specs.file_tree
        for width in WIDTHS:
            self.settle(width)
            label = self.specs.lbl_current_file
            label.setText('tc_08_bms_hv_precharge_sequence.md (bms)')
            self.settle(width)
            with self.subTest(width=width):
                self.assertEqual(label.toolTip(), label.full_text(),
                                 'the untruncated name must stay available as a tooltip')
                self.assertTrue(label.text(), 'the label must not be empty')
                if label.text() != label.full_text():
                    self.assertIn('…', label.text(), 'shortening must be marked')

    def test_file_name_keeps_a_readable_width(self):
        """A button moves into the overflow menu before the file name is crushed."""
        for width in WIDTHS:
            self.settle(width)
            with self.subTest(width=width):
                self.assertGreaterEqual(self.specs.lbl_current_file.width(), 120)

    def test_inspector_tabs_stay_clickable_without_scroll_arrows(self):
        for width in WIDTHS:
            self.settle(width)
            panel = self.specs.right_panel
            bar = panel.tabBar()
            with self.subTest(width=width):
                self.assertFalse(bar.usesScrollButtons(),
                                 'tabs must not hide behind scroll arrows')
                for index in range(panel.count()):
                    self.assertGreater(bar.tabRect(index).width(), 0,
                                       f'tab {panel.tabText(index)!r} is not reachable')

    def test_inspector_tabs_have_captions_and_tooltips(self):
        panel = self.specs.right_panel
        self.assertEqual([panel.tabText(i) for i in range(panel.count())],
                         ['Details', 'Einfügen', 'Python'])
        for index in range(panel.count()):
            with self.subTest(tab=panel.tabText(index)):
                self.assertTrue(panel.tabToolTip(index),
                                'every tab needs an explanatory tooltip')

    def test_toolbar_buttons_carry_tooltips(self):
        for button in self.toolbar_buttons():
            with self.subTest(button=button.text()):
                self.assertTrue(button.toolTip(), f'{button.text()!r} needs a tooltip')


class CanStatusDisplayTests(unittest.TestCase):
    """The CAN catalog status is stated in words; colour only reinforces it."""

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.window = MappingStudioWindow()
        self.addCleanup(self.window.close)

    def profile(self, can_database):
        return ProjectProfile(
            id='probe', name='Probe',
            registry_target='operations.registry:REGISTRY',
            mapping_files=['inputs/operation_mapping.toml'],
            resources_file='inputs/resources.json',
            specs_dir='inputs',
            can_database=can_database,
        )

    def test_loaded_catalog_is_stated_in_words(self):
        self.window.state.set_project_profile(self.profile('inputs/can_signals.json'))
        self.window.refresh_catalog_status()
        text = self.window.lbl_catalog_status.text()
        self.assertIn('Kommunikationskatalog', text)
        self.assertIn('Geladen', text)
        self.assertTrue(self.window.lbl_catalog_status.toolTip())

    def test_project_without_a_catalog_says_so(self):
        self.window.state.set_project_profile(self.profile(''))
        self.window.refresh_catalog_status()
        self.assertIn('Nicht konfiguriert', self.window.lbl_catalog_status.text())

    def test_broken_catalog_is_reported_as_unavailable(self):
        broken = self.root / 'broken.json'
        broken.write_text('{ invalid', encoding='utf-8')
        # A broken catalog is refused on switching, so drive the reload path instead.
        profile = self.profile(str(broken))
        self.window.state.profile_config = profile
        self.window.state._load_catalog()
        self.window.refresh_catalog_status()

        self.assertIn('Nicht verfügbar', self.window.lbl_catalog_status.text())
        self.assertFalse(self.window.state.communication_available)
        self.assertIn('Fehler', self.window.lbl_catalog_status.toolTip())

    def test_status_text_alone_distinguishes_the_three_states(self):
        """Removing all colour must still leave the three states distinguishable."""
        seen = set()
        self.window.state.set_project_profile(self.profile('inputs/can_signals.json'))
        self.window.refresh_catalog_status()
        seen.add(self.window.lbl_catalog_status.text())

        self.window.state.set_project_profile(self.profile(''))
        self.window.refresh_catalog_status()
        seen.add(self.window.lbl_catalog_status.text())

        broken = self.root / 'broken2.json'
        broken.write_text('{ invalid', encoding='utf-8')
        self.window.state.profile_config = self.profile(str(broken))
        self.window.state._load_catalog()
        self.window.refresh_catalog_status()
        seen.add(self.window.lbl_catalog_status.text())

        self.assertEqual(len(seen), 3, f'states are not distinguishable by text: {seen}')


if __name__ == '__main__':
    unittest.main()
