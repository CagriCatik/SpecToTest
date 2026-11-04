"""GUI tests for the communication view inside the existing catalog workspace."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from tcg.gui.app import MappingStudioWindow
from tcg.gui.profiles import ProjectProfile, get_builtin_profiles

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'comm'

MULTI_BUS = [
    {'path': 'tests/fixtures/comm/powertrain_can.json', 'network': 'PowertrainCAN',
     'technology': 'can'},
    # Shares signal names with PowertrainCAN, so it declares its own addressing.
    {'path': 'tests/fixtures/comm/chassis_can.json', 'network': 'ChassisCAN',
     'technology': 'can', 'adapter_naming': 'prefixed'},
    {'path': 'tests/fixtures/comm/body_lin.ldf', 'network': 'BodyLIN'},
    {'path': 'tests/fixtures/comm/services.arxml', 'network': 'BackboneEth'},
]


def profile(communication, bench_type='vector'):
    return ProjectProfile(
        id='multi', name='Multi-Bus',
        registry_target='operations.registry:REGISTRY',
        mapping_files=['inputs/operation_mapping.toml'],
        resources_file='inputs/resources.json',
        specs_dir='inputs',
        bench_config='inputs/demo_bench.json',
        bench_type=bench_type,
        communication=communication,
        base_dir=str(ROOT),
    )


class CommunicationViewTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        self.window = MappingStudioWindow()
        self.addCleanup(self.window.close)
        self.view = self.window.workspace_catalog.view_communication

    def activate(self, communication):
        ok, error = self.window.state.set_project_profile(profile(communication))
        self.assertTrue(ok, error)
        self.view.refresh()
        return ok

    def tree_labels(self, tree):
        labels, stack = [], [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            labels.append(item.text(0))
            stack += [item.child(i) for i in range(item.childCount())]
        return labels

    def find_item(self, reference):
        tree = self.view.resource_tree
        stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            if item.data(0, Qt.ItemDataRole.UserRole) == reference:
                return item
            stack += [item.child(i) for i in range(item.childCount())]
        return None

    # --- the view lives inside the existing navigation ---------------------
    def test_communication_is_a_tab_of_the_catalog_workspace(self):
        tabs = self.window.workspace_catalog.main_tabs
        titles = [tabs.tabText(i) for i in range(tabs.count())]
        self.assertIn('Kommunikation', titles)
        # No extra top-level navigation was introduced.
        main = [self.window.tabs.tabText(i) for i in range(self.window.tabs.count())]
        self.assertEqual(main, ['Spezifikationen', 'Operationskatalog', 'Satzprüfung'])

    def test_builtin_automotive_profile_loads_every_demo_bus(self):
        automotive = next(profile for profile in get_builtin_profiles(ROOT)
                          if profile.id == 'automotive_hil')
        ok, error = self.window.state.set_project_profile(automotive)
        self.assertTrue(ok, error)
        self.view.refresh()

        self.assertEqual(self.view.catalog.networks(),
                         ('BackboneEth', 'BodyComfortLIN', 'PowertrainCAN'))
        labels = self.tree_labels(self.view.resource_tree)
        self.assertIn('PowertrainCAN', labels)
        self.assertIn('BodyComfortLIN', labels)
        self.assertIn('BackboneEth', labels)
        self.assertEqual(
            [name for name, info in self.window.state.operations.items()
             if not info.is_mapped],
            [],
        )

    # --- descriptions, networks and resources ------------------------------
    def test_loaded_descriptions_are_listed_with_their_status(self):
        self.activate(MULTI_BUS)
        rows = [[self.view.sources_tree.topLevelItem(i).text(column) for column in range(4)]
                for i in range(self.view.sources_tree.topLevelItemCount())]
        files = {row[0] for row in rows}
        self.assertEqual(files, {'powertrain_can.json', 'chassis_can.json',
                                 'body_lin.ldf', 'services.arxml'})
        formats = {row[2] for row in rows}
        self.assertEqual(formats, {'can_json', 'ldf', 'arxml'})
        for row in rows:
            self.assertIn('Geladen', row[3])

    def test_networks_and_objects_are_shown(self):
        self.activate(MULTI_BUS)
        labels = self.tree_labels(self.view.resource_tree)
        for network in ('PowertrainCAN', 'ChassisCAN', 'BodyLIN', 'BackboneEth'):
            self.assertIn(network, labels)
        for kind in ('signal', 'frame', 'schedule', 'service', 'method', 'event', 'field'):
            self.assertIn(kind, labels)

    def test_resource_row_shows_qualified_reference_and_origin(self):
        self.activate(MULTI_BUS)
        item = self.find_item('BodyLIN::DoorFrame::DoorState')
        self.assertIsNotNone(item)
        self.assertEqual(item.text(2), 'BodyLIN::DoorFrame::DoorState')
        self.assertEqual(item.text(4), 'body_lin.ldf')
        self.assertIn('Geschlossen', item.text(3))

    def test_selecting_a_resource_shows_origin_and_scaling(self):
        self.activate(MULTI_BUS)
        self.view.resource_tree.setCurrentItem(
            self.find_item('BodyLIN::MirrorFrame::MirrorPosition'))
        detail = self.view.lbl_detail.text()
        self.assertIn('BodyLIN::MirrorFrame::MirrorPosition', detail)
        self.assertIn('body_lin.ldf', detail)
        self.assertIn('physikalisch = roh * 0.5 + -10', detail)

    def test_adapter_address_is_shown(self):
        self.activate(MULTI_BUS)
        self.view.resource_tree.setCurrentItem(
            self.find_item('ChassisCAN::Chassis_01::VehicleSpeed'))
        detail = self.view.lbl_detail.text()
        self.assertIn('Adapteradresse         : ChassisCAN_VehicleSpeed', detail)

    def test_no_address_conflict_is_marked_when_policies_differ(self):
        self.activate(MULTI_BUS)
        for reference in ('PowertrainCAN::Drive_01::VehicleSpeed',
                          'ChassisCAN::Chassis_01::VehicleSpeed'):
            with self.subTest(reference=reference):
                self.assertNotIn('Adresskonflikt', self.find_item(reference).text(0))

    def test_filter_narrows_the_resource_tree(self):
        self.activate(MULTI_BUS)
        self.view.search.setText('MirrorPosition')
        labels = self.tree_labels(self.view.resource_tree)
        self.assertIn('MirrorPosition', labels)
        self.assertNotIn('DoorLockState', labels)

    # --- capabilities ------------------------------------------------------
    def test_bench_capabilities_are_listed_with_readable_status(self):
        self.activate(MULTI_BUS)
        rows = {self.view.capabilities_tree.topLevelItem(i).text(0):
                self.view.capabilities_tree.topLevelItem(i).text(1)
                for i in range(self.view.capabilities_tree.topLevelItemCount())}
        self.assertIn('set_lin_schedule', rows)
        self.assertIn('call_method', rows)
        for status in rows.values():
            self.assertIn(status, ('Verfügbar', 'Nicht verfügbar'))

    def test_missing_capabilities_are_reported_for_compiled_cases(self):
        from tcg.adapters.inbound.text_parser import parse_text_spec
        from tcg.core.compiler import compile_cases
        from tcg.core.mapping import load_mappings, parse_mapping_document

        self.activate(MULTI_BUS)
        toml_text = """
