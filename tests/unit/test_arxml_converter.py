"""Unit tests for the AUTOSAR ARXML <-> JSON service converter and validator."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tcg.comm.importers import arxml as arxml_importer
from tcg.comm.model import ObjectKind
from tcg.core.model import SpecError
from tools.arxml_to_json import (
    arxml_to_dict,
    convert_file,
    dict_to_arxml,
    validate_service_database,
)

ROOT = Path(__file__).resolve().parents[2]
ARXML_PATH = ROOT / 'tools' / 'vehicle_services.arxml'


def minimal_database(**overrides):
    data = {
        'database': 'Test',
        'protocol': 'Ethernet',
        'autosar_version': '4.x',
        'services': {
            'DoorService': {
                'service_id': 4660,
                'someip': True,
                'methods': {'Open': {'id': 1}},
                'events': {'Changed': {'id': 0x8001, 'data_type': 'uint8'}},
                'fields': {'State': {'data_type': 'uint8'}},
            },
        },
    }
    data.update(overrides)
    return data


class ArxmlParsingTests(unittest.TestCase):
    """The shipped demo description parses into the expected structure."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(ARXML_PATH.exists(), f'ARXML demo file missing: {ARXML_PATH}')
        cls.data = arxml_to_dict(ARXML_PATH.read_text(encoding='utf-8'), ARXML_PATH.name)

    def test_header_fields(self):
        self.assertEqual(self.data['protocol'], 'Ethernet')
        self.assertEqual(self.data['autosar_version'], '4.x')

    def test_services_are_found(self):
        self.assertEqual(sorted(self.data['services']),
                         ['ChargingService', 'DiagnosticService', 'DoorService'])

    def test_methods_events_and_fields(self):
        door = self.data['services']['DoorService']
        self.assertEqual(sorted(door['methods']),
                         ['GetDoorState', 'LockAllDoors', 'UnlockAllDoors'])
        self.assertEqual(sorted(door['events']),
                         ['DoorStateChanged', 'LockStateChanged'])
        self.assertEqual(sorted(door['fields']), ['CentralLockState'])

    def test_someip_ids_are_attached(self):
        door = self.data['services']['DoorService']
        self.assertEqual(door['service_id'], 4660)
        self.assertTrue(door['someip'])
        self.assertEqual(door['methods']['LockAllDoors']['id'], 1)
        self.assertEqual(door['events']['DoorStateChanged']['id'], 32769)

    def test_service_without_deployment_has_no_ids(self):
        """SOME/IP is not assumed: an interface may have no deployment at all."""
        diagnostic = self.data['services']['DiagnosticService']
        self.assertIsNone(diagnostic['service_id'])
        self.assertFalse(diagnostic['someip'])
        self.assertEqual(diagnostic['methods']['ReadFaultMemory'], {})

    def test_method_without_deployment_entry_has_no_id(self):
        charging = self.data['services']['ChargingService']
        self.assertEqual(charging['methods']['StartCharging']['id'], 1)
        self.assertNotIn('id', charging['methods']['SetChargeLimit'])

    def test_data_types_are_carried(self):
        door = self.data['services']['DoorService']
        self.assertEqual(door['events']['DoorStateChanged']['data_type'], 'uint8')
        self.assertEqual(door['fields']['CentralLockState']['data_type'], 'uint8')


class ArxmlRoundTripTests(unittest.TestCase):
    """ARXML -> JSON -> ARXML keeps the described services intact."""

    def test_round_trip_preserves_resources(self):
        data = arxml_to_dict(ARXML_PATH.read_text(encoding='utf-8'), ARXML_PATH.name)
        regenerated = dict_to_arxml(data)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'roundtrip.arxml'
            path.write_text(regenerated, encoding='utf-8')

            def snapshot(source):
                return {
                    (resource.container, resource.name, resource.kind):
                        (dict(resource.attributes).get('id'),
                         dict(resource.attributes).get('data_type'),
                         dict(resource.attributes).get('service_id'))
                    for resource in arxml_importer.load(source, network='N')
                }

            self.assertEqual(snapshot(ARXML_PATH), snapshot(path))

    def test_round_trip_json_is_stable(self):
        first = arxml_to_dict(ARXML_PATH.read_text(encoding='utf-8'), ARXML_PATH.name)
        second = arxml_to_dict(dict_to_arxml(first), ARXML_PATH.name)
        self.assertEqual(first['services'], second['services'])


