"""Unit/Module tests for persistent timestamped execution logging."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from tcg.runtime.execution_logger import (
    log_step_record,
    log_suite_start,
    log_suite_summary,
    log_test_case_result,
    log_test_case_start,
    setup_execution_logger,
)
from tcg.runtime.result import TestResult
from tests.common import BaseTestCase


class ExecutionLoggerModuleTests(BaseTestCase):
    """Verifies that execution logger generates timestamped .log files and updates latest.log."""

    def test_logger_creates_timestamped_file_and_latest_symlink(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            log_dir = Path(tmp_str) / "test_logs"
            fixed_dt = datetime(2026, 11, 4, 8, 30, 0)
            logger, log_file = setup_execution_logger(
                log_dir=log_dir,
                prefix="test_bench",
                timestamp=fixed_dt,
            )

            self.assertTrue(log_file.exists())
            self.assertEqual(log_file.name, "test_bench_20261104_083000.log")
            latest_file = log_dir / "latest.log"
            self.assertTrue(latest_file.exists())

            # Log typical sequence
            log_suite_start(logger, "Vector CANoe", Path("generated"), 1)
            log_test_case_start(logger, "TC_DEMO", "bms")
            log_step_record(logger, "TC_DEMO", {
                'operation': 'set_can_signal',
                'details': {'signal': 'BatteryVoltage', 'value': '13.8', 'status': 'CONFIRMED'},
                'time': '0.100 s',
            })
            log_step_record(logger, "TC_DEMO", {
                'execution_id': '20',
                'phase': 'ACTION',
                'operation': 'check_voltage',
                'arguments': {'expected': '13.8'},
                'result': 'PASS',
                'status': 'CONFIRMED',
                'bench_time_s': '0.100',
            })
            dummy_result = TestResult("TC_DEMO", "PASS", duration=0.015, records=[{}, {}])
            log_test_case_result(logger, "TC_DEMO", dummy_result)
            log_suite_summary(logger, [dummy_result], 0.015, log_file_path=log_file)

            # Flush handlers
            for h in logger.handlers:
                h.flush()

            # Verify content written to both files
            content_ts = log_file.read_text(encoding='utf-8')
            content_latest = latest_file.read_text(encoding='utf-8')

            for content in (content_ts, content_latest):
                self.assertIn("⚡ SpecToTest — Testbench Ausführung gestartet", content)
                self.assertIn("[TC_DEMO] ▶ STARTE Testfall", content)
                self.assertIn("set_can_signal(signal=BatteryVoltage, value=13.8) [Aktorik: CONFIRMED]", content)
                self.assertIn("Step 20   (ACTION ) check_voltage(expected=13.8) -> PASS [Aktorik: CONFIRMED]", content)
                self.assertIn("✔ VERDICT: PASS", content)
                self.assertIn("ZUSAMMENFASSUNG: 1 Gesamt | 1 PASS", content)


if __name__ == '__main__':
    unittest.main()