[[mapping]]
id = "MAP_LIN_SCHED"
template = "LIN-Schedule {schedule} aktivieren"
operation = "set_lin_schedule"
parameters = { schedule = "schedule" }
"""
        mappings = load_mappings(parse_mapping_document(toml_text), self.window.state.registry)
        document = ('# TESTFALL: TC_CAP\nNAME: Cap\n\n## Ablauf\n'
                    '10. LIN-Schedule NormalTable aktivieren\n')
        cases = compile_cases(parse_text_spec(document), mappings,
                              self.window.state.profile, 'cap.md')
        # The configured Vector simulation bench offers every capability.
        self.assertEqual(self.view.missing_capabilities_for(cases), ())

    # --- errors ------------------------------------------------------------
    def test_broken_description_is_reported_and_the_catalog_is_dropped(self):
        self.activate(MULTI_BUS)
        self.assertTrue(self.window.state.communication_available)

        with tempfile.TemporaryDirectory() as directory:
            broken = Path(directory) / 'broken.ldf'
            broken.write_text('not a lin description', encoding='utf-8')
            self.window.state.profile_config = profile([{'path': str(broken),
                                                         'network': 'X'}])
            self.window.state._load_catalog()
            self.view.refresh()
            self.window.refresh_catalog_status()

        self.assertFalse(self.window.state.communication_available)
        self.assertIsNone(self.view.catalog)
        self.assertIn('nicht verfügbar', self.view.lbl_status.text())
        self.assertIn('broken.ldf', self.view.lbl_status.text())
        self.assertEqual(self.view.resource_tree.topLevelItemCount(), 0)
        self.assertIn('Nicht verfügbar', self.window.lbl_catalog_status.text())

    def test_switching_projects_replaces_the_shown_resources(self):
        self.activate(MULTI_BUS)
        self.assertIsNotNone(self.find_item('BodyLIN::DoorFrame::DoorState'))

        self.activate([MULTI_BUS[0]])
        self.assertIsNone(self.find_item('BodyLIN::DoorFrame::DoorState'))
        self.assertEqual(self.view.catalog.networks(), ('PowertrainCAN',))
        self.assertIn('1 Netzwerk', self.view.lbl_status.text())

    def test_project_without_descriptions_says_so(self):
        ok, error = self.window.state.set_project_profile(profile([]))
        self.assertTrue(ok, error)
        self.view.refresh()
        self.assertIn('keine Kommunikationsbeschreibung', self.view.lbl_status.text())
        self.assertEqual(self.view.resource_tree.topLevelItemCount(), 0)


if __name__ == '__main__':
    unittest.main()
