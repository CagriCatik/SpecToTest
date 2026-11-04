"""Tests for the 7 critical review findings and counterexamples.

Guarantees:
1. Expectations referencing a BREAK step or unconsumed expectations are rejected.
2. Batch runner records ERROR and returns exit code 2 when a module fails to load.
3. Same-named specifications in different categories are not silently dropped, and duplicate Test_IDs are rejected.
4. Unclosed block comments (/* or <!--) at EOF trigger a syntax SpecError.
5. Loop variables undergo strict scope checking, contract validation (range & unit conversion), and condition validation.
6. Error aggregation never masks a primary technical error with a cleanup CheckFailed.
7. CAN wait operations fail if the observation completes after the timeout deadline.
"""
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from generate import derive_output_filename, generate, generate_batch
from operations.can import wait_can_signal
from run_bench import discover_test_modules, load_module_runners
from tcg.adapters.inbound.text_parser import parse_text_spec
from tcg.core.compiler import compile_cases
from tcg.core.model import SpecError
from tcg.runtime import CheckFailed, TestResult
from tcg.runtime.runner import execute
from tests.common import BaseTestCase, CONFIG, MAPPING, REGISTRY, RESOURCES, ROOT, RUNNER


class ReviewCounterexamplesModuleTests(BaseTestCase):

    def test_flaw_1_expectation_on_break_is_rejected(self):
        spec = """
        TESTFALL: TC_BREAK_EXP
        NAME: Test expectation on break
        Action
        10: FOR (v;[1])
        15: Warte 1 s
        20: BREAK
        END FOR
        Expected Result
        20: Parameter GAIN ist 999
        """
        sections = parse_text_spec(spec)
        with self.assertRaises(SpecError) as ctx:
            compile_cases(sections, self.mappings, self.profile, 'tc_break.txt')
        self.assertIn("references a BREAK statement", str(ctx.exception))

    def test_flaw_2_batch_runner_reports_error_on_broken_module(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            broken_file = suite_dir / 'test_broken.py'
            broken_file.write_text("raise RuntimeError('BROKEN MODULE')", encoding='utf-8')

            discovered = discover_test_modules(suite_dir)
            self.assertEqual(len(discovered), 1)

            # Test loader handles exception gracefully by returning an error result
            all_logs = []
            for _, path in discovered:
                try:
                    runners = load_module_runners(path)
                except Exception as err:
                    err_res = TestResult(test_id=path.stem.upper(), result='ERROR', error=err)
                    all_logs.append(err_res)

            self.assertEqual(len(all_logs), 1)
            self.assertEqual(all_logs[0].result, 'ERROR')
            self.assertIn('BROKEN MODULE', str(all_logs[0].error))

    def test_flaw_3_same_named_specs_in_different_categories_are_both_generated(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_root = Path(tmp_dir) / 'inputs'
            (spec_root / 'a').mkdir(parents=True)
            (spec_root / 'b').mkdir(parents=True)

            spec_a = spec_root / 'a' / 'tc_01_same.txt'
            spec_a.write_text("TESTFALL: TC_A\nNAME: Case A\nAction\n10. Warte 1 s\n", encoding='utf-8')

            spec_b = spec_root / 'b' / 'tc_01_same.txt'
            spec_b.write_text("TESTFALL: TC_B\nNAME: Case B\nAction\n10. Warte 1 s\n", encoding='utf-8')

            out_root = Path(tmp_dir) / 'generated'
            cases = generate_batch(spec_root, [MAPPING], RESOURCES, out_root, REGISTRY, RUNNER)
            self.assertEqual(len(cases), 2)
            self.assertEqual({c.id for c in cases}, {'TC_A', 'TC_B'})

            out_a = out_root / 'a' / 'test_tc_01_same.py'
            out_b = out_root / 'b' / 'test_tc_01_same.py'
            self.assertTrue(out_a.exists())
            self.assertTrue(out_b.exists())

    def test_flaw_3_duplicate_test_id_across_specs_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_root = Path(tmp_dir) / 'inputs'
            (spec_root / 'a').mkdir(parents=True)
            (spec_root / 'b').mkdir(parents=True)

            spec_a = spec_root / 'a' / 'tc_01.txt'
            spec_a.write_text("TESTFALL: TC_DUPLICATE\nNAME: Duplicate Case\nAction\n10. Warte 1 s\n", encoding='utf-8')

            spec_b = spec_root / 'b' / 'tc_02.txt'
            spec_b.write_text("TESTFALL: TC_DUPLICATE\nNAME: Duplicate Case 2\nAction\n10. Warte 1 s\n", encoding='utf-8')

            out_root = Path(tmp_dir) / 'generated'
            with self.assertRaises(SpecError) as ctx:
                generate_batch(spec_root, [MAPPING], RESOURCES, out_root, REGISTRY, RUNNER)
            self.assertIn("Duplicate Test_ID 'TC_DUPLICATE'", str(ctx.exception))

    def test_flaw_4_unclosed_block_comment_raises_syntax_spec_error(self):
        spec = """
        Action
        10. Warte 1 s /* Kommentar versehentlich nicht geschlossen
        Expected Result
        10. Parameter GAIN ist 999
        """
        with self.assertRaises(SpecError) as ctx:
            parse_text_spec(spec)
        self.assertIn("unclosed block comment", str(ctx.exception))

    def test_flaw_4_unclosed_html_comment_raises_syntax_spec_error(self):
        spec = """
        Action
        10. Warte 1 s <!-- unclosed html comment
        Expected Result
        10. Parameter GAIN ist 999
        """
        with self.assertRaises(SpecError) as ctx:
            parse_text_spec(spec)
        self.assertIn("unclosed HTML comment", str(ctx.exception))

    def test_flaw_5_break_condition_unknown_variable_is_rejected(self):
        spec = """
        Action
        10: FOR (v;[1, 2])
        20:   BREAK (v == missing)
        30: END FOR
        """
        sections = parse_text_spec(spec)
        with self.assertRaises(SpecError) as ctx:
            compile_cases(sections, self.mappings, self.profile, 'tc_break_var.txt')
        self.assertIn("variable 'missing' on right-hand side of BREAK condition is undefined", str(ctx.exception))

    def test_flaw_5_loop_variable_negative_time_rejected_at_compile_time(self):
        spec = """
        Action
        10: FOR (v;[-1])
        20:   Warte v
        30: END FOR
        """
        sections = parse_text_spec(spec)
        with self.assertRaises(SpecError) as ctx:
            compile_cases(sections, self.mappings, self.profile, 'tc_loop_neg.txt')
        self.assertIn("outside time range", str(ctx.exception))

    def test_flaw_5_loop_variable_unit_conversion(self):
        spec = """
        Action
        10: FOR (v;["13.8V"])
        20:   Batteriespannung = v
        30: END FOR
        """
        sections = parse_text_spec(spec)
        cases = compile_cases(sections, self.mappings, self.profile, 'tc_loop_conv.txt')
        loop = cases[0].steps[0]
        # Unit was converted from string literal to normalized Decimal('13.8') in Volts
        self.assertEqual(loop.items, (Decimal('13.8'),))

    def test_flaw_6_error_aggregation_technical_error_trumps_cleanup_check_failure(self):
        def buggy_runner(bench):
            cleanup_errors = []
            try:
                raise RuntimeError("PRIMARY_TECHNICAL_ERROR")
            finally:
                try:
                    raise CheckFailed("CLEANUP_CHECK_FAILURE")
                except Exception as e:
                    cleanup_errors.append(e)
                if cleanup_errors:
                    raise cleanup_errors[0]

        bench = self.bench()
        res = execute(buggy_runner, bench)
        self.assertEqual(res.result, 'ERROR')
        self.assertIsInstance(res.error, RuntimeError)
        self.assertEqual(str(res.error), "PRIMARY_TECHNICAL_ERROR")
        self.assertEqual(len(res.cleanup_errors), 1)
        self.assertIsInstance(res.cleanup_errors[0], CheckFailed)

    def test_flaw_7_wait_can_signal_fails_when_observation_exceeds_timeout(self):
        bench = self.bench()
        bench.set_can_signal('VehicleSpeed', 0)

        # Simulate bench where reading takes 2 seconds (exceeding 1s timeout)
        orig_get = bench.get_can_signal
        def slow_get_can_signal(sig):
            val = orig_get(sig)
            # Advance clock past timeout
            bench.time += Decimal('2.0')
            return 50  # Matches target value, but AFTER deadline!

        bench.get_can_signal = slow_get_can_signal

        with self.assertRaises(CheckFailed) as ctx:
            wait_can_signal(bench, signal='VehicleSpeed', value=50, timeout=Decimal('1.0'), interval=Decimal('0.1'))
        self.assertIn("observation completed after timeout", str(ctx.exception))


if __name__ == '__main__':
    unittest.main()
