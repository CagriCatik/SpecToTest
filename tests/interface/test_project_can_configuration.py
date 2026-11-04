"""Project-configuration boundary tests: the active project owns its CAN signal catalog.

These exercise the inbound configuration adapters -- the project profile used by the
GUI and the CLI driver in generate.py -- rather than the converter internals.
"""

from decimal import Decimal
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tcg.core.model import SpecError
from tcg.gui.models import MappingStudioState
from tcg.gui.profiles import ProjectProfile, get_builtin_profiles

ROOT = Path(__file__).resolve().parents[2]

MAPPING_TOML = """
[[mapping]]
id = "MAP_CAN_SET"
template = "CAN-Signal {signal} auf {wert} setzen"
operation = "set_can_signal"
parameters = { signal = "signal", wert = "value" }
"""

SPEC = """# TESTFALL: TC_PROJ
NAME: Project catalog
## Action
10. CAN-Signal DoorContactStatus auf Geschlossen setzen
"""


def database(value_for_geschlossen):
    return {
        'database': 'ProjectDb',
        'messages': {'Body_01': {'id': '0x200', 'dlc': 8}},
        'signals': {
            'DoorContactStatus': {
                'message': 'Body_01', 'start_bit': 0, 'length': 4,
                'values': {str(value_for_geschlossen): 'Geschlossen',
                           str(value_for_geschlossen + 1): 'Offen'},
            },
        },
    }


class ProjectFixture(unittest.TestCase):
    """Writes two self-contained project directories into a temporary workspace."""

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        resources = (ROOT / 'inputs' / 'resources.json').read_text(encoding='utf-8')

        self.projects = {}
        for name, raw_value in (('alpha', 0), ('beta', 5)):
            directory = self.root / name
            (directory / 'specs').mkdir(parents=True)
            (directory / 'mapping.toml').write_text(MAPPING_TOML, encoding='utf-8')
            (directory / 'resources.json').write_text(resources, encoding='utf-8')
            (directory / 'can_signals.json').write_text(
                json.dumps(database(raw_value)), encoding='utf-8')
            (directory / 'specs' / 'spec.md').write_text(SPEC, encoding='utf-8')
            self.projects[name] = directory

    def profile(self, name, can_database='can_signals.json'):
        """A project profile using paths relative to its own configuration directory."""
        return ProjectProfile(
            id=name,
            name=name,
            registry_target='operations.registry:REGISTRY',
            mapping_files=[str(self.projects[name] / 'mapping.toml')],
            resources_file=str(self.projects[name] / 'resources.json'),
            specs_dir=str(self.projects[name] / 'specs'),
            can_database=can_database,
            base_dir=str(self.projects[name]),
        )


