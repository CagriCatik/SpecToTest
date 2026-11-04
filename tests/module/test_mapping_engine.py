"""Module tests for the mapping engine: TOML parsing, resolution, ambiguity, and multi-file mappings."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from operations import timing
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.contracts import OperationContract, build_registry
from tcg.core.mapping import load_mapping, load_mappings, parse_mapping_document
from tcg.core.model import SpecError
from tests.common import BaseTestCase, copy_sections, MAPPING, REGISTRY, RESOURCES, ROOT, RUNNER, SPEC


class MappingEngineModuleTests(BaseTestCase):

    def test_unknown_ambiguous_and_invalid_parameters_block_generation(self):
        duplicate = dict(self.mapping_entries[0])
        duplicate['id'] = 'MAP_OTHER'
        ambiguous = load_mappings(self.mapping_entries + (duplicate,), REGISTRY)
        with self.assertRaisesRegex(SpecError, 'ambiguous'):
            self.cases(mappings=ambiguous)
        sections = copy_sections(self.sections)
        sections['Ablauf'][0][1]['Befehl'] = 'Versorgung auf 99 V setzen'
        with self.assertRaisesRegex(SpecError, 'outside'):
            self.cases(sections)
        sections = copy_sections(self.sections)
        sections['Ablauf'][0][1]['Befehl'] = 'Unbekannte Operation'
        with self.assertRaisesRegex(SpecError, 'no mapping'):
            self.cases(sections)

    def test_toml_mapping_validation(self):
        duplicate_id = dict(self.mapping_entries[0])
        with self.assertRaisesRegex(SpecError, 'duplicate id'):
            load_mappings((self.mapping_entries[0], duplicate_id), REGISTRY)
        bad = '''
        [[mapping]]
        id = "MAP_BAD"
        template = "Bad {wert}"
        operation = "missing_operation"
        parameters = { wert = "value" }
        '''
        entries = parse_mapping_document(bad)
        with self.assertRaisesRegex(SpecError, 'unknown operation'):
            load_mappings(entries, REGISTRY)
        with self.assertRaisesRegex(SpecError, 'invalid TOML'):
            parse_mapping_document('[[mapping]\nid =')

    def test_flow_rejects_operation_with_ambiguous_usage(self):
        contract = OperationContract('wait_both', timing.wait,
                                     REGISTRY['wait'].parameters,
                                     frozenset({'ACTION', 'EXPECTED'}))
        registry = build_registry((*REGISTRY.values(), contract))
        entry = {'id': 'MAP_WAIT_BOTH', 'template': 'Mehrdeutig {dauer}',
                 'operation': 'wait_both', 'parameters': {'dauer': 'seconds'}}
        mappings = load_mappings(self.mapping_entries + (entry,), registry)
        sections = copy_sections(self.sections)
        sections['Ablauf'][0][1]['Befehl'] = 'Mehrdeutig 1 s'
        with self.assertRaisesRegex(SpecError, 'exactly one of ACTION or EXPECTED'):
            compile_cases(sections, mappings, self.profile, SPEC.name)

    def test_mapping_order_and_fresh_processes_are_byte_identical(self):
        normal = render_python(self.cases(), REGISTRY, RUNNER).encode()
        reordered = load_mappings(tuple(reversed(self.mapping_entries)), REGISTRY)
        self.assertEqual(normal, render_python(self.cases(mappings=reordered), REGISTRY, RUNNER).encode())
        with tempfile.TemporaryDirectory() as directory:
            outputs = [Path(directory) / name for name in ('one.py', 'two.py')]
            command = [sys.executable, '-B', 'generate.py', '--spec', str(SPEC),
                       '--mapping', str(MAPPING), '--resources', str(RESOURCES),
                       '--registry', 'operations:REGISTRY', '--runner', RUNNER]
            for output in outputs:
                result = subprocess.run(command + ['--output', str(output)], cwd=ROOT,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(hashlib.sha256(outputs[0].read_bytes()).digest(),
                             hashlib.sha256(outputs[1].read_bytes()).digest())

    def test_multi_toml_mapping_loading_and_uniqueness(self):
        with tempfile.TemporaryDirectory() as directory:
            map1_file = Path(directory) / 'map1.toml'
            map2_file = Path(directory) / 'map2.toml'
            map1_file.write_text("""
            [[mapping]]
            id = "MAP_ONE"
            template = "Spezialbefehl 1 {zustand}"
            operation = "set_ignition"
            parameters = { zustand = "state" }
            """, encoding='utf-8')
            map2_file.write_text("""
            [[mapping]]
            id = "MAP_TWO"
            template = "Spezialbefehl 2 {zustand}"
            operation = "set_ignition"
            parameters = { zustand = "state" }
            """, encoding='utf-8')

            # Multi-file loading succeeds
            maps = load_mapping([map1_file, map2_file], REGISTRY)
            self.assertEqual({m.id for m in maps}, {'MAP_ONE', 'MAP_TWO'})

            # Reordering mapping files produces deterministic sorted mappings
            maps_reversed = load_mapping([map2_file, map1_file], REGISTRY)
            self.assertEqual(tuple(m.id for m in maps), tuple(m.id for m in maps_reversed))

            # Duplicate ID across files is rejected
            map2_dup = Path(directory) / 'map2_dup.toml'
            map2_dup.write_text("""
            [[mapping]]
            id = "MAP_ONE"
            template = "Anderer Befehl {zustand}"
            operation = "set_ignition"
            parameters = { zustand = "state" }
            """, encoding='utf-8')
            with self.assertRaisesRegex(SpecError, "duplicate mapping id 'MAP_ONE'"):
                load_mapping([map1_file, map2_dup], REGISTRY)


if __name__ == '__main__':
    unittest.main()

