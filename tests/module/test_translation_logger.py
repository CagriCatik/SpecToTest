"""Unit/Module tests for translation / compilation logging."""
from datetime import datetime
from pathlib import Path
import tempfile
import unittest

from tcg.core.model import SourceRef, Step, TestCase
from tcg.core.translation_logger import (
    log_batch_header,
    log_batch_summary,
    log_compiled_case,
    log_spec_file_start,
    setup_translation_logger,
)
from tests.common import BaseTestCase


class TranslationLoggerModuleTests(BaseTestCase):
    """Verifies that the translation logger creates timestamped files and records step mappings."""

    def test_translation_logger_records_case_and_step_details(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            log_dir = Path(tmp_dir) / "logs"
            fixed_dt = datetime(2026, 11, 4, 9, 15, 0)
            logger, log_file = setup_translation_logger(
                log_dir=log_dir,
                prefix="compilation",
                timestamp=fixed_dt,
            )

            self.assertTrue(log_file.exists())
            self.assertEqual(log_file.name, "compilation_20261104_091500.log")
            latest_file = log_dir / "latest_translation.log"
            self.assertTrue(latest_file.exists())

            # Log mock compilation run
            log_batch_header(logger, Path("inputs"), 1, Path("generated"))
            log_spec_file_start(logger, Path("inputs/diagnostics/tc_demo.md"), "diagnostics")

            class DummyContract:
                id = "supply.set_battery_voltage"
                parameters = ()

            dummy_step = Step(
                execution_id="40",
                phase="ACTION",
                test_step=40,
                step_name="Voltage Step",
                expectation_order=None,
                contract=DummyContract(),
                arguments=(("value", "7.0"),),
                mapping_id="MAP_BATTERY_VOLTAGE",
                source=SourceRef("tc_demo.md", "Action", 12),
                description="Batteriespannung = 7000mV",
            )
            dummy_case = TestCase(
                id="TC_DEMO",
                name="Demo Testfall",
                objective="Testziel",
                profile_id="default",
                steps=(dummy_step,),
            )

            log_compiled_case(logger, dummy_case, Path("generated/diagnostics/test_demo.py"), "def run(): pass\n")
            log_batch_summary(logger, 1, 1, 1, 0.05, log_file)

            for h in logger.handlers:
                h.flush()

            content = log_file.read_text(encoding="utf-8")
            self.assertIn("⚡ SpecToTest — Übersetzungsvorgang gestartet", content)
            self.assertIn("TC_DEMO", content)
            self.assertIn('Z.12  [ACTION]     | 40.  "Batteriespannung = 7000mV"', content)
            self.assertIn("[MAP_BATTERY_VOLTAGE] supply.set_battery_voltage(value='7.0')", content)
            self.assertIn("AST-Status:  GÜLTIG", content)
            self.assertIn("ZUSAMMENFASSUNG ÜBERSETZUNG", content)


if __name__ == '__main__':
    unittest.main()

