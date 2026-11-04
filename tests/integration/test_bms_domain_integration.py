"""Integration tests for Battery Management System (BMS) domain cases and tolerances."""
import ast
from decimal import Decimal
import unittest

from operations import can as can_ops
from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, VectorDummyBench, load_config
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.runtime import CheckFailed
from tests.common import BaseTestCase, CONFIG, REGISTRY, RUNNER, TC_08, TC_09, TC_10, TC_11, TC_12


class BmsDomainIntegrationTests(BaseTestCase):

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
        bench = self.bench()
        bench.set_can_signal('CellVoltageMax', Decimal('4.30'))
        with self.assertRaises(CheckFailed):
            can_ops.expect_can_signal_tolerance(bench, signal='CellVoltageMax', value=Decimal('4.20'), tolerance=Decimal('0.05'))


if __name__ == '__main__':
    unittest.main()

