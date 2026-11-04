"""Module tests for HTML dashboard reporting and JUnit XML generation."""
from pathlib import Path
import tempfile
import unittest

from tcg.runtime import CheckFailed, TestResult
from tcg.runtime.html_report import generate_html_report
from tcg.runtime.runner import write_junit_xml
from tests.common import BaseTestCase


class HtmlReportModuleTests(BaseTestCase):

    def test_junit_xml_report_generation(self):
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

    def test_html_report_generation(self):
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


if __name__ == '__main__':
    unittest.main()

