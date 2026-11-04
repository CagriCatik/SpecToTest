"""Unit tests for the Vector CANdb (.dbc) <-> JSON converter and validator."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from tools.dbc_to_json import (
    convert_file,
    dbc_to_dict,
    dict_to_dbc,
    validate_can_database,
)
from operations.registry import REGISTRY
from tcg.adapters.inbound.text_parser import parse_text_spec
from tcg.adapters.outbound.dummy_bench import VectorDummyBench, load_config
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.mapping import load_mappings, parse_mapping_document
from tcg.core.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent.parent


class TestDbcConverter(unittest.TestCase):
    """Test suite for DBC parsing, JSON conversion, DBC generation, and CAN validations."""

    def setUp(self):
        self.dbc_path = ROOT / "tools" / "powertrain_bms.dbc"
        self.json_path = ROOT / "inputs" / "can_signals.json"
        self.assertTrue(self.dbc_path.exists(), f"DBC file missing: {self.dbc_path}")
        self.assertTrue(self.json_path.exists(), f"JSON file missing: {self.json_path}")

    def test_parse_powertrain_bms_dbc(self):
        content = self.dbc_path.read_text(encoding="utf-8")
        data = dbc_to_dict(content)

        self.assertEqual(data["database"], "Powertrain_BMS_CAN")
        self.assertEqual(data["baudrate"], 500000)
        self.assertEqual(len(data["messages"]), 9)
        self.assertEqual(len(data["signals"]), 27)

        # Spot check messages
        self.assertIn("Power_01", data["messages"])
        power_msg = data["messages"]["Power_01"]
        self.assertEqual(power_msg["id"], "0x050")
        self.assertEqual(power_msg["dlc"], 8)
        self.assertEqual(power_msg["cycle_time_ms"], 100)

        self.assertIn("BMS_04_Cells", data["messages"])
        cells_msg = data["messages"]["BMS_04_Cells"]
        self.assertEqual(cells_msg["id"], "0x303")
        self.assertEqual(cells_msg["dlc"], 8)
        self.assertEqual(cells_msg["cycle_time_ms"], 50)

        # Spot check signals
        self.assertIn("Clamp15Status", data["signals"])
        c15 = data["signals"]["Clamp15Status"]
        self.assertEqual(c15["message"], "Power_01")
        self.assertEqual(c15["start_bit"], 0)
        self.assertEqual(c15["length"], 1)

        self.assertIn("CellVoltageMax", data["signals"])
        cv_max = data["signals"]["CellVoltageMax"]
        self.assertEqual(cv_max["unit"], "V")
        self.assertEqual(cv_max["factor"], 0.001)
        self.assertEqual(cv_max["default"], 3.7)

        # Check VAL_ enums
        self.assertIn("BMSState", data["signals"])
        bms_state = data["signals"]["BMSState"]
        self.assertIn("values", bms_state)
        self.assertEqual(bms_state["values"]["3"], "DriveReady")
        self.assertEqual(bms_state["values"]["1"], "Standby")

        self.assertIn("InterlockStatus", data["signals"])
        self.assertEqual(data["signals"]["InterlockStatus"]["values"]["1"], "Geschlossen")

    def test_can_database_validation_clean(self):
        content = self.dbc_path.read_text(encoding="utf-8")
        data = dbc_to_dict(content)
        issues = validate_can_database(data)
        self.assertEqual(issues, [], f"Validation should find zero issues, got: {issues}")

    def test_validation_catches_dlc_overflow(self):
        bad_data = {
            "messages": {"TestMsg": {"id": "0x100", "dlc": 1}},
            "signals": {
                "TooLong": {
                    "message": "TestMsg",
                    "start_bit": 6,
                    "length": 4,  # bits 6..9 exceed dlc 1 (8 bits)
                    "factor": 1,
                    "min": 0,
                    "max": 15,
                }
            },
        }
        issues = validate_can_database(bad_data)
        self.assertEqual(len(issues), 1)
        self.assertIn("exceeds message 'TestMsg' DLC 1", issues[0])

    def test_validation_catches_bit_collision(self):
        bad_data = {
            "messages": {"TestMsg": {"id": "0x100", "dlc": 2}},
            "signals": {
                "SigA": {
                    "message": "TestMsg",
                    "start_bit": 0,
                    "length": 8,
                    "factor": 1,
                    "min": 0,
                    "max": 255,
                },
                "SigB": {
                    "message": "TestMsg",
                    "start_bit": 4,  # Overlaps bits 4..7 with SigA
                    "length": 4,
                    "factor": 1,
                    "min": 0,
                    "max": 15,
                },
            },
        }
        issues = validate_can_database(bad_data)
        self.assertTrue(any("collision" in iss.lower() for iss in issues))

    def test_roundtrip_conversion(self):
        # DBC -> Dict -> DBC -> Dict
        original_dbc = self.dbc_path.read_text(encoding="utf-8")
        dict1 = dbc_to_dict(original_dbc)

        generated_dbc = dict_to_dbc(dict1)
        dict2 = dbc_to_dict(generated_dbc)

        self.assertEqual(dict1["database"], dict2["database"])
        self.assertEqual(dict1["baudrate"], dict2["baudrate"])
        self.assertEqual(len(dict1["messages"]), len(dict2["messages"]))
        self.assertEqual(len(dict1["signals"]), len(dict2["signals"]))

        for msg_name, msg_data in dict1["messages"].items():
            self.assertIn(msg_name, dict2["messages"])
            self.assertEqual(msg_data["id"], dict2["messages"][msg_name]["id"])
            self.assertEqual(msg_data["dlc"], dict2["messages"][msg_name]["dlc"])

        for sig_name, sig_data in dict1["signals"].items():
            self.assertIn(sig_name, dict2["signals"])
            self.assertEqual(sig_data["start_bit"], dict2["signals"][sig_name]["start_bit"])
            self.assertEqual(sig_data["length"], dict2["signals"][sig_name]["length"])
            self.assertEqual(sig_data["unit"], dict2["signals"][sig_name]["unit"])

    def test_cli_execution(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = Path(tmpdir) / "output.json"
            cmd = [
                sys.executable,
                str(ROOT / "tools" / "dbc_to_json.py"),
                str(self.dbc_path),
                "-o",
                str(out_json),
                "--check",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(res.returncode, 0, f"CLI error: {res.stderr}")
            self.assertTrue(out_json.exists())

            data = json.loads(out_json.read_text(encoding="utf-8"))
            self.assertEqual(data["database"], "Powertrain_BMS_CAN")
            self.assertEqual(len(data["signals"]), 27)

    def test_symbolic_can_step_compilation_and_execution(self):
        """Verify that symbolic DBC enum names are compiled into correct Decimal values and executed."""
        mapping_entries = parse_mapping_document((ROOT / "inputs/operation_mapping.toml").read_text(encoding="utf-8"))
        mappings = load_mappings(mapping_entries, REGISTRY)
        profile = load_profile(ROOT / "inputs/resources.json")

        spec_text = """# TESTFALL: TC_SYMBOLIC_CAN