class TestRelativePathResolution(ProjectFixture):
    def test_relative_can_database_resolves_against_the_project_configuration(self):
        profile = self.profile('alpha')
        self.assertEqual(profile.can_database_path(),
                         self.projects['alpha'] / 'can_signals.json')

    def test_absolute_can_database_is_kept(self):
        absolute = self.projects['beta'] / 'can_signals.json'
        profile = self.profile('alpha', can_database=str(absolute))
        self.assertEqual(profile.can_database_path(), absolute)

    def test_a_project_without_can_database_declares_none(self):
        self.assertIsNone(self.profile('alpha', can_database='').can_database_path())

    def test_project_configuration_file_sets_the_base_directory(self):
        config = self.projects['alpha'] / 'project.json'
        config.write_text(json.dumps({
            'id': 'alpha', 'name': 'Alpha',
            'registry_target': 'operations.registry:REGISTRY',
            'mapping_files': ['mapping.toml'], 'resources_file': 'resources.json',
            'specs_dir': 'specs', 'can_database': 'can_signals.json',
        }), encoding='utf-8')
        loaded = ProjectProfile.load(config)
        self.assertEqual(loaded.base_dir, str(self.projects['alpha']))
        self.assertEqual(loaded.can_database_path(),
                         self.projects['alpha'] / 'can_signals.json')

    def test_broken_project_configuration_file_fails_visibly(self):
        config = self.projects['alpha'] / 'broken.json'
        config.write_text('{ not json', encoding='utf-8')
        with self.assertRaises(SpecError) as caught:
            ProjectProfile.load(config)
        self.assertIn('broken.json', str(caught.exception))

    def test_builtin_demo_project_references_all_communication_descriptions(self):
        demo = next(p for p in get_builtin_profiles() if p.id == 'automotive_hil')
        self.assertEqual(demo.can_database, '')
        self.assertEqual(
            [(entry['network'], entry['path']) for entry in demo.communication],
            [
                ('PowertrainCAN', 'inputs/can_signals.json'),
                ('BodyComfortLIN', 'inputs/lin_signals.json'),
                ('BackboneEth', 'tools/vehicle_services.arxml'),
            ])
        self.assertEqual(demo.mapping_files, [
            'inputs/operation_mapping.toml',
            'inputs/multibus_mapping.toml',
        ])
        self.assertTrue(all(demo.resolve_path(entry['path']).is_file()
                            for entry in demo.communication))

    def test_builtin_software_project_needs_no_can_database(self):
        service = next(p for p in get_builtin_profiles() if p.id == 'service_pilot')
        self.assertEqual(service.can_database, '')
        self.assertIsNone(service.can_database_path())


class TestProjectSwitching(ProjectFixture):
    """Switching projects must not carry the previous project's catalog over."""

    def value_of(self, state):
        contract = state.registry['set_can_signal']
        catalog = contract.parameter('value').type.catalog
        return catalog.resolve_state('DoorContactStatus', 'Geschlossen')

    def test_switching_projects_replaces_the_catalog(self):
        state = MappingStudioState(project_profile=self.profile('alpha'))
        self.assertEqual(self.value_of(state), Decimal('0'))
        self.assertTrue(state.communication_available)

        ok, error = state.set_project_profile(self.profile('beta'))
        self.assertTrue(ok, error)
        self.assertEqual(self.value_of(state), Decimal('5'))

        ok, error = state.set_project_profile(self.profile('alpha'))
        self.assertTrue(ok, error)
        self.assertEqual(self.value_of(state), Decimal('0'))

    def test_switching_to_a_project_without_a_database_drops_the_catalog(self):
        state = MappingStudioState(project_profile=self.profile('alpha'))
        self.assertEqual(self.value_of(state), Decimal('0'))

        ok, error = state.set_project_profile(self.profile('beta', can_database=''))
        self.assertTrue(ok, error)
        self.assertFalse(state.communication_available)
        self.assertIsNone(self.value_of(state))
        self.assertIn('nicht konfiguriert', state.catalog_status_text())

    def test_broken_catalog_is_rejected_and_leaves_state_untouched(self):
        state = MappingStudioState(project_profile=self.profile('alpha'))
        broken = self.projects['beta'] / 'broken_db.json'
        broken.write_text('{ invalid json', encoding='utf-8')

        ok, error = state.set_project_profile(self.profile('beta', can_database=str(broken)))
        self.assertFalse(ok)
        self.assertIn('Kommunikationsbeschreibung', error)
        self.assertIn('broken_db.json', error)
        # The previous project stays fully active; nothing was half-applied.
        self.assertEqual(state.profile_config.id, 'alpha')
        self.assertEqual(self.value_of(state), Decimal('0'))

    def test_missing_catalog_file_is_rejected(self):
        state = MappingStudioState(project_profile=self.profile('alpha'))
        ok, error = state.set_project_profile(
            self.profile('beta', can_database='does_not_exist.json'))
        self.assertFalse(ok)
        self.assertIn('does_not_exist.json', error)
        self.assertEqual(state.profile_config.id, 'alpha')

    def test_reload_reflects_a_removed_state(self):
        """Editing the catalog and reloading must drop states that no longer exist."""
        profile = self.profile('alpha')
        state = MappingStudioState(project_profile=profile)
        self.assertEqual(self.value_of(state), Decimal('0'))

        renamed = {
            'database': 'Renamed',
            'messages': {'Body_01': {'id': '0x200', 'dlc': 8}},
            'signals': {'DoorContactStatus': {
                'message': 'Body_01', 'start_bit': 0, 'length': 4,
                'values': {'0': 'Zu', '1': 'Auf'}}},
        }
        (self.projects['alpha'] / 'can_signals.json').write_text(
            json.dumps(renamed), encoding='utf-8')
        state.reload_all()

        self.assertIsNone(self.value_of(state), 'removed state must not survive a reload')
        contract_type = state.registry['set_can_signal'].parameter('value').type
        self.assertEqual(contract_type.catalog.resolve_state('DoorContactStatus', 'Zu'),
                         Decimal('0'))

    def test_broken_catalog_on_reload_marks_can_unavailable(self):
        """A reload must not keep working with the previously loaded catalog."""
        state = MappingStudioState(project_profile=self.profile('alpha'))
        self.assertTrue(state.communication_available)

        (self.projects['alpha'] / 'can_signals.json').write_text('{ broken', encoding='utf-8')
        state.reload_all()

        self.assertFalse(state.communication_available)
        self.assertIsNotNone(state.catalog_error)
        self.assertIsNone(self.value_of(state))
        status = state.catalog_status_text()
        self.assertIn('Fehler', status)
        self.assertNotEqual(status.strip(), '')


