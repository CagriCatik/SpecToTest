"""Unit tests for the LIN Description File (.ldf) <-> JSON converter and validator."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tcg.comm.importers import ldf as ldf_importer
from tcg.comm.model import ObjectKind
from tcg.core.model import SpecError
from tools.ldf_to_json import (
    convert_file,
    dict_to_ldf,
    ldf_to_dict,
    validate_lin_database,
)

ROOT = Path(__file__).resolve().parents[2]
LDF_PATH = ROOT / 'tools' / 'body_comfort.ldf'


def minimal_database(**overrides):
    data = {
        'database': 'Test',
        'protocol_version': '2.1',
        'speed_kbps': 19.2,
        'nodes': {'master': 'M', 'slaves': ['S']},
        'frames': {
            'F1': {'id': '0x20', 'publisher': 'S', 'length': 1,
                   'layout': {'Sig1': 0, 'Sig2': 4}},
        },
        'signals': {
            'Sig1': {'frame': 'F1', 'start_bit': 0, 'size': 4, 'init': 0,
                     'publisher': 'S', 'subscribers': ['M'], 'unit': '',
                     'factor': 1, 'offset': 0},
            'Sig2': {'frame': 'F1', 'start_bit': 4, 'size': 4, 'init': 0,
                     'publisher': 'S', 'subscribers': ['M'], 'unit': '',
                     'factor': 1, 'offset': 0},
        },
        'schedules': {'T1': [{'frame': 'F1', 'delay_ms': 10}]},
    }
    data.update(overrides)
    return data


class LdfParsingTests(unittest.TestCase):
    """The shipped demo description parses into the expected structure."""

    @classmethod
    def setUpClass(cls):
        cls.assertTrue(LDF_PATH.exists(), f'LDF demo file missing: {LDF_PATH}')
        cls.data = ldf_to_dict(LDF_PATH.read_text(encoding='utf-8'), LDF_PATH.name)

    def test_header_fields(self):
        self.assertEqual(self.data['protocol'], 'LIN')
        self.assertEqual(self.data['protocol_version'], '2.1')
        self.assertEqual(self.data['speed_kbps'], 19.2)

    def test_nodes(self):
        self.assertEqual(self.data['nodes']['master'], 'BodyMaster')
        self.assertIn('MirrorModule', self.data['nodes']['slaves'])
        self.assertEqual(len(self.data['nodes']['slaves']), 5)

    def test_frames_and_layout(self):
        self.assertEqual(len(self.data['frames']), 6)
        door = self.data['frames']['LIN_Door_01']
        self.assertEqual(door['id'], '0x20')
        self.assertEqual(door['publisher'], 'DoorModuleFL')
        self.assertEqual(door['length'], 3)
        self.assertEqual(door['layout'],
                         {'DoorContactFL': 0, 'WindowPositionFL': 8, 'ErrDoorFL': 16})

    def test_logical_values_become_states(self):
        signal = self.data['signals']['DoorContactFL']
        self.assertEqual(signal['values'],
                         {'0': 'Geschlossen', '1': 'Offen', '2': 'Fehler'})
        self.assertEqual(signal['encoding_type'], 'DoorContactEncoding')

    def test_physical_values_become_scaling(self):
        signal = self.data['signals']['MirrorPositionH']
        self.assertEqual(signal['unit'], 'deg')
        self.assertEqual(signal['factor'], 0.5)
        self.assertEqual(signal['offset'], -64)
        self.assertEqual(signal['min'], 0)
        self.assertEqual(signal['max'], 255)

    def test_state_names_with_spaces_are_preserved(self):
        self.assertEqual(self.data['signals']['SeatHeaterLevel']['values']['3'],
                         'Stufe 3')

    def test_schedules_keep_their_delays(self):
        normal = self.data['schedules']['NormalTable']
        self.assertEqual(len(normal), 6)
        self.assertEqual(normal[0], {'frame': 'LIN_Master_01', 'delay_ms': 10})
        self.assertEqual(self.data['schedules']['DiagnosticTable'],
                         [{'frame': 'LIN_Sensor_01', 'delay_ms': 100}])

    def test_one_encoding_shared_by_two_signals(self):
        self.assertEqual(self.data['signals']['DoorContactFL']['encoding_type'],
                         self.data['signals']['DoorContactFR']['encoding_type'])


class LdfRoundTripTests(unittest.TestCase):
    """LDF -> JSON -> LDF keeps the described network intact."""

    def test_round_trip_preserves_resources(self):
        data = ldf_to_dict(LDF_PATH.read_text(encoding='utf-8'), LDF_PATH.name)
        regenerated = dict_to_ldf(data)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'roundtrip.ldf'
            path.write_text(regenerated, encoding='utf-8')

            def snapshot(source):
                return {
                    resource.name: (
                        resource.kind,
                        getattr(resource.encoding, 'declared_states', ()),
                        getattr(resource.encoding, 'factor', None),
                        getattr(resource.encoding, 'offset', None),
                        getattr(resource.encoding, 'unit', None),
                    )
                    for resource in ldf_importer.load(source, network='N')
                }

            self.assertEqual(snapshot(LDF_PATH), snapshot(path))

    def test_round_trip_json_is_stable(self):
        first = ldf_to_dict(LDF_PATH.read_text(encoding='utf-8'), LDF_PATH.name)
        second = ldf_to_dict(dict_to_ldf(first), LDF_PATH.name)
        for name, signal in first['signals'].items():
            with self.subTest(signal=name):
                self.assertEqual(signal.get('values'),
                                 second['signals'][name].get('values'))
                self.assertEqual(signal['factor'], second['signals'][name]['factor'])
                self.assertEqual(signal['offset'], second['signals'][name]['offset'])


class LinValidationTests(unittest.TestCase):
    """The validator reports real LIN constraint violations."""

    def test_demo_database_is_clean(self):
        data = ldf_to_dict(LDF_PATH.read_text(encoding='utf-8'), LDF_PATH.name)
        self.assertEqual(validate_lin_database(data), [])

    def test_minimal_database_is_clean(self):
        self.assertEqual(validate_lin_database(minimal_database()), [])

    def test_identifier_outside_lin_range(self):
        data = minimal_database()
        data['frames']['F1']['id'] = '0x7F'
        issues = validate_lin_database(data)
        self.assertTrue(any('0x00..0x3F' in issue for issue in issues), issues)

    def test_duplicate_frame_identifier(self):
        data = minimal_database()
        data['frames']['F2'] = {'id': '0x20', 'publisher': 'S', 'length': 1,
                                'layout': {}}
        issues = validate_lin_database(data)
        self.assertTrue(any('reuses id' in issue for issue in issues), issues)

    def test_signal_exceeds_frame_capacity(self):
        data = minimal_database()
        data['signals']['Sig2']['size'] = 8  # 4 + 8 > 8 bits
        issues = validate_lin_database(data)
        self.assertTrue(any('do not fit' in issue for issue in issues), issues)

    def test_overlapping_signals(self):
        data = minimal_database()
        data['frames']['F1']['layout']['Sig2'] = 2  # overlaps Sig1 (bits 0..3)
        issues = validate_lin_database(data)
        self.assertTrue(any('overlaps' in issue for issue in issues), issues)

    def test_frame_maps_undeclared_signal(self):
        data = minimal_database()
        data['frames']['F1']['layout']['Ghost'] = 0
        issues = validate_lin_database(data)
        self.assertTrue(any('undeclared signal' in issue for issue in issues), issues)

    def test_signal_references_unknown_frame(self):
        data = minimal_database()
        data['signals']['Sig1']['frame'] = 'Nowhere'
        issues = validate_lin_database(data)
        self.assertTrue(any('unknown frame' in issue for issue in issues), issues)

    def test_schedule_references_unknown_frame(self):
        data = minimal_database()
        data['schedules']['T1'] = [{'frame': 'Nowhere', 'delay_ms': 10}]
        issues = validate_lin_database(data)
        self.assertTrue(any('unknown frame' in issue for issue in issues), issues)

    def test_non_positive_schedule_delay(self):
        data = minimal_database()
        data['schedules']['T1'] = [{'frame': 'F1', 'delay_ms': 0}]
        issues = validate_lin_database(data)
        self.assertTrue(any('non-positive delay' in issue for issue in issues), issues)

    def test_zero_scaling_factor(self):
        data = minimal_database()
        data['signals']['Sig1']['factor'] = 0
        issues = validate_lin_database(data)
        self.assertTrue(any('factor of zero' in issue for issue in issues), issues)

    def test_inverted_min_max(self):
        data = minimal_database()
        data['signals']['Sig1'].update({'min': 10, 'max': 2})
        issues = validate_lin_database(data)
        self.assertTrue(any('greater than' in issue for issue in issues), issues)

    def test_initial_value_does_not_fit(self):
        data = minimal_database()
        data['signals']['Sig1']['init'] = 99  # 4 bits -> max 15
        issues = validate_lin_database(data)
        self.assertTrue(any('does not fit' in issue for issue in issues), issues)

    def test_state_value_does_not_fit(self):
        data = minimal_database()
        data['signals']['Sig1']['values'] = {'99': 'Zuviel'}
        issues = validate_lin_database(data)
        self.assertTrue(any('does not fit' in issue for issue in issues), issues)


class LdfErrorHandlingTests(unittest.TestCase):
    """Unsupported or malformed input fails visibly."""

    def test_non_ldf_content_is_refused(self):
        with self.assertRaises(SpecError) as caught:
            ldf_to_dict('this is not a LIN description', 'x.ldf')
        self.assertIn('LIN_description_file', str(caught.exception))

    def test_missing_signals_block_is_refused(self):
        with self.assertRaises(SpecError) as caught:
            ldf_to_dict('LIN_description_file;\nFrames { }\n', 'x.ldf')
        self.assertIn('Signals', str(caught.exception))

    def test_unsupported_encoding_entry_is_refused_by_the_importer(self):
        text = ('LIN_description_file;\n'
                'Signals { S1: 8, 0, Slave, Master; }\n'
                'Signal_encoding_types { Enc { bcd_value; } }\n'
                'Signal_representation { Enc: S1; }\n')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bcd.ldf'
            path.write_text(text, encoding='utf-8')
            with self.assertRaises(SpecError) as caught:
                ldf_importer.load(path, network='N')
        self.assertIn('bcd_value', str(caught.exception))


class LdfImporterIntegrationTests(unittest.TestCase):
    """The shipped demo file is usable as a project description."""

    def test_importer_reads_the_demo_file(self):
        resources = ldf_importer.load(LDF_PATH, network='BodyComfortLIN')
        kinds = {resource.kind for resource in resources}
        self.assertEqual(kinds, {ObjectKind.SIGNAL, ObjectKind.FRAME,
                                 ObjectKind.SCHEDULE})
        by_name = {resource.name: resource for resource in resources}
        self.assertEqual(by_name['DoorContactFL'].container, 'LIN_Door_01')
        self.assertEqual(by_name['DoorContactFL'].qualified_name,
                         'BodyComfortLIN::LIN_Door_01::DoorContactFL')
        self.assertEqual(by_name['DoorContactFL'].encoding.state_raw('Geschlossen'), 0)
        self.assertEqual(by_name['DoorContactFL'].encoding.state_raw('Offen'), 1)

    def test_schedule_entries_carry_their_delays(self):
        resources = ldf_importer.load(LDF_PATH, network='BodyComfortLIN')
        normal = next(r for r in resources if r.name == 'NormalTable')
        self.assertIn(('LIN_Door_01', 10), normal.attributes['entries'])


class LdfCliTests(unittest.TestCase):
    """The converter runs as a standalone command line tool."""

    def run_cli(self, *args):
        return subprocess.run([sys.executable, 'tools/ldf_to_json.py', *args],
                              capture_output=True, text=True, cwd=ROOT)

    def test_convert_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'lin.json'
            result = self.run_cli(str(LDF_PATH), '-o', str(output), '--check')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('Validation: no issues found', result.stdout)

            data = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(len(data['signals']), 16)
            self.assertEqual(len(data['frames']), 6)

    def test_validation_failure_reports_a_failing_status(self):
        broken = minimal_database()
        broken['frames']['F1']['id'] = '0x7F'
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'broken.json'
            source.write_text(json.dumps(broken), encoding='utf-8')
            result = self.run_cli(str(source), '--check')
            self.assertEqual(result.returncode, 1)
            self.assertIn('0x00..0x3F', result.stderr)

    def test_missing_input_file(self):
        result = self.run_cli('/nowhere/missing.ldf')
        self.assertEqual(result.returncode, 2)
        self.assertIn('not found', result.stderr)

    def test_malformed_input_reports_a_failing_status(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad.ldf'
            source.write_text('not a lin file', encoding='utf-8')
            result = self.run_cli(str(source))
            self.assertEqual(result.returncode, 2)
            self.assertIn('CONVERSION FAILED', result.stderr)

    def test_json_to_ldf_direction(self):
        with tempfile.TemporaryDirectory() as directory:
            json_path = Path(directory) / 'lin.json'
            ldf_path = Path(directory) / 'out.ldf'
            convert_file(LDF_PATH, json_path)
            result = self.run_cli(str(json_path), '-o', str(ldf_path))
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('LIN_description_file;', ldf_path.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
