import ast
from dataclasses import replace
from decimal import Decimal, localcontext
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from generate import generate, read_specification
from examples import external_operations
from examples.external_registry import REGISTRY as EXTERNAL_REGISTRY
from operations.registry import REGISTRY
from operations import diagnostic, timing
from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, DummyBench, VectorDummyBench, load_config
from tcg.adapters.outbound.python_emitter import literal, render_python
from tcg.core.compiler import compile_cases
from tcg.core.contracts import ContractError, OperationContract, ParameterSpec, build_registry
from tcg.core.mapping import load_mapping, load_mappings, parse_mapping_document, resolve
from tcg.core.model import SourceRef, SpecError
from tcg.core.parameters import Boolean, Resource
from tcg.core.profile import load_profile
from tcg.runtime import CheckFailed, StepInfo, TestFailure, TestLog


ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'inputs/tc_05_diagnostic_timing_undervoltage.txt'
BASE_SPEC = ROOT / 'inputs/tc_01_undervoltage_recovery.txt'
TC_01 = ROOT / 'inputs/tc_01_undervoltage_recovery.txt'
TC_02 = ROOT / 'inputs/tc_02_hmi_loop_verification.txt'
TC_03 = ROOT / 'inputs/tc_03_diagnostic_powercycle.txt'
TC_04 = ROOT / 'inputs/tc_04_parameter_limits_sweep.txt'
TC_05 = ROOT / 'inputs/tc_05_diagnostic_timing_undervoltage.txt'
TC_06 = ROOT / 'inputs/tc_06_can_signal_transmission.txt'
TC_07 = ROOT / 'inputs/tc_07_controldesk_hil_simulation.txt'
TC_08 = ROOT / 'inputs/tc_08_bms_hv_precharge_sequence.txt'
TC_09 = ROOT / 'inputs/tc_09_bms_cell_overvoltage_derating.txt'
TC_10 = ROOT / 'inputs/tc_10_bms_thermal_derating_sweep.txt'
TC_11 = ROOT / 'inputs/tc_11_bms_isolation_monitoring.txt'
TC_12 = ROOT / 'inputs/tc_12_bms_signal_tolerances_and_ranges.txt'
MAPPING = ROOT / 'inputs/operation_mapping.toml'
RESOURCES = ROOT / 'inputs/resources.json'
CONFIG = ROOT / 'inputs/demo_bench.json'
EXTERNAL_SPEC = ROOT / 'examples/external_test.txt'
EXTERNAL_MAPPING = ROOT / 'examples/external_mapping.toml'
RUNNER = 'tcg.runtime.runner'