class TestCliConfiguration(unittest.TestCase):
    """The CLI reports configuration errors with a failing exit status."""

    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.addCleanup(self.workspace.cleanup)
        self.root = Path(self.workspace.name)
        self.spec = self.root / 'spec.md'
        self.spec.write_text(
            '# TESTFALL: TC_CLI\n'
            'NAME: CLI\n'
            '## Action\n'
            '10. CAN-Signal InterlockStatus auf Geschlossen setzen\n',
            encoding='utf-8')
        self.output = self.root / 'out' / 'test_cli.py'

    def run_cli(self, *extra):
        command = [sys.executable, 'generate.py',
                   '--spec', str(self.spec),
                   '--mapping', 'inputs/operation_mapping.toml',
                   '--resources', 'inputs/resources.json',
                   '--output', str(self.output),
                   '--log-dir', str(self.root / 'logs'), *extra]
        return subprocess.run(command, capture_output=True, text=True, cwd=ROOT)

    def test_symbolic_state_without_a_catalog_fails(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 2)
        self.assertIn('Geschlossen', result.stderr)
        self.assertIn('can_database', result.stderr)
        self.assertFalse(self.output.exists())

    def test_corrupt_catalog_fails_with_the_file_named(self):
        broken = self.root / 'broken_db.json'
        broken.write_text('{ invalid', encoding='utf-8')
        result = self.run_cli('--can-database', str(broken))
        self.assertEqual(result.returncode, 2)
        self.assertIn('broken_db.json', result.stderr)
        self.assertFalse(self.output.exists())

    def test_missing_catalog_fails_with_the_file_named(self):
        result = self.run_cli('--can-database', str(self.root / 'absent.json'))
        self.assertEqual(result.returncode, 2)
        self.assertIn('absent.json', result.stderr)

    def test_configured_catalog_compiles_the_catalogued_raw_value(self):
        result = self.run_cli('--can-database', 'inputs/can_signals.json')
        self.assertEqual(result.returncode, 0, result.stderr)
        source = self.output.read_text(encoding='utf-8')
        # InterlockStatus declares Geschlossen=1 (opposite to DoorContactStatus).
        self.assertIn("signal='InterlockStatus', value=Decimal('1')", source)


if __name__ == '__main__':
    unittest.main()
