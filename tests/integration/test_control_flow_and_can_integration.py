"""Integration tests for control flows (FOR, BREAK), CAN transmission, and ControlDesk HiL."""
import ast
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, VectorDummyBench, load_config
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.runtime import CheckFailed
from tests.common import BaseTestCase, CONFIG, REGISTRY, RUNNER, TC_02, TC_03, TC_06, TC_07


class ControlFlowAndCanIntegrationTests(BaseTestCase):

    def test_tc02_compilation_and_execution(self):
        sections = read_text_spec(TC_02)
        cases = compile_cases(sections, self.mappings, self.profile, TC_02.name)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, 'TC_02_HMI_LOOP_VERIFICATION')

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
        self.assertEqual(cases[0].id, 'TC_03_DIAGNOSTIC_POWERCYCLE')

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

    def test_tc06_can_signal_transmission_compilation_and_execution(self):
        sections = read_text_spec(TC_06)
        cases = compile_cases(sections, self.mappings, self.profile, TC_06.name)
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0].id, 'TC_06_CAN_SIGNAL_TRANSMISSION')

        source = render_python(cases, REGISTRY, RUNNER)
        ast.parse(source)
        self.assertIn('import operations.can as _op_can', source)
        self.assertIn("_op_can.set_can_signal(bench, signal='EngineSpeed', value=Decimal('2500'))", source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)

        bench = self.bench()
        res = ns['RUNNERS']['TC_06_CAN_SIGNAL_TRANSMISSION'](bench)
        self.assertEqual(res.result, 'PASS')

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

        cd_bench = ControlDeskDummyBench(load_config(CONFIG, self.profile))
        res = ns['RUNNERS']['TC_07_CONTROLDESK_HIL_SIMULATION'](cd_bench)
        self.assertEqual(res.result, 'PASS')


if __name__ == '__main__':
    unittest.main()
