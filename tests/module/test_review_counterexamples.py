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
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from generate import derive_output_filename, generate, generate_batch
from operations.can import wait_can_signal
import run_bench
from run_bench import discover_test_modules, load_module_runners
from tcg.adapters.inbound.text_parser import parse_text_spec
from tcg.adapters.outbound.python_emitter import render_python
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

    def test_flaw_1_loop_variable_dimension_preservation_and_order_independence(self):
        # Case A: Voltage operation first, then timing operation
        spec_a = """
        Action
        10: FOR (v;["1000mV"])
        20:   Batteriespannung = v
        30:   Warte v
        END FOR
        """
        sections_a = parse_text_spec(spec_a)
        with self.assertRaises(SpecError) as ctx_a:
            compile_cases(sections_a, self.mappings, self.profile, 'tc_mv_time_a.txt')
        self.assertIn("mV", str(ctx_a.exception))
        self.assertIn("invalid for parameter 'seconds'", str(ctx_a.exception))

        # Case B: Timing operation first, then voltage operation (must fail with same error)
        spec_b = """
        Action
        10: FOR (v;["1000mV"])
        20:   Warte v
        30:   Batteriespannung = v
        END FOR
        """
        sections_b = parse_text_spec(spec_b)
        with self.assertRaises(SpecError) as ctx_b:
            compile_cases(sections_b, self.mappings, self.profile, 'tc_mv_time_b.txt')
        self.assertIn("mV", str(ctx_b.exception))
        self.assertIn("invalid for parameter 'seconds'", str(ctx_b.exception))

        # Case C: Compatible multiple operations preserve unit conversion and consistency
        spec_c = """
        Action
        10: FOR (v;["13.8V", "12V"])
        20:   Batteriespannung = v
        30:   Batteriespannung = v
        END FOR
        """
        sections_c = parse_text_spec(spec_c)
        cases_c = compile_cases(sections_c, self.mappings, self.profile, 'tc_mv_compat.txt')
        loop = cases_c[0].steps[0]
        self.assertEqual(loop.items, (Decimal('13.8'), Decimal('12')))

    def test_flaw_1_nested_loop_variable_conversion(self):
        # Nested loop: outer variable 't' is used for the first time inside inner loop 'i'
        spec = """
        TESTFALL: TC_NESTED_LOOP
        NAME: Test nested loop conversion
        Action
        10: FOR (t;["1000ms"])
        20:   FOR (i;[1])
        30:     Warte t
        40:   END FOR
        50: END FOR
        """
        sections = parse_text_spec(spec)
        cases = compile_cases(sections, self.mappings, self.profile, 'tc_nested_loop.txt')
        outer_loop = cases[0].steps[0]
        # "1000ms" must be converted to 1 second (Decimal('1'))
        self.assertEqual(outer_loop.items, (Decimal('1'),))

        # Check rendered Python source:
        source = render_python(cases, REGISTRY, RUNNER)
        self.assertIn("Decimal('1')", source)

        # Execute rendered Python code on bench to verify runtime execution
        ns = {}
        exec(source, ns)
        bench = self.bench()
        bench_time_before = bench.time
        res = execute(ns['run_tc_nested_loop'], bench)
        self.assertEqual(res.result, 'PASS')
        # bench time should have advanced by 1 second
        self.assertEqual(bench.time - bench_time_before, Decimal('1'))

    def test_flaw_2_batch_runner_reports_error_on_broken_module(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            broken_file = suite_dir / 'test_broken.py'
            broken_file.write_text("raise RuntimeError('BROKEN MODULE')\n", encoding='utf-8')

            xml_report = Path(tmp_dir) / 'reports' / 'junit.xml'
            html_report = Path(tmp_dir) / 'reports' / 'report.html'
            log_dir = Path(tmp_dir) / 'logs'

            # Run actual batch runner entrypoint with CLI flags
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_report),
                '--html-report', str(html_report),
                '--log-dir', str(log_dir),
            ])

            # Must return exit code 2 indicating an ERROR result
            self.assertEqual(exit_code, 2)
            self.assertTrue(xml_report.exists())
            self.assertTrue(html_report.exists())

            xml_content = xml_report.read_text(encoding='utf-8')
            self.assertIn('errors="1"', xml_content)
            self.assertIn('BROKEN MODULE', xml_content)

            html_content = html_report.read_text(encoding='utf-8')
            self.assertIn('ERROR', html_content)

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

    def test_flaw_3_failed_batch_does_not_modify_existing_output_files(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_root = Path(tmp_dir) / 'inputs'
            (spec_root / 'a').mkdir(parents=True)
            (spec_root / 'b').mkdir(parents=True)

            spec_a = spec_root / 'a' / 'tc_01.txt'
            spec_a.write_text("TESTFALL: TC_DUPLICATE\nNAME: Duplicate Case 1\nAction\n10. Warte 1 s\n", encoding='utf-8')

            spec_b = spec_root / 'b' / 'tc_02.txt'
            spec_b.write_text("TESTFALL: TC_DUPLICATE\nNAME: Duplicate Case 2\nAction\n10. Warte 1 s\n", encoding='utf-8')

            out_root = Path(tmp_dir) / 'generated'
            (out_root / 'a').mkdir(parents=True)
            existing_file = out_root / 'a' / 'test_existing.py'
            existing_file.write_text("# PREVIOUS VALID FILE CONTENT\n", encoding='utf-8')

            with self.assertRaises(SpecError):
                generate_batch(spec_root, [MAPPING], RESOURCES, out_root, REGISTRY, RUNNER)

            # Assert that the existing file was NOT modified or replaced
            self.assertEqual(existing_file.read_text(encoding='utf-8'), "# PREVIOUS VALID FILE CONTENT\n")
            # And no half-compiled duplicate output files were written
            self.assertFalse((out_root / 'a' / 'test_tc_01.py').exists())
            self.assertFalse((out_root / 'b' / 'test_tc_02.py').exists())

    def test_flaw_2_deleted_specs_not_executed_by_runner(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            spec_root = Path(tmp_dir) / 'inputs'
            out_root = Path(tmp_dir) / 'generated'
            spec_root.mkdir()
            out_root.mkdir()

            spec_a = spec_root / 'tc_a.txt'
            spec_a.write_text("TESTFALL: TC_A\nNAME: Case A\nAction\n10. Warte 1 s\n", encoding='utf-8')

            spec_b = spec_root / 'tc_b.txt'
            spec_b.write_text("TESTFALL: TC_B\nNAME: Case B\nAction\n10. Warte 1 s\n", encoding='utf-8')

            # 1. Generate both TC_A and TC_B
            cases = generate_batch(spec_root, [MAPPING], RESOURCES, out_root, REGISTRY, RUNNER)
            self.assertEqual(len(cases), 2)
            discovered_1 = discover_test_modules(out_root)
            self.assertEqual(len(discovered_1), 2)
            self.assertEqual({name for name, _ in discovered_1}, {'test_tc_a', 'test_tc_b'})

            # 2. Add a foreign file (e.g. user utility) that should be preserved
            foreign_file = out_root / 'user_helper.py'
            foreign_file.write_text("# foreign user script\n", encoding='utf-8')

            # 3. Delete spec_b
            spec_b.unlink()

            # 4. Re-generate batch in the same output directory
            cases_after = generate_batch(spec_root, [MAPPING], RESOURCES, out_root, REGISTRY, RUNNER)
            self.assertEqual(len(cases_after), 1)
            self.assertEqual(cases_after[0].id, 'TC_A')

            # 5. Discover modules: only TC_A is discovered! Deleted TC_B is ignored by manifest
            discovered_2 = discover_test_modules(out_root)
            self.assertEqual(len(discovered_2), 1)
            self.assertEqual(discovered_2[0][0], 'test_tc_a')

            # 6. Stale test file was cleaned up from disk
            self.assertFalse((out_root / 'test_tc_b.py').exists())

            # 7. Foreign file is preserved
            self.assertTrue(foreign_file.exists())
            self.assertEqual(foreign_file.read_text(encoding='utf-8'), "# foreign user script\n")

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

    def test_flaw_5_variable_starting_with_underscore_is_rejected(self):
        spec = """
        Action
        10: FOR (_op_timing;[1])
        20:   Warte 1 s
        30: END FOR
        """
        sections = parse_text_spec(spec)
        with self.assertRaises(SpecError) as ctx:
            compile_cases(sections, self.mappings, self.profile, 'tc_var_underscore.txt')
        self.assertIn("cannot start with an underscore", str(ctx.exception))

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

    def test_manifest_missing_file_reports_error_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            # Manifest references a test file that is missing on disk
            manifest_path.write_text(
                '{"version": "1.0", "files": ["test_missing.py"]}',
                encoding='utf-8'
            )

            # 1. Programmatic discovery strictly raises FileNotFoundError
            with self.assertRaises(FileNotFoundError) as ctx:
                discover_test_modules(suite_dir)
            self.assertIn("test_missing.py", str(ctx.exception))

            # 2. CLI execution must record an ERROR and return exit code 2
            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 2)
            self.assertTrue(xml_path.exists())
            self.assertTrue(html_path.exists())

            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('errors="1"', xml_content)
            self.assertIn('test_missing.py', xml_content)

            html_content = html_path.read_text(encoding='utf-8')
            self.assertIn('ERROR', html_content)

    def test_manifest_invalid_json_reports_error_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            manifest_path.write_text('{ malformed json content here ...', encoding='utf-8')

            # Create stale/foreign files that must NOT be discovered or executed
            (suite_dir / 'test_stale.py').write_text("# stale\n", encoding='utf-8')
            (suite_dir / 'test_user.py').write_text("# user\n", encoding='utf-8')

            # 1. Programmatic discovery strictly raises ValueError
            with self.assertRaises(ValueError) as ctx:
                discover_test_modules(suite_dir)
            self.assertIn("Invalid JSON in manifest", str(ctx.exception))

            # 2. CLI execution must record an ERROR and return exit code 2
            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 2)

            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('errors="1"', xml_content)
            self.assertIn('MANIFEST_ERROR', xml_content)

    def test_directory_without_manifest_falls_back_to_rglob(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            # No manifest created here
            test_file = suite_dir / 'test_standalone.py'
            test_file.write_text("RUNNERS = {}\n", encoding='utf-8')

            discovered = discover_test_modules(suite_dir)
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0][0], 'test_standalone')

    def test_manifest_missing_runner_entry_reports_error_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            manifest_data = {
                "version": "1.0",
                "files": ["test_multi.py"],
                "specs": {
                    "test_multi.py": {
                        "spec": "inputs/multi.md",
                        "test_ids": ["TC_A", "TC_B"]
                    }
                }
            }
            manifest_path.write_text(json.dumps(manifest_data), encoding='utf-8')

            test_file = suite_dir / 'test_multi.py'
            test_file.write_text(
                "def runner_a(bench): pass\n"
                "runner_a.test_id = 'TC_A'\n"
                "RUNNERS = {'TC_A': runner_a}\n",  # TC_B is omitted from RUNNERS
                encoding='utf-8'
            )

            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 2)
            self.assertTrue(xml_path.exists())
            self.assertTrue(html_path.exists())

            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('errors="1"', xml_content)
            self.assertIn('name="TC_B"', xml_content)
            self.assertIn('missing from test_multi.py RUNNERS', xml_content)
            self.assertIn('name="TC_A"', xml_content)

            html_content = html_path.read_text(encoding='utf-8')
            self.assertIn('ERROR', html_content)
            self.assertIn('TC_B', html_content)
            self.assertIn('TC_A', html_content)

            # Also verify that applying --filter still detects missing TC_B before filter
            exit_code_filter = run_bench.main([
                '--suite', str(suite_dir),
                '--filter', 'TC_A',
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code_filter, 2)

    def test_manifest_extra_runner_entry_reports_error_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            manifest_data = {
                "version": "1.0",
                "files": ["test_single.py"],
                "specs": {
                    "test_single.py": {
                        "spec": "inputs/single.md",
                        "test_ids": ["TC_A"]
                    }
                }
            }
            manifest_path.write_text(json.dumps(manifest_data), encoding='utf-8')

            test_file = suite_dir / 'test_single.py'
            test_file.write_text(
                "def runner_a(bench): pass\n"
                "runner_a.test_id = 'TC_A'\n"
                "def runner_extra(bench): pass\n"
                "runner_extra.test_id = 'TC_EXTRA'\n"
                "RUNNERS = {'TC_A': runner_a, 'TC_EXTRA': runner_extra}\n",
                encoding='utf-8'
            )

            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 2)
            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('errors="1"', xml_content)
            self.assertIn('TC_EXTRA', xml_content)
            self.assertIn('Unexpected test case ID', xml_content)

    def test_duplicate_runner_test_id_across_modules_reports_error_and_exits_2(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            manifest_data = {
                "version": "legacy",
                "files": ["test_one.py", "test_two.py"],
            }
            manifest_path.write_text(json.dumps(manifest_data), encoding='utf-8')

            (suite_dir / 'test_one.py').write_text(
                "def runner(bench): pass\n"
                "runner.test_id = 'TC_DUP'\n"
                "RUNNERS = {'TC_DUP': runner}\n",
                encoding='utf-8'
            )
            (suite_dir / 'test_two.py').write_text(
                "def runner(bench): pass\n"
                "runner.test_id = 'TC_DUP'\n"
                "RUNNERS = {'TC_DUP': runner}\n",
                encoding='utf-8'
            )

            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 2)
            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('errors="1"', xml_content)
            self.assertIn('TC_DUP', xml_content)
            self.assertIn('Duplicate test case ID', xml_content)

    def test_manifest_missing_test_ids_reports_manifest_error_and_exits_2(self):
        """Review counterexample: Manifest specifies a file in specs, but omits test_ids."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            manifest_data = {
                "version": "1.0",
                "files": ["test_multi.py"],
                "specs": {
                    "test_multi.py": {
                        "spec": "inputs/multi.md"
                        # test_ids is missing!
                    }
                }
            }
            manifest_path.write_text(json.dumps(manifest_data), encoding='utf-8')

            test_file = suite_dir / 'test_multi.py'
            test_file.write_text(
                "def runner_a(bench): pass\n"
                "runner_a.test_id = 'TC_A'\n"
                "RUNNERS = {'TC_A': runner_a}\n",
                encoding='utf-8'
            )

            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 2)
            self.assertTrue(xml_path.exists())
            self.assertTrue(html_path.exists())

            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('errors="1"', xml_content)
            self.assertIn('MANIFEST_ERROR', xml_content)
            self.assertIn("missing valid 'test_ids' list", xml_content)

            html_content = html_path.read_text(encoding='utf-8')
            self.assertIn('ERROR', html_content)

    def test_manifest_missing_specs_section_reports_manifest_error_and_exits_2(self):
        """Current format version 1.0 requires 'specs' dictionary."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            manifest_data = {
                "version": "1.0",
                "files": ["test_single.py"],
            }
            manifest_path.write_text(json.dumps(manifest_data), encoding='utf-8')

            test_file = suite_dir / 'test_single.py'
            test_file.write_text(
                "def runner_a(bench): pass\n"
                "runner_a.test_id = 'TC_A'\n"
                "RUNNERS = {'TC_A': runner_a}\n",
                encoding='utf-8'
            )

            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 2)
            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('MANIFEST_ERROR', xml_content)
            self.assertIn("missing required 'specs' dictionary", xml_content)

    def test_manifest_legacy_version_allows_omitting_specs(self):
        """Explicit legacy version in manifest allows running without specs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            suite_dir = Path(tmp_dir) / 'generated'
            suite_dir.mkdir()
            manifest_path = suite_dir / '.manifest.json'
            manifest_data = {
                "version": "legacy",
                "files": ["test_single.py"],
            }
            manifest_path.write_text(json.dumps(manifest_data), encoding='utf-8')

            test_file = suite_dir / 'test_single.py'
            test_file.write_text(
                "def runner_a(bench): pass\n"
                "runner_a.test_id = 'TC_A'\n"
                "RUNNERS = {'TC_A': runner_a}\n",
                encoding='utf-8'
            )

            xml_path = Path(tmp_dir) / 'junit.xml'
            html_path = Path(tmp_dir) / 'report.html'
            exit_code = run_bench.main([
                '--suite', str(suite_dir),
                '--junit-xml', str(xml_path),
                '--html-report', str(html_path),
                '--log-dir', str(Path(tmp_dir) / 'logs'),
            ])
            self.assertEqual(exit_code, 0)
            xml_content = xml_path.read_text(encoding='utf-8')
            self.assertIn('tests="1"', xml_content)
            self.assertIn('errors="0"', xml_content)


if __name__ == '__main__':
    unittest.main()