def copy_sections(sections):
    return {name: [(line, dict(data)) for line, data in rows] for name, rows in sections.items()}


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(RESOURCES)
        self.mapping_entries = parse_mapping_document(MAPPING.read_text(encoding='utf-8'), MAPPING.name)
        self.mappings = load_mappings(self.mapping_entries, REGISTRY, MAPPING.name)
        self.sections = read_text_spec(SPEC)

    def cases(self, sections=None, mappings=None, source=SPEC.name):
        return compile_cases(sections or self.sections, mappings or self.mappings, self.profile, source)

    def namespace(self, sections=None, mappings=None, registry=REGISTRY):
        source = render_python(self.cases(sections, mappings), registry, RUNNER)
        namespace = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), namespace)
        return source, namespace

    def bench(self, **changes):
        return DummyBench(replace(load_config(CONFIG, self.profile), **changes))

    def test_simple_flow_classifies_each_command_from_its_contract(self):
        cases = self.cases()
        self.assertEqual([case.id for case in cases], ['TC_05_DIAGNOSTIC_TIMING_UNDERVOLTAGE'])
        self.assertEqual([(step.execution_id, step.phase) for step in cases[0].steps], [
            ('P10', 'PRECONDITION'), ('P20', 'PRECONDITION'), ('P30', 'PRECONDITION'),
            ('S40', 'ACTION'), ('S50', 'EXPECTED'), ('S60', 'EXPECTED'),
            ('S70', 'EXPECTED'), ('S80', 'ACTION'), ('S90', 'EXPECTED'),
            ('C100', 'CLEANUP'), ('C110', 'CLEANUP'), ('C120', 'CLEANUP'),
        ])

    def test_empty_preconditions_cleanup_and_action_without_check_are_valid(self):
        text = '''
        Precondition
        Action
        10. Versorgung auf 13.5 V setzen
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'action_only.txt'
            path.write_text(text, encoding='utf-8')
            cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
        self.assertEqual([(step.execution_id, step.phase) for step in cases[0].steps], [('S10', 'ACTION')])
        namespace = {'__name__': 'generated_test'}
        exec(compile(render_python(cases, REGISTRY, RUNNER), 'generated_test.py', 'exec'), namespace)
        self.assertEqual(namespace['RUNNERS']['TC_ACTION_ONLY'](self.bench()).result, 'PASS')

    def test_base_and_txt_only_second_case_generate_and_run(self):
        with tempfile.TemporaryDirectory() as directory:
            base_out, extended_out = Path(directory) / 'base.py', Path(directory) / 'extended.py'
            base_cases = generate(BASE_SPEC, MAPPING, RESOURCES, base_out, REGISTRY, RUNNER)
            extended_cases = generate(SPEC, MAPPING, RESOURCES, extended_out, REGISTRY, RUNNER)
            self.assertEqual([case.id for case in base_cases], ['TC_01_UNDERVOLTAGE_RECOVERY'])
            self.assertEqual([case.id for case in extended_cases], ['TC_05_DIAGNOSTIC_TIMING_UNDERVOLTAGE'])
            namespace = {'__name__': 'generated_test'}
            exec(compile(extended_out.read_bytes(), str(extended_out), 'exec'), namespace)
            for run in namespace['RUNNERS'].values():
                self.assertEqual(run(self.bench()).result, 'PASS')

    def test_outer_whitespace_tabs_and_crlf_do_not_change_output(self):
        original_cases = compile_cases(read_text_spec(BASE_SPEC), self.mappings, self.profile, BASE_SPEC.name)
        lines = BASE_SPEC.read_text(encoding='utf-8').splitlines()
        tolerant = '\r\n'.join(f'\t{line}\t' if line else '\t  ' for line in lines) + '\r\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / BASE_SPEC.name
            path.write_bytes(tolerant.encode('utf-8'))
            tolerant_cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
        self.assertEqual(render_python(original_cases, REGISTRY, RUNNER),
                         render_python(tolerant_cases, REGISTRY, RUNNER))

    def test_now_within_and_monitor_are_distinct_operations(self):
        mapped = {mapping.id: mapping.contract.id for mapping in self.mappings}
        self.assertEqual(mapped['MAP_DIAGNOSTIC_NOW'], 'expect_diagnostic')
        self.assertEqual(mapped['MAP_DIAGNOSTIC_WITHIN'], 'expect_diagnostic_within')
        self.assertEqual(mapped['MAP_DIAGNOSTIC_MONITOR'], 'monitor_diagnostic')
        _, arguments = resolve('Fehler UNDERVOLTAGE in BCM ist aktiv', self.mappings, self.profile)
        self.assertIs(dict(arguments)['active'], True)

    def test_timeout_failure_runs_cleanup(self):
        sections = copy_sections(self.sections)
        command = next(data for _, data in sections['Ablauf'] if data['Schritt'] == 60)
        command['Befehl'] = ('Auf Fehler UNDERVOLTAGE in BCM aktiv warten, maximal 400 ms, '
                             'Prüfintervall 100 ms')
        _, namespace = self.namespace(sections)
        bench = self.bench()
        with self.assertRaises(CheckFailed):
            namespace['RUNNERS']['TC_05_DIAGNOSTIC_TIMING_UNDERVOLTAGE'](bench)
        # Cleanup was: Versorgung auf 13.5 V setzen
        self.assertEqual(bench.supply, Decimal('13.5'))

    def test_observation_completed_after_deadline_fails_even_if_value_matches(self):
        class SlowObservationBench:
            def __init__(self):
                self.time = Decimal('0')

            def now(self):
                return self.time

            def diagnostic_active(self, controller, code):
                self.time += Decimal('0.6')
                return True

            def wait(self, seconds):
                self.time += seconds

        with self.assertRaisesRegex(CheckFailed, 'completed after timeout'):
            diagnostic.expect_diagnostic_within(
                SlowObservationBench(), controller='BCM', code='UNDERVOLTAGE', active=True,
                timeout=Decimal('0.5'), interval=Decimal('0.1'))

    def test_monitoring_detects_state_change_and_runs_cleanup(self):
        class ChangingBench(DummyBench):
            def diagnostic_active(self, controller, code):
                actual = super().diagnostic_active(controller, code)
                return False if self.now() >= Decimal('0.7') else actual

        _, namespace = self.namespace()
        bench = ChangingBench(load_config(CONFIG, self.profile))
        with self.assertRaises(CheckFailed):
            namespace['RUNNERS']['TC_05_DIAGNOSTIC_TIMING_UNDERVOLTAGE'](bench)
        # Cleanup was: Versorgung auf 13.5 V setzen
        self.assertEqual(bench.supply, Decimal('13.5'))

    def test_cleanup_error_does_not_skip_later_cleanup(self):
        class FailingCleanupBench(DummyBench):
            def write_parameter(self, parameter, value):
                if parameter == 'GAIN' and value == 0:
                    raise RuntimeError('injected cleanup error')
                return super().write_parameter(parameter, value)

        from operations import hmi
        bench = FailingCleanupBench(load_config(CONFIG, self.profile))
        info1 = StepInfo('C1', 'CLEANUP', 1, None, None, 'spec.txt', 'MAP', 'cleanup 1')
        info2 = StepInfo('C2', 'CLEANUP', 2, None, None, 'spec.txt', 'MAP', 'cleanup 2')
        log = TestLog('TC_TEST', 'Test', None, 'PROFILE', (info1, info2), bench)
        log.cleanup('C1', hmi.write_parameter, parameter='GAIN', value=Decimal('0'))
        log.cleanup('C2', hmi.write_parameter, parameter='LIMIT', value=Decimal('0'))
        self.assertEqual([(r['execution_id'], r['result']) for r in log.records],
                         [('C1', 'ERROR'), ('C2', 'PASS')])

    def test_clock_failure_does_not_hide_check_failure_or_drop_record(self):
        class BrokenClock:
            def now(self):
                raise RuntimeError('clock unavailable')

        def failing_check(bench):
            raise CheckFailed('observed mismatch')

        info = StepInfo('S10', 'EXPECTED', 10, None, None, 'spec.txt:1 [Ablauf]',
                        'MAP_CHECK', 'check')
        log = TestLog('TC_CLOCK', 'Clock', None, 'PROFILE', (info,), BrokenClock())
        with self.assertRaisesRegex(CheckFailed, 'observed mismatch'):
            log.step('S10', failing_check)
        self.assertEqual(len(log.records), 1)
        self.assertEqual(log.records[0]['result'], 'FAIL')
        self.assertIn('clock unavailable', log.records[0]['logging_error'])
        self.assertEqual([type(error) for error in log.errors], [CheckFailed, RuntimeError])

    def test_decimal_rendering_is_independent_of_global_context(self):
        value = Decimal('123456789.123456789000')
        with localcontext() as context:
            context.prec = 6
            low_precision = literal(value)
        with localcontext() as context:
            context.prec = 28
            high_precision = literal(value)
        self.assertEqual(low_precision, high_precision)
        self.assertEqual(low_precision, "Decimal('123456789.123456789')")

    def test_registry_rejects_non_importable_local_function(self):
        def local_operation(bench, *, value):
            pass

        contract = OperationContract('local_operation', local_operation,
                                     (ParameterSpec('value', Boolean()),), frozenset({'ACTION'}))
        with self.assertRaisesRegex(ContractError, 'module level'):
            build_registry((contract,))

    def test_unused_operation_resource_does_not_block_existing_cases(self):
        unused = OperationContract(
            'unused_camera_operation', external_operations.expect_supply_at_least,
            (ParameterSpec('minimum', Resource('camera')),), frozenset({'EXPECTED'}))
        registry = build_registry((*REGISTRY.values(), unused))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'generated.py'
            cases = generate(BASE_SPEC, MAPPING, RESOURCES, output, registry, RUNNER)
        self.assertEqual([case.id for case in cases], ['TC_01_UNDERVOLTAGE_RECOVERY'])

    def test_external_operation_extension_generates_imports_and_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'external_generated.py'
            cases = generate(EXTERNAL_SPEC, EXTERNAL_MAPPING, RESOURCES, output,
                             EXTERNAL_REGISTRY, RUNNER)
            source = output.read_text(encoding='utf-8')
            self.assertIn('import examples.external_operations', source)
            namespace = {'__name__': 'generated_external'}
            exec(compile(source, str(output), 'exec'), namespace)
            log = namespace['RUNNERS']['TC_EXTERNAL_OPERATION_001'](self.bench())
        self.assertEqual(log.result, 'PASS')
        self.assertEqual(cases[0].steps[-1].contract.id, 'expect_supply_at_least')
        self.assertFalse(any(step.phase == 'CLEANUP' for step in cases[0].steps))

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

    def test_parser_syntax_errors_and_control_structures(self):
        valid = BASE_SPEC.read_text(encoding='utf-8')
        cases = (
            (valid.replace('40. Batteriespannung = 7000mV\n'
                           '50. Warte 1 s\n'
                           '60. Fehlerspeicher BCM1 lesen\n'
                           '70. Batteriespannung = 13.8V\n'
                           '80. Warte 500 ms\n', ''),
             'at least one numbered command'),
            (valid.replace('80. Warte 500 ms', '80: FOR (i;[1, 2, 3])'),
             'unclosed FOR loop'),
            (valid.replace('80. Warte 500 ms', '80: BREAK (i==3)'),
             'BREAK statement occurs outside of any FOR loop'),
            (valid.replace('80. Warte 500 ms', '80: FOR (i;[])\nEND FOR'),
             'FOR loop items must not be empty'),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, (content, message) in enumerate(cases):
                path = Path(directory) / f'bad_{index}.txt'
                path.write_text(content, encoding='utf-8')
                with self.subTest(message=message), self.assertRaisesRegex(SpecError, message):
                    sections = read_text_spec(path)
                    compile_cases(sections, self.mappings, self.profile, path.name)

    def test_invalid_input_preserves_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'output.py'
            output.write_text('keep me', encoding='utf-8')
            spec = Path(directory) / 'bad.txt'
            spec.write_text(BASE_SPEC.read_text(encoding='utf-8').replace(
                '10. Zündung an', '10. Unbekannte Prüfung'),
                encoding='utf-8')
            with self.assertRaisesRegex(SpecError, 'no mapping'):
                generate(spec, MAPPING, RESOURCES, output, REGISTRY, RUNNER)
            self.assertEqual(output.read_text(encoding='utf-8'), 'keep me')
            with self.assertRaisesRegex(SpecError, 'must be a .txt'):
                read_specification(Path(directory) / 'spec.xlsx')

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

    def test_python_like_text_remains_a_literal(self):
        spec_text = '''
        Precondition
        Action
        10. Bildschirm SETTINGS auswählen
        20. Anzeige zeigt "__import__(\\"os\\").system(\\"never\\")"
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'py_literal.txt'
            path.write_text(spec_text, encoding='utf-8')
            cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
            source = render_python(cases, REGISTRY, RUNNER)
            ast.parse(source)
            self.assertIn('__import__', source)
            self.assertNotIn('system("never")\n', source)

    def test_tc02_compilation_and_execution(self):
        sections = read_text_spec(TC_02)
        cases = compile_cases(sections, self.mappings, self.profile, TC_02.name)
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case.id, 'TC_02_HMI_LOOP_VERIFICATION')

        source = render_python(cases, REGISTRY, RUNNER)
        ast.parse(source)
        self.assertIn('for step in [10, 20, 30]:', source)
        self.assertIn('if step == 20:', source)
        self.assertIn('break', source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)
        bench = self.bench()
        report = ns['RUNNERS']['TC_02_HMI_LOOP_VERIFICATION'](bench).report()
        self.assertEqual(report['result'], 'PASS')

    def test_tc03_compilation_and_execution(self):
        sections = read_text_spec(TC_03)
        cases = compile_cases(sections, self.mappings, self.profile, TC_03.name)
        self.assertEqual(len(cases), 1)
        case = cases[0]
        self.assertEqual(case.id, 'TC_03_DIAGNOSTIC_POWERCYCLE')

        source = render_python(cases, REGISTRY, RUNNER)
        ast.parse(source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)
        bench = self.bench()
        report = ns['RUNNERS']['TC_03_DIAGNOSTIC_POWERCYCLE'](bench).report()
        self.assertEqual(report['result'], 'PASS')

    def test_postcondition_loop_executes_even_if_action_fails(self):
        spec_text = '''
        Precondition
        10. Zündung an

        Action
        20. Batteriespannung = 7000mV
        30. Parameter GAIN ist 99

        Postcondition
        40. Zündung aus
        60: FOR (i;[1, 2, 3])
        61:   Warte i
        62:   BREAK (i==2)
        63: END FOR
        70. Zündung an
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fail_test.txt'
            path.write_text(spec_text, encoding='utf-8')
            sections = read_text_spec(path)
            cases = compile_cases(sections, self.mappings, self.profile, path.name)
            source = render_python(cases, REGISTRY, RUNNER)

            ns = {'__name__': 'generated_test'}
            exec(compile(source, 'generated_test.py', 'exec'), ns)
            bench = self.bench()

            with self.assertRaises(CheckFailed):
                ns['RUNNERS']['TC_FAIL_TEST'](bench)

            # Action 30 failed, but postconditions still executed: 40 (off), 60 (waited 1+2=3s), 70 (on)
            self.assertEqual(bench.now(), Decimal('3'))
            self.assertEqual(bench.ignition, True)

    def test_variable_scoping_rejects_undefined_variable(self):
        spec_text = '''
        Precondition
        Action
        10. Batteriespannung = 7000mV
        20. Warte undefined_var
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad_scope.txt'
            path.write_text(spec_text, encoding='utf-8')
            sections = read_text_spec(path)
            with self.assertRaisesRegex(SpecError, "variable 'undefined_var' is undefined"):
                compile_cases(sections, self.mappings, self.profile, path.name)

    def test_units_with_and_without_whitespace(self):
        spec_text = '''
        Precondition
        Action
        10. Batteriespannung = 7000mV
        20. Batteriespannung = 13.8V
        30. Batteriespannung = 12 V
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'units.txt'
            path.write_text(spec_text, encoding='utf-8')
            cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
            steps = cases[0].steps
            self.assertEqual(steps[0].arguments, (('value', Decimal('7')),))
            self.assertEqual(steps[1].arguments, (('value', Decimal('13.8')),))
            self.assertEqual(steps[2].arguments, (('value', Decimal('12')),))

    def test_external_operations_package_generates_and_executes(self):
        from operations import REGISTRY as OP_REGISTRY
        mappings = load_mappings(self.mapping_entries, OP_REGISTRY, MAPPING.name)
        cases = compile_cases(read_text_spec(TC_01), mappings, self.profile, TC_01.name)
        source = render_python(cases, OP_REGISTRY, RUNNER)
        self.assertIn('import operations.ignition', source)
        self.assertIn('import operations.diagnostic', source)
        self.assertIn('import operations.supply', source)
        self.assertIn('import operations.timing', source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)
        report = ns['RUNNERS']['TC_01_UNDERVOLTAGE_RECOVERY'](self.bench()).report()
        self.assertEqual(report['result'], 'PASS')

    def test_tc06_can_signal_transmission_compilation_and_execution(self):
        sections = read_text_spec(TC_06)
        cases = compile_cases(sections, self.mappings, self.profile, TC_06.name)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, 'TC_06_CAN_SIGNAL_TRANSMISSION')

        source = render_python(cases, REGISTRY, RUNNER)
        ast.parse(source)
        self.assertIn('import operations.can as can', source)
        self.assertIn("can.set_can_signal(bench, signal='EngineSpeed', value=Decimal('2500'))", source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)
        
        # Test with Standard DummyBench
        bench = self.bench()
        res = ns['RUNNERS']['TC_06_CAN_SIGNAL_TRANSMISSION'](bench)
        self.assertEqual(res.result, 'PASS')

        # Test with Vector CANoe DummyBench
        vector_bench = VectorDummyBench(load_config(CONFIG, self.profile))
        res_v = ns['RUNNERS']['TC_06_CAN_SIGNAL_TRANSMISSION'](vector_bench)
        self.assertEqual(res_v.result, 'PASS')

    def test_tc07_controldesk_hil_simulation_compilation_and_execution(self):
        sections = read_text_spec(TC_07)
        cases = compile_cases(sections, self.mappings, self.profile, TC_07.name)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, 'TC_07_CONTROLDESK_HIL_SIMULATION')

        source = render_python(cases, REGISTRY, RUNNER)
        ast.parse(source)
        self.assertIn('can.wait_can_signal', source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)

        # Test with ControlDesk HiL DummyBench
        cd_bench = ControlDeskDummyBench(load_config(CONFIG, self.profile))
        res = ns['RUNNERS']['TC_07_CONTROLDESK_HIL_SIMULATION'](cd_bench)
        self.assertEqual(res.result, 'PASS')

    def test_vector_and_controldesk_bench_specific_apis(self):
        cfg = load_config(CONFIG, self.profile)
        vector_bench = VectorDummyBench(cfg)
        vector_bench.set_signal('EngineSpeed', 3000)
        self.assertEqual(vector_bench.get_signal('EngineSpeed'), Decimal('3000'))
        self.assertEqual(vector_bench.get_can_signal('EngineSpeed'), Decimal('3000'))

        cd_bench = ControlDeskDummyBench(cfg)
        cd_bench.write_variable('DoorContactStatus', 1)
        self.assertEqual(cd_bench.read_variable('DoorContactStatus'), Decimal('1'))
        self.assertEqual(cd_bench.get_can_signal('DoorContactStatus'), Decimal('1'))

    def test_bms_testcases_compilation_and_execution(self):
        bms_specs = [
            (TC_08, 'TC_08_BMS_HV_PRECHARGE_SEQUENCE'),
            (TC_09, 'TC_09_BMS_CELL_OVERVOLTAGE_DERATING'),
            (TC_10, 'TC_10_BMS_THERMAL_DERATING_SWEEP'),
            (TC_11, 'TC_11_BMS_ISOLATION_MONITORING'),
        ]
        for spec_path, expected_id in bms_specs:
            sections = read_text_spec(spec_path)
            cases = compile_cases(sections, self.mappings, self.profile, spec_path.name)
            self.assertEqual(len(cases), 1)
            self.assertEqual(cases[0].id, expected_id)

            source = render_python(cases, REGISTRY, RUNNER)
            ast.parse(source)

            ns = {'__name__': 'generated_test'}
            exec(compile(source, 'generated_test.py', 'exec'), ns)

            bench = self.bench()
            res = ns['RUNNERS'][expected_id](bench)
            self.assertEqual(res.result, 'PASS', f'{expected_id} failed on DummyBench')

            # Also execute on VectorDummyBench and ControlDeskDummyBench
            vector_bench = VectorDummyBench(load_config(CONFIG, self.profile))
            res_v = ns['RUNNERS'][expected_id](vector_bench)
            self.assertEqual(res_v.result, 'PASS', f'{expected_id} failed on VectorDummyBench')

            cd_bench = ControlDeskDummyBench(load_config(CONFIG, self.profile))
            res_cd = ns['RUNNERS'][expected_id](cd_bench)
            self.assertEqual(res_cd.result, 'PASS', f'{expected_id} failed on ControlDeskDummyBench')

    def test_tc12_can_signal_tolerances_ranges_and_comparisons(self):
        sections = read_text_spec(TC_12)
        cases = compile_cases(sections, self.mappings, self.profile, TC_12.name)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, 'TC_12_BMS_SIGNAL_TOLERANCES_AND_RANGES')

        source = render_python(cases, REGISTRY, RUNNER)
        ast.parse(source)
        self.assertIn('can.expect_can_signal_tolerance', source)
        self.assertIn('can.expect_can_signal_range', source)
        self.assertIn('can.expect_can_signal_min', source)
        self.assertIn('can.expect_can_signal_max', source)
        self.assertIn('can.expect_can_signal_greater', source)
        self.assertIn('can.expect_can_signal_less', source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)

        bench = self.bench()
        res = ns['RUNNERS']['TC_12_BMS_SIGNAL_TOLERANCES_AND_RANGES'](bench)
        self.assertEqual(res.result, 'PASS')

    def test_can_signal_tolerance_failure(self):
        from operations import can as can_ops
        bench = self.bench()
        bench.set_can_signal('CellVoltageMax', Decimal('4.30'))
        with self.assertRaises(CheckFailed):
            can_ops.expect_can_signal_tolerance(bench, signal='CellVoltageMax', value=Decimal('4.20'), tolerance=Decimal('0.05'))

    def test_junit_xml_report_generation(self):
        from tcg.runtime.runner import write_junit_xml
        from tcg.runtime import TestResult
        with tempfile.TemporaryDirectory() as directory:
            xml_path = Path(directory) / 'junit.xml'
            logs = [
                TestResult('TC_PASS', 'PASS', duration=0.12),
                TestResult('TC_FAIL', 'FAIL', error=CheckFailed('signal mismatch'), duration=0.45),
            ]
            write_junit_xml(logs, xml_path)
            content = xml_path.read_text(encoding='utf-8')
            self.assertIn('<testsuites', content)
            self.assertIn('name="TC_PASS"', content)
            self.assertIn('name="TC_FAIL"', content)
            self.assertIn('<failure', content)
            self.assertIn('signal mismatch', content)

    def test_automated_boundary_value_test_generator(self):
        import json
        from tcg.generators.boundaries import BoundaryTestConfig, generate_boundary_spec, generate_boundary_suite
        with tempfile.TemporaryDirectory() as directory:
            with open(ROOT / 'inputs/can_signals.json', 'r', encoding='utf-8') as f:
                can_db = json.load(f)['signals']

            out_files = generate_boundary_suite(
                variable_definitions=can_db,
                target_variables=['PackSOC', 'CellTempMax'],
                set_template="CAN-Signal {name} auf {val}{unit} setzen",
                check_template="CAN-Signal {name} ist {val}{unit}",
                preconditions=["Zündung an", "CAN-Signal Clamp15Status auf 1 setzen"],
                postconditions=["CAN-Signal Clamp15Status auf 0 setzen", "Zündung aus"],
                output_dir=directory,
            )
            self.assertEqual(len(out_files), 2)
            for spec_file in out_files:
                sections = read_text_spec(spec_file)
                cases = compile_cases(sections, self.mappings, self.profile, spec_file.name)
                self.assertEqual(len(cases), 1)
                source = render_python(cases, REGISTRY, RUNNER)
                ast.parse(source)

                ns = {'__name__': 'generated_test'}
                exec(compile(source, 'generated_test.py', 'exec'), ns)
                res = list(ns['RUNNERS'].values())[0](self.bench())
                self.assertEqual(res.result, 'PASS')

    def test_parameter_boundary_generation_with_generic_templates(self):
        from tcg.generators.boundaries import BoundaryTestConfig, generate_boundary_spec
        cfg = BoundaryTestConfig(
            name='GAIN',
            min_val=Decimal('0'),
            max_val=Decimal('100'),
            nominal_val=Decimal('50'),
            set_template="Parameter {name} auf {val} schreiben",
            check_template="Parameter {name} ist {val}",
            preconditions=("Zündung an",),
            postconditions=("Zündung aus",),
        )
        spec = generate_boundary_spec(cfg)
        self.assertIn("Parameter GAIN auf 0 schreiben", spec)
        self.assertIn("Parameter GAIN auf 50 schreiben", spec)
        self.assertIn("Parameter GAIN auf 100 schreiben", spec)
        self.assertIn("Parameter GAIN ist 100", spec)

    def test_html_report_generation(self):
        from tcg.runtime.html_report import generate_html_report
        from tcg.runtime import TestResult
        with tempfile.TemporaryDirectory() as directory:
            report_file = Path(directory) / 'report.html'
            logs = [
                TestResult('TC_01_PASS', 'PASS', duration=0.05, records=[{'time': '0.000 s', 'operation': 'wait', 'details': {'s': '1'}}]),
                TestResult('TC_02_FAIL', 'FAIL', duration=0.10, error=CheckFailed('expected 42, got 0')),
            ]
            generate_html_report(logs, report_file, bench_type='VectorDummyBench')
            self.assertTrue(report_file.exists())
            html_text = report_file.read_text(encoding='utf-8')
            self.assertIn('TC_01_PASS', html_text)
            self.assertIn('TC_02_FAIL', html_text)
            self.assertIn('VectorDummyBench', html_text)
            self.assertIn('expected 42, got 0', html_text)
            self.assertIn('progress-bar', html_text)

    def test_run_bench_discover_and_execute(self):
        from run_bench import discover_test_modules, load_module_runners
        test_files = discover_test_modules(ROOT / 'generated')
        self.assertGreaterEqual(len(test_files), 12)
        for _, path in test_files:
            runners = load_module_runners(path)
            self.assertGreaterEqual(len(runners), 1)


if __name__ == '__main__':
    unittest.main()
