import ast
from dataclasses import replace
from decimal import Decimal
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from openpyxl import Workbook

from generate import generate, read_specification
from tcg.compiler import SPEC_SCHEMA, compile_cases
from tcg.contracts import ContractError, OperationContract, ParameterSpec, build_registry
from tcg.demo_registry import REGISTRY
from tcg.dummy_bench import DummyBench, load_config
from tcg.excel_input import read_rows, read_tables
from tcg.mapping import MAPPING_COLUMNS, load_mappings, resolve
from tcg.model import SpecError
from tcg.parameters import Boolean
from tcg.profile import check_profile, load_profile
from tcg.render import render_python
from tcg.runtime import TestFailure
from tcg.text_input import read_text_spec

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'inputs/testspezifikation.txt'
BASE_SPEC = ROOT / 'inputs/testspezifikation_beispiel.txt'
MAPPING = ROOT / 'inputs/operation_mapping.xlsx'
RESOURCES = ROOT / 'inputs/resources.json'
CONFIG = ROOT / 'inputs/demo_bench.json'
RUNNER = 'tcg.demo_runner'


def copy_tables(tables):
    return {sheet: [(row, dict(data)) for row, data in rows] for sheet, rows in tables.items()}


def write_spec(path, tables):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for sheet, columns in SPEC_SCHEMA.items():
        worksheet = workbook.create_sheet(sheet)
        worksheet.append(columns)
        for _, data in tables[sheet]:
            worksheet.append(tuple(data[column] for column in columns))
    workbook.save(path)


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(RESOURCES)
        check_profile(self.profile, REGISTRY)
        self.mapping_rows = read_rows(MAPPING, 'Mapping', MAPPING_COLUMNS)
        self.mappings = load_mappings(self.mapping_rows, REGISTRY)
        self.tables = read_text_spec(SPEC)

    def cases(self, tables=None, mappings=None, workbook=SPEC.name):
        return compile_cases(tables or self.tables, mappings or self.mappings, self.profile, workbook)

    def namespace(self, tables=None, mappings=None):
        source = render_python(self.cases(tables, mappings), REGISTRY, 'tcg.demo_runner')
        namespace = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), namespace)
        return source, namespace

    def bench(self, **changes):
        return DummyBench(replace(load_config(CONFIG, self.profile), **changes))

    def test_text_schema_compiles_explicit_action_expectation_relationships(self):
        cases = self.cases()
        self.assertEqual([case.id for case in cases], ['TC_DIAGNOSTIC_TIMING_001', 'TC_HMI_PARAMETER_001'])
        self.assertEqual(cases[0].name, 'Diagnose mit expliziter Zeitsemantik')
        self.assertEqual([step.execution_id for step in cases[0].steps],
                         ['P10', 'S10.A', 'S10.E10', 'S10.E20', 'S10.E30', 'S20.A', 'S20.E10', 'C10'])
        expectations = [step for step in cases[0].steps if step.phase == 'EXPECTED']
        self.assertEqual([(step.test_step, step.expectation_order) for step in expectations],
                         [(10, 10), (10, 20), (10, 30), (20, 10)])
        self.assertEqual([step.step_name for step in expectations[:3]], ['Unterspannung anlegen'] * 3)

    def test_base_example_and_text_only_second_case_both_generate_and_run(self):
        with tempfile.TemporaryDirectory() as directory:
            base_out, extended_out = Path(directory) / 'base.py', Path(directory) / 'extended.py'
            base_cases = generate(BASE_SPEC, MAPPING, RESOURCES, base_out, REGISTRY, RUNNER)
            extended_cases = generate(SPEC, MAPPING, RESOURCES, extended_out, REGISTRY, RUNNER)
            self.assertEqual([case.id for case in base_cases], ['TC_DIAGNOSTIC_TIMING_001'])
            self.assertEqual([case.id for case in extended_cases],
                             ['TC_DIAGNOSTIC_TIMING_001', 'TC_HMI_PARAMETER_001'])
            namespace = {'__name__': 'generated_test'}
            exec(compile(extended_out.read_bytes(), str(extended_out), 'exec'), namespace)
            for run in namespace['RUNNERS'].values():
                self.assertEqual(run(self.bench()).result, 'PASS')
            used = {step.contract.id for step in extended_cases[1].steps}
            self.assertEqual(used, {'select_screen', 'expect_screen_text', 'write_parameter', 'expect_parameter'})

    def test_multiple_expectations_run_in_declared_order(self):
        _, namespace = self.namespace()
        log = namespace['RUNNERS']['TC_DIAGNOSTIC_TIMING_001'](self.bench())
        self.assertEqual([record['execution_id'] for record in log.records[2:5]],
                         ['S10.E10', 'S10.E20', 'S10.E30'])
        self.assertEqual([record['bench_time_s'] for record in log.records[2:5]], ['0', '0.5', '0.8'])

    def test_now_within_and_monitor_are_distinct_registered_operations(self):
        contracts = [REGISTRY[name].function.__name__ for name in
                     ('expect_diagnostic', 'expect_diagnostic_within', 'monitor_diagnostic')]
        self.assertEqual(contracts, ['expect_diagnostic', 'expect_diagnostic_within', 'monitor_diagnostic'])
        mappings = {mapping.id: mapping.contract.id for mapping in self.mappings}
        self.assertEqual(mappings['MAP_DIAGNOSTIC_NOW'], 'expect_diagnostic')
        self.assertEqual(mappings['MAP_DIAGNOSTIC_WITHIN'], 'expect_diagnostic_within')
        self.assertEqual(mappings['MAP_DIAGNOSTIC_MONITOR'], 'monitor_diagnostic')

    def test_timeout_failure_still_executes_cleanup(self):
        tables = copy_tables(self.tables)
        tables['Erwartungen'][1][1]['Erwartung'] = (
            'Auf Fehler UNDERVOLTAGE in BCM aktiv warten, maximal 400 ms, Prüfintervall 100 ms')
        _, namespace = self.namespace(tables)
        with self.assertRaises(TestFailure) as failure:
            namespace['RUNNERS']['TC_DIAGNOSTIC_TIMING_001'](self.bench())
        log = failure.exception.log
        self.assertEqual(log.result, 'FAIL')
        self.assertEqual(log.records[-1]['execution_id'], 'C10')
        self.assertEqual(log.records[-1]['result'], 'PASS')
        self.assertIn('S10.E30', log.not_run)

    def test_monitoring_detects_state_change_and_runs_cleanup(self):
        class ChangingBench(DummyBench):
            def diagnostic_active(self, controller, code):
                actual = super().diagnostic_active(controller, code)
                return False if self.now() >= Decimal('0.7') else actual
        _, namespace = self.namespace()
        with self.assertRaises(TestFailure) as failure:
            namespace['RUNNERS']['TC_DIAGNOSTIC_TIMING_001'](
                ChangingBench(load_config(CONFIG, self.profile)))
        self.assertEqual(failure.exception.log.records[-1]['execution_id'], 'C10')
        failed = next(record for record in failure.exception.log.records if record['result'] == 'FAIL')
        self.assertEqual(failed['execution_id'], 'S10.E30')

    def test_readable_status_is_converted_by_boolean_contract(self):
        mapping, arguments = resolve('Fehler UNDERVOLTAGE in BCM ist aktiv', self.mappings, self.profile)
        self.assertEqual(mapping.id, 'MAP_DIAGNOSTIC_NOW')
        self.assertEqual(dict(arguments)['active'], True)
        _, arguments = resolve('Fehler UNDERVOLTAGE in BCM ist inaktiv', self.mappings, self.profile)
        self.assertEqual(dict(arguments)['active'], False)

    def test_expectation_reference_missing_expectation_and_duplicate_order_are_errors(self):
        tables = copy_tables(self.tables)
        tables['Erwartungen'][0][1]['Schritt'] = 999
        with self.assertRaisesRegex(SpecError, 'unknown test step 999'):
            self.cases(tables)
        tables = copy_tables(self.tables)
        tables['Erwartungen'] = [item for item in tables['Erwartungen']
                                  if not (item[1]['Test_ID'] == 'TC_HMI_PARAMETER_001' and item[1]['Schritt'] == 10)]
        with self.assertRaisesRegex(SpecError, 'at least one explicit expectation'):
            self.cases(tables)
        tables = copy_tables(self.tables)
        tables['Erwartungen'][1][1]['Reihenfolge'] = 10
        with self.assertRaisesRegex(SpecError, 'duplicate Reihenfolge'):
            self.cases(tables)

    def test_unknown_ambiguous_and_invalid_parameters_block_generation(self):
        duplicate = dict(self.mapping_rows[0][1], Mapping_ID='MAP_OTHER')
        ambiguous = load_mappings(self.mapping_rows + [(99, duplicate)], REGISTRY)
        with self.assertRaisesRegex(SpecError, 'ambiguous'):
            self.cases(mappings=ambiguous)
        tables = copy_tables(self.tables)
        tables['Testschritte'][0][1]['Aktion'] = 'Versorgung auf 99 V setzen'
        with self.assertRaisesRegex(SpecError, 'outside'):
            self.cases(tables)
        tables = copy_tables(self.tables)
        tables['Erwartungen'][0][1]['Erwartung'] = 'Unbekannte Prüfung'
        with self.assertRaisesRegex(SpecError, 'no mapping'):
            self.cases(tables)

    def test_cleanup_error_does_not_skip_later_cleanup(self):
        class FailingCleanupBench(DummyBench):
            def write_parameter(self, parameter, value):
                if parameter == 'GAIN' and value == 0:
                    raise RuntimeError('injected cleanup error')
                return super().write_parameter(parameter, value)
        _, namespace = self.namespace()
        with self.assertRaises(TestFailure) as failure:
            namespace['RUNNERS']['TC_HMI_PARAMETER_001'](FailingCleanupBench(load_config(CONFIG, self.profile)))
        self.assertEqual([(record['execution_id'], record['result']) for record in failure.exception.log.records[-2:]],
                         [('C10', 'ERROR'), ('C20', 'PASS')])

    def test_contract_signature_drift_is_rejected(self):
        def invalid(bench, value):
            pass
        contract = OperationContract('invalid', invalid, (ParameterSpec('value', Boolean()),), frozenset({'ACTION'}))
        with self.assertRaisesRegex(ContractError, 'keyword-only'):
            build_registry((contract,))

    def test_mapping_order_and_fresh_process_regeneration_are_byte_identical(self):
        normal = render_python(self.cases(), REGISTRY, 'tcg.demo_runner').encode()
        reordered = load_mappings(tuple(reversed(self.mapping_rows)), REGISTRY)
        self.assertEqual(normal, render_python(self.cases(mappings=reordered), REGISTRY, 'tcg.demo_runner').encode())
        with tempfile.TemporaryDirectory() as directory:
            outputs = [Path(directory) / name for name in ('one.py', 'two.py')]
            command = [sys.executable, 'generate.py', '--spec', str(SPEC), '--mapping', str(MAPPING),
                       '--resources', str(RESOURCES), '--registry', 'tcg.demo_registry:REGISTRY',
                       '--runner', RUNNER]
            for output in outputs:
                result = subprocess.run(command + ['--output', str(output)], cwd=ROOT, text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(hashlib.sha256(outputs[0].read_bytes()).digest(),
                             hashlib.sha256(outputs[1].read_bytes()).digest())

    def test_invalid_excel_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output.py'
            output.write_text('keep me', encoding='utf-8')
            tables = copy_tables(self.tables)
            tables['Erwartungen'][0][1]['Erwartung'] = 'unknown'
            spec = Path(directory) / 'bad.xlsx'
            write_spec(spec, tables)
            with self.assertRaises(SpecError):
                generate(spec, MAPPING, RESOURCES, output, REGISTRY, RUNNER)
            self.assertEqual(output.read_text(encoding='utf-8'), 'keep me')

    def test_text_errors_preserve_existing_output_and_report_the_line(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output.py'
            output.write_text('keep me', encoding='utf-8')
            spec = Path(directory) / 'bad.txt'
            spec.write_text(SPEC.read_text(encoding='utf-8').replace(
                '  ERWARTUNG 10: Anzeige zeigt "Settings"',
                '  ERWARTUNG 10: Unbekannte Prüfung'), encoding='utf-8')
            with self.assertRaisesRegex(SpecError, r'bad\.txt:36 \[Erwartungen\].*no mapping'):
                generate(spec, MAPPING, RESOURCES, output, REGISTRY, RUNNER)
            self.assertEqual(output.read_text(encoding='utf-8'), 'keep me')

    def test_text_parser_rejects_missing_action_tabs_and_control_structures(self):
        valid = BASE_SPEC.read_text(encoding='utf-8')
        cases = (
            (valid.replace('  AKTION: Versorgung auf 7000 mV setzen\n', ''),
             'ERWARTUNG must appear after AKTION'),
            (valid.replace('  AKTION:', '\tAKTION:', 1), 'tabs are forbidden'),
            (valid.replace('20. Versorgung normalisieren', '20. FOR (i;[1, 2, 3])'),
             'FOR/BREAK control structures'),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, (content, message) in enumerate(cases):
                path = Path(directory) / f'bad_{index}.txt'
                path.write_text(content, encoding='utf-8')
                with self.subTest(message=message), self.assertRaisesRegex(SpecError, message):
                    read_text_spec(path)

    def test_text_requires_explicit_expectation_and_supported_suffix(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'missing.txt'
            path.write_text(BASE_SPEC.read_text(encoding='utf-8').replace(
                '  ERWARTUNG 10: Fehler UNDERVOLTAGE in BCM ist inaktiv\n\nNACHBEDINGUNGEN:',
                'NACHBEDINGUNGEN:'), encoding='utf-8')
            tables = read_text_spec(path)
            with self.assertRaisesRegex(SpecError, 'at least one explicit expectation'):
                self.cases(tables, workbook=path.name)
            unsupported = Path(directory) / 'spec.md'
            unsupported.write_text('unused', encoding='utf-8')
            with self.assertRaisesRegex(SpecError, 'unsupported specification format'):
                read_specification(unsupported)

    def test_excel_headers_empty_cells_and_formula_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad.xlsx'
            workbook = Workbook()
            worksheet = workbook.active
            worksheet.title = 'Testfaelle'
            worksheet.append(('Test_ID', 'Test_ID', 'Testziel'))
            workbook.save(path)
            with self.assertRaisesRegex(SpecError, 'duplicate column'):
                read_tables(path, {'Testfaelle': SPEC_SCHEMA['Testfaelle']})
            for value, message in ((None, 'missing'), ('', 'missing'), ('=1+1', 'formulas')):
                workbook = Workbook()
                worksheet = workbook.active
                worksheet.title = 'Testfaelle'
                worksheet.append(SPEC_SCHEMA['Testfaelle'])
                worksheet.append(('TC_X', 'Name', value))
                workbook.save(path)
                with self.assertRaisesRegex(SpecError, message):
                    read_tables(path, {'Testfaelle': SPEC_SCHEMA['Testfaelle']})

    def test_generation_does_not_execute_operations_and_literals_remain_data(self):
        def raising(bench, *, value):
            raise AssertionError('must not execute while generating')
        registry = dict(REGISTRY)
        registry['set_supply'] = replace(REGISTRY['set_supply'], function=raising)
        with tempfile.TemporaryDirectory() as directory:
            generate(SPEC, MAPPING, RESOURCES, Path(directory) / 'safe.py', registry, RUNNER)
        tables = copy_tables(self.tables)
        tables['Erwartungen'][4][1]['Erwartung'] = 'Anzeige zeigt "__import__(\'os\').system(\'never\')"'
        source, _ = self.namespace(tables)
        ast.parse(source)
        self.assertIn("__import__(\\'os\\').system", source)


if __name__ == '__main__':
    unittest.main()
