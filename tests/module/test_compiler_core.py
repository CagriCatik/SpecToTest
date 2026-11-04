"""Module tests for compiler core: AST construction, phase classification, atomic generation."""
from pathlib import Path
import tempfile
import unittest

from generate import generate, read_specification
from tcg.adapters.outbound.dummy_bench import DummyBench
from tcg.core.model import SpecError
from tests.common import BASE_SPEC, BaseTestCase, MAPPING, REGISTRY, RESOURCES, RUNNER, SPEC, TC_01


class CompilerCoreModuleTests(BaseTestCase):

    def test_simple_flow_classifies_each_command_from_its_contract(self):
        cases = self.cases()
        self.assertEqual([case.id for case in cases], ['TC_05_DIAGNOSTIC_TIMING_UNDERVOLTAGE'])
        self.assertEqual([(step.execution_id, step.phase) for step in cases[0].steps], [
            ('P10', 'PRECONDITION'), ('P20', 'PRECONDITION'), ('P30', 'PRECONDITION'),
            ('S40', 'ACTION'), ('S50', 'EXPECTED'), ('S60', 'EXPECTED'),
            ('S70', 'EXPECTED'), ('S80', 'ACTION'), ('S90', 'EXPECTED'),
            ('C100', 'CLEANUP'), ('C110', 'CLEANUP'), ('C120', 'CLEANUP'),
        ])

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

    def test_atomic_generation_and_bench_factory(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'generated_test.py'
            generate(TC_01, MAPPING, RESOURCES, output, REGISTRY, RUNNER)
            self.assertTrue(output.exists())

            custom_instantiated = []
            def my_bench_factory(cfg):
                b = DummyBench(cfg)
                custom_instantiated.append(b)
                return b

            from tcg.runtime.runner import run_main
            ns = {}
            exec(compile(output.read_text(encoding='utf-8'), str(output), 'exec'), ns)
            code = run_main(ns['RUNNERS'], argv=['--test-id', 'TC_01_UNDERVOLTAGE_RECOVERY'], bench_factory=my_bench_factory)
            self.assertEqual(code, 0)
            self.assertEqual(len(custom_instantiated), 2)


if __name__ == '__main__':
    unittest.main()