class ServiceValidationTests(unittest.TestCase):
    """The validator reports real AUTOSAR / SOME/IP constraint violations."""

    def test_demo_database_is_clean(self):
        data = arxml_to_dict(ARXML_PATH.read_text(encoding='utf-8'), ARXML_PATH.name)
        self.assertEqual(validate_service_database(data), [])

    def test_minimal_database_is_clean(self):
        self.assertEqual(validate_service_database(minimal_database()), [])

    def test_service_id_out_of_range(self):
        data = minimal_database()
        data['services']['DoorService']['service_id'] = 0x10000
        issues = validate_service_database(data)
        self.assertTrue(any('outside' in issue for issue in issues), issues)

    def test_duplicate_service_id(self):
        data = minimal_database()
        data['services']['Other'] = {'service_id': 4660, 'someip': True,
                                     'methods': {'X': {}}, 'events': {}, 'fields': {}}
        issues = validate_service_database(data)
        self.assertTrue(any('reuses service id' in issue for issue in issues), issues)

    def test_method_id_out_of_range(self):
        data = minimal_database()
        data['services']['DoorService']['methods']['Open']['id'] = 0x8001
        issues = validate_service_database(data)
        self.assertTrue(any('0x0000..0x7FFF' in issue for issue in issues), issues)

    def test_event_id_out_of_range(self):
        data = minimal_database()
        data['services']['DoorService']['events']['Changed']['id'] = 1
        issues = validate_service_database(data)
        self.assertTrue(any('0x8000..0xFFFF' in issue for issue in issues), issues)

    def test_duplicate_method_id(self):
        data = minimal_database()
        data['services']['DoorService']['methods']['Close'] = {'id': 1}
        issues = validate_service_database(data)
        self.assertTrue(any('reuses id' in issue for issue in issues), issues)

    def test_someip_without_service_id(self):
        data = minimal_database()
        data['services']['DoorService']['service_id'] = None
        issues = validate_service_database(data)
        self.assertTrue(any('marked as SOME/IP but has no' in issue
                            for issue in issues), issues)

    def test_member_id_without_deployment(self):
        data = minimal_database()
        data['services']['DoorService']['service_id'] = None
        data['services']['DoorService']['someip'] = False
        issues = validate_service_database(data)
        self.assertTrue(any('no SOME/IP deployment' in issue for issue in issues), issues)

    def test_empty_service(self):
        data = minimal_database()
        data['services']['Empty'] = {'methods': {}, 'events': {}, 'fields': {}}
        issues = validate_service_database(data)
        self.assertTrue(any('no methods, events or fields' in issue
                            for issue in issues), issues)

    def test_invalid_short_name(self):
        data = minimal_database()
        data['services']['Not A Name'] = {'methods': {'X': {}}, 'events': {},
                                          'fields': {}}
        issues = validate_service_database(data)
        self.assertTrue(any('SHORT-NAME' in issue for issue in issues), issues)

    def test_invalid_member_short_name(self):
        data = minimal_database()
        data['services']['DoorService']['methods']['bad name'] = {}
        issues = validate_service_database(data)
        self.assertTrue(any('SHORT-NAME' in issue for issue in issues), issues)