NAME: Symbolic CAN State Enum Test
## Precondition
10. CAN-Signal InterlockStatus auf Geschlossen setzen
## Action
20. CAN-Signal BMSState auf DriveReady setzen
30. CAN-Signal CoolingRequest auf "Stufe 2" setzen
## Expected Result
20. CAN-Signal BMSState ist DriveReady
30. CAN-Signal CoolingRequest ist "Stufe 2"
## Postcondition
40. CAN-Signal BMSState auf Standby setzen
"""
        sections = parse_text_spec(spec_text)
        cases = compile_cases(sections, mappings, profile, "test_symbolic.md")
        source = render_python(cases, REGISTRY, "VectorDummyBench")

        self.assertIn("signal='InterlockStatus', value=Decimal('1')", source)
        self.assertIn("signal='BMSState', value=Decimal('3')", source)
        self.assertIn("signal='CoolingRequest', value=Decimal('2')", source)

        # Execute on simulated Vector testbench
        bench = VectorDummyBench(load_config(ROOT / "inputs/demo_bench.json", profile))
        ns = {}
        exec(compile(source, "generated_symbolic_test.py", "exec"), ns)
        runner = ns["RUNNERS"]["TC_SYMBOLIC_CAN"]
        result = runner(bench)
        self.assertEqual(result.result, "PASS")
        self.assertEqual(bench.can_signals["BMSState"], 1)  # Cleanup left it in Standby (1)


if __name__ == "__main__":
    unittest.main()

