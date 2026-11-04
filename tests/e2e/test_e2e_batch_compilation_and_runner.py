"""End-to-End test for batch compilation, discovery, and testbench execution across categories."""
from pathlib import Path
import tempfile
import unittest

from generate import generate_batch
from run_bench import discover_test_modules, load_module_runners
from tcg.runtime.html_report import generate_html_report
from tcg.runtime.runner import execute
from tests.common import BaseTestCase, MAPPING, REGISTRY, RESOURCES, ROOT, RUNNER


class BatchCompilationAndRunnerE2ETests(BaseTestCase):

    def test_run_bench_discover_and_execute(self):
        test_files = discover_test_modules(ROOT / 'generated')
        self.assertGreaterEqual(len(test_files), 12)
        for _, path in test_files:
            runners = load_module_runners(path)
            self.assertGreaterEqual(len(runners), 1)

    def test_categorized_batch_generation_and_e2e_bench(self):
        with tempfile.TemporaryDirectory() as directory:
            out_dir = Path(directory) / 'generated'
            cases = generate_batch(ROOT / 'inputs', [MAPPING], RESOURCES, out_dir, REGISTRY, RUNNER)
            self.assertEqual(len(cases), 14)

            # Check that category folders were created
            expected_categories = {'bms', 'can', 'diagnostics', 'hil', 'hmi', 'limits'}
            actual_subdirs = {p.name for p in out_dir.iterdir() if p.is_dir()}
            self.assertTrue(expected_categories.issubset(actual_subdirs))

            # Check test discovery
            discovered = discover_test_modules(out_dir)
            self.assertEqual(len(discovered), 14)

            # Run E2E and generate HTML report
            logs = []
            for stem, path in discovered:
                category = path.parent.name if path.parent != out_dir else 'general'
                runners = load_module_runners(path)
                for tid, runner in runners.items():
                    log = execute(runner, self.bench())
                    log.category = category
                    logs.append(log)

            self.assertEqual(len(logs), 14)
            self.assertTrue(all(l.result == 'PASS' for l in logs))

            html_out = Path(directory) / 'report.html'
            generate_html_report(logs, html_out)
            self.assertTrue(html_out.exists())
            html_text = html_out.read_text(encoding='utf-8')
            for cat in expected_categories:
                self.assertIn(f'>{cat.upper()}<', html_text)


if __name__ == '__main__':
    unittest.main()