class ArxmlErrorHandlingTests(unittest.TestCase):
    """Unsupported or malformed input fails visibly, never silently."""

    def test_malformed_xml_is_refused(self):
        with self.assertRaises(SpecError) as caught:
            arxml_to_dict('<AUTOSAR><UNCLOSED>', 'bad.arxml')
        self.assertIn('ungültiges XML', str(caught.exception))

    def test_wrong_root_element_is_refused(self):
        with self.assertRaises(SpecError) as caught:
            arxml_to_dict('<?xml version="1.0"?><NOTAUTOSAR/>', 'other.arxml')
        self.assertIn('AUTOSAR', str(caught.exception))

    def test_entity_declarations_are_refused(self):
        text = ('<?xml version="1.0"?><!DOCTYPE AUTOSAR [<!ENTITY a "b">]>'
                '<AUTOSAR></AUTOSAR>')
        with self.assertRaises(SpecError) as caught:
            arxml_to_dict(text, 'evil.arxml')
        self.assertIn('ENTITY', str(caught.exception))

    def test_system_description_is_refused_with_an_explanation(self):
        text = ('<?xml version="1.0"?><AUTOSAR xmlns="http://autosar.org/schema/r4.0">'
                '<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>Sys</SHORT-NAME><ELEMENTS>'
                '<CAN-CLUSTER><SHORT-NAME>CAN1</SHORT-NAME></CAN-CLUSTER>'
                '</ELEMENTS></AR-PACKAGE></AR-PACKAGES></AUTOSAR>')
        with self.assertRaises(SpecError) as caught:
            arxml_to_dict(text, 'system.arxml')
        message = str(caught.exception)
        self.assertIn('SERVICE-INTERFACE', message)
        self.assertIn('nicht unterstützt', message)

    def test_unsupported_interface_child_is_named(self):
        text = ('<?xml version="1.0"?><AUTOSAR xmlns="http://autosar.org/schema/r4.0">'
                '<SERVICE-INTERFACE><SHORT-NAME>S</SHORT-NAME>'
                '<TRIGGERS><TRIGGER><SHORT-NAME>T</SHORT-NAME></TRIGGER></TRIGGERS>'
                '</SERVICE-INTERFACE></AUTOSAR>')
        with self.assertRaises(SpecError) as caught:
            arxml_to_dict(text, 'iface.arxml')
        self.assertIn('TRIGGERS', str(caught.exception))


class ArxmlImporterIntegrationTests(unittest.TestCase):
    """The shipped demo file is usable as a project description."""

    def test_importer_reads_the_demo_file(self):
        resources = arxml_importer.load(ARXML_PATH, network='BackboneEth')
        kinds = {resource.kind for resource in resources}
        self.assertEqual(kinds, {ObjectKind.SERVICE, ObjectKind.METHOD,
                                 ObjectKind.EVENT, ObjectKind.FIELD})
        by_reference = {resource.qualified_name: resource for resource in resources}
        self.assertIn('BackboneEth::DoorService::LockAllDoors', by_reference)
        self.assertEqual(
            by_reference['BackboneEth::DoorService::LockAllDoors'].attributes['id'], '1')

    def test_services_are_not_modelled_as_signals(self):
        resources = arxml_importer.load(ARXML_PATH, network='BackboneEth')
        for resource in resources:
            with self.subTest(resource=resource.name):
                self.assertIsNone(resource.encoding)


class ArxmlCliTests(unittest.TestCase):
    """The converter runs as a standalone command line tool."""

    def run_cli(self, *args):
        return subprocess.run([sys.executable, 'tools/arxml_to_json.py', *args],
                              capture_output=True, text=True, cwd=ROOT)

    def test_convert_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'services.json'
            result = self.run_cli(str(ARXML_PATH), '-o', str(output), '--check')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Validation: no issues found', result.stdout)

            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(len(data['services']), 3)
            self.assertEqual(data['autosar_version'], '4.x')

    def test_validation_failure_reports_a_failing_status(self):
        broken = minimal_database()
        broken['services']['DoorService']['methods']['Open']['id'] = 0x9000
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'broken.json'
            source.write_text(json.dumps(broken), encoding='utf-8')
            result = self.run_cli(str(source), '--check')
            self.assertEqual(result.returncode, 1)
            self.assertIn('0x0000..0x7FFF', result.stderr)

    def test_missing_input_file(self):
        result = self.run_cli('/nowhere/missing.arxml')
        self.assertEqual(result.returncode, 2)
        self.assertIn('not found', result.stderr)

    def test_unsupported_arxml_reports_a_failing_status(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'system.arxml'
            source.write_text(
                '<?xml version="1.0"?><AUTOSAR xmlns="http://autosar.org/schema/r4.0">'
                '</AUTOSAR>', encoding='utf-8')
            result = self.run_cli(str(source))
            self.assertEqual(result.returncode, 2)
            self.assertIn('SERVICE-INTERFACE', result.stderr)

    def test_json_to_arxml_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / 'services.json'
            arxml_path = Path(directory) / 'out.arxml'
            convert_file(ARXML_PATH, json_path)
            result = self.run_cli(str(json_path), '-o', str(arxml_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('<SERVICE-INTERFACE>',
                          arxml_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
