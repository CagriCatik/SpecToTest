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
from operations.can_catalog import load_can_signal_catalog
from operations.registry import build_operations_registry
from tcg.adapters.inbound.text_parser import parse_text_spec
from tcg.adapters.outbound.dummy_bench import VectorDummyBench, load_config
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.mapping import load_mappings, parse_mapping_document
from tcg.core.model import SpecError
from tcg.core.profile import load_profile

ROOT = Path(__file__).resolve().parent.parent.parent

# The demo project references its demo database explicitly; nothing is implicit.
DEMO_CAN_DATABASE = ROOT / "inputs" / "can_signals.json"


def demo_registry():
    """An operation registry bound to the shipped demo CAN signal catalog."""
    return build_operations_registry(
        can_catalog=load_can_signal_catalog(DEMO_CAN_DATABASE))


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
        registry = demo_registry()
        mappings = load_mappings(mapping_entries, registry)
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
        source = render_python(cases, registry, "VectorDummyBench")

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

    def test_signal_dependent_enum_resolution_opposite_mappings(self):
        """Verify that identical state names resolve to their respective signal's value in DBC.
        
        DoorContactStatus: Geschlossen -> 0, Offen -> 1
        InterlockStatus:   Geschlossen -> 1, Offen -> 0
        """
        mapping_entries = parse_mapping_document((ROOT / "inputs/operation_mapping.toml").read_text(encoding="utf-8"))
        registry = demo_registry()
        mappings = load_mappings(mapping_entries, registry)
        profile = load_profile(ROOT / "inputs/resources.json")

        spec_text = """# TESTFALL: TC_OPPOSITE_ENUMS
NAME: Opposite Enums Test
## Action
10. CAN-Signal DoorContactStatus auf Geschlossen setzen
20. CAN-Signal InterlockStatus auf Geschlossen setzen
30. CAN-Signal DoorContactStatus auf Offen setzen
40. CAN-Signal InterlockStatus auf Offen setzen
## Expected Result
10. CAN-Signal DoorContactStatus ist Geschlossen
20. CAN-Signal InterlockStatus ist Geschlossen
30. CAN-Signal DoorContactStatus ist Offen
40. CAN-Signal InterlockStatus ist Offen
"""
        sections = parse_text_spec(spec_text)
        cases = compile_cases(sections, mappings, profile, "test_opposite.md")
        source = render_python(cases, registry, "VectorDummyBench")

        # Step 10: DoorContactStatus Geschlossen -> must be Decimal('0')
        self.assertIn("_op_can.set_can_signal(bench, signal='DoorContactStatus', value=Decimal('0'))", source)
        self.assertIn("_op_can.expect_can_signal(bench, signal='DoorContactStatus', value=Decimal('0'))", source)

        # Step 20: InterlockStatus Geschlossen -> must be Decimal('1')
        self.assertIn("_op_can.set_can_signal(bench, signal='InterlockStatus', value=Decimal('1'))", source)
        self.assertIn("_op_can.expect_can_signal(bench, signal='InterlockStatus', value=Decimal('1'))", source)

        # Step 30: DoorContactStatus Offen -> must be Decimal('1')
        self.assertIn("_op_can.set_can_signal(bench, signal='DoorContactStatus', value=Decimal('1'))", source)
        self.assertIn("_op_can.expect_can_signal(bench, signal='DoorContactStatus', value=Decimal('1'))", source)

        # Step 40: InterlockStatus Offen -> must be Decimal('0')
        self.assertIn("_op_can.set_can_signal(bench, signal='InterlockStatus', value=Decimal('0'))", source)
        self.assertIn("_op_can.expect_can_signal(bench, signal='InterlockStatus', value=Decimal('0'))", source)

        # Execution check
        bench = VectorDummyBench(load_config(ROOT / "inputs/demo_bench.json", profile))
        ns = {}
        exec(compile(source, "generated_opposite_test.py", "exec"), ns)
        runner = ns["RUNNERS"]["TC_OPPOSITE_ENUMS"]
        result = runner(bench)
        self.assertEqual(result.result, "PASS")

    def test_signal_dependent_enum_rejects_incompatible_states(self):
        """Verify that states belonging to one signal cannot be used on unrelated signals."""
        mapping_entries = parse_mapping_document((ROOT / "inputs/operation_mapping.toml").read_text(encoding="utf-8"))
        registry = demo_registry()
        mappings = load_mappings(mapping_entries, registry)
        profile = load_profile(ROOT / "inputs/resources.json")

        # 1. Continuous signal (VehicleSpeed) rejects discrete state (DriveReady)
        spec_continuous = """# TESTFALL: TC_ERR_1
NAME: Speed Error Test
## Action
10. CAN-Signal VehicleSpeed auf DriveReady setzen
"""
        with self.assertRaises(SpecError) as ctx:
            compile_cases(parse_text_spec(spec_continuous), mappings, profile, "test_err1.md")
        self.assertIn("Zustand 'DriveReady' ist für CAN-Signal 'VehicleSpeed'", str(ctx.exception))
        self.assertIn("nicht gültig", str(ctx.exception))

        # 2. Discrete signal (DoorContactStatus) rejects state from BMSState (DriveReady)
        spec_wrong_discrete = """# TESTFALL: TC_ERR_2
NAME: Door Wrong State Test
## Action
10. CAN-Signal DoorContactStatus auf DriveReady setzen
"""
        with self.assertRaises(SpecError) as ctx:
            compile_cases(parse_text_spec(spec_wrong_discrete), mappings, profile, "test_err2.md")
        self.assertIn("Zustand 'DriveReady' ist für CAN-Signal 'DoorContactStatus'", str(ctx.exception))
        self.assertIn("nicht gültig", str(ctx.exception))
        self.assertIn("Geschlossen", str(ctx.exception))
        self.assertIn("Offen", str(ctx.exception))

        # 3. BMSState rejects DoorContactStatus state (Geschlossen)
        spec_bms_wrong = """# TESTFALL: TC_ERR_3
NAME: BMS Wrong State Test
## Action
10. CAN-Signal BMSState auf Geschlossen setzen
"""
        with self.assertRaises(SpecError) as ctx:
            compile_cases(parse_text_spec(spec_bms_wrong), mappings, profile, "test_err3.md")
        self.assertIn("Zustand 'Geschlossen' ist für CAN-Signal 'BMSState'", str(ctx.exception))
        self.assertIn("nicht gültig", str(ctx.exception))

    def test_inverted_template_order_and_context_isolation(self):
        """Verify that mappings with inverted placeholder order ({value} before {signal}) resolve
        strictly based on the sentence's own signal and without sentence-to-sentence context leakage.
        """
        inverted_toml = """
[[mapping]]
id = "MAP_INVERTED_SET"
template = "Wert {wert} an CAN-Signal {signal} setzen"
operation = "set_can_signal"
parameters = { wert = "value", signal = "signal" }

[[mapping]]
id = "MAP_INVERTED_EXPECT"
template = "Wert {wert} für CAN-Signal {signal} erwartet"
operation = "expect_can_signal"
parameters = { wert = "value", signal = "signal" }
"""
        mapping_entries = parse_mapping_document(inverted_toml)
        registry = demo_registry()
        mappings = load_mappings(mapping_entries, registry)
        profile = load_profile(ROOT / "inputs/resources.json")

        spec_text = """# TESTFALL: TC_INVERTED_ORDER
NAME: Inverted Placeholder Order and Sentence Context Isolation Test
## Action
10. Wert Geschlossen an CAN-Signal InterlockStatus setzen
20. Wert Geschlossen an CAN-Signal DoorContactStatus setzen
## Expected Result
10. Wert Geschlossen für CAN-Signal InterlockStatus erwartet
20. Wert Geschlossen für CAN-Signal DoorContactStatus erwartet
"""
        sections = parse_text_spec(spec_text)
        cases = compile_cases(sections, mappings, profile, "test_inverted.md")
        source = render_python(cases, registry, "VectorDummyBench")

        # Step 10: InterlockStatus Geschlossen must be Decimal('1')
        self.assertIn("_op_can.set_can_signal(bench, signal='InterlockStatus', value=Decimal('1'))", source)
        self.assertIn("_op_can.expect_can_signal(bench, signal='InterlockStatus', value=Decimal('1'))", source)

        # Step 20: DoorContactStatus Geschlossen must be Decimal('0') (NOT influenced by step 10's InterlockStatus!)
        self.assertIn("_op_can.set_can_signal(bench, signal='DoorContactStatus', value=Decimal('0'))", source)
        self.assertIn("_op_can.expect_can_signal(bench, signal='DoorContactStatus', value=Decimal('0'))", source)

        # Execute on simulated Vector testbench
        bench = VectorDummyBench(load_config(ROOT / "inputs/demo_bench.json", profile))
        ns = {}
        exec(compile(source, "generated_inverted_test.py", "exec"), ns)
        runner = ns["RUNNERS"]["TC_INVERTED_ORDER"]
        result = runner(bench)
        self.assertEqual(result.result, "PASS")

    def test_database_isolation_no_demo_leakage(self):
        """A custom database is authoritative: no demo state leaks into it."""
        custom_db = {
            "database": "Custom_Isolation_CAN",
            "baudrate": 500000,
            "messages": {
                "Body_Custom": {"id": "0x200", "dlc": 8},
                "Other_Custom": {"id": "0x210", "dlc": 8},
            },
            "signals": {
                "DoorContactStatus": {
                    "message": "Body_Custom", "start_bit": 0, "length": 1,
                    "values": {"0": "Zu", "1": "Auf"},
                },
                "OtherSignal": {
                    "message": "Other_Custom", "start_bit": 0, "length": 1,
                    "values": {"0": "Geschlossen", "1": "Offen"},
                },
            },
        }
        registry = build_operations_registry(
            can_catalog=load_can_signal_catalog(custom_db, name="custom.json"))

        custom_toml = """
[[mapping]]
id = "MAP_CAN_SET"
template = "CAN-Signal {signal} auf {wert} setzen"
operation = "set_can_signal"
parameters = { signal = "signal", wert = "value" }
"""
        mappings = load_mappings(parse_mapping_document(custom_toml), registry)
        profile = load_profile(ROOT / "inputs/resources.json")

        # 1. A state this database defines must compile to its declared raw value.
        valid_spec = """# TESTFALL: TC_CUSTOM_VALID
NAME: Custom DB Valid
## Action
10. CAN-Signal DoorContactStatus auf Zu setzen
"""
        cases = compile_cases(parse_text_spec(valid_spec), mappings, profile, "custom_valid.md")
        source = render_python(cases, registry, "VectorDummyBench")
        self.assertIn("signal='DoorContactStatus', value=Decimal('0')", source)

        # 2. 'Geschlossen' belongs to OtherSignal, so DoorContactStatus must reject it.
        invalid_spec = """# TESTFALL: TC_CUSTOM_INVALID
NAME: Custom DB Invalid
## Action
10. CAN-Signal DoorContactStatus auf Geschlossen setzen
"""
        with self.assertRaises(SpecError) as ctx:
            compile_cases(parse_text_spec(invalid_spec), mappings, profile, "custom_invalid.md")
        message = str(ctx.exception)
        self.assertIn("Zustand 'Geschlossen' ist für CAN-Signal 'DoorContactStatus'", message)
        self.assertIn("nicht gültig", message)
        self.assertIn("Custom_Isolation_CAN", message)
        self.assertIn("Zu", str(ctx.exception))
        self.assertIn("Auf", str(ctx.exception))

        # 3. A state no signal declares is rejected as an undefined identifier.
        unknown_spec = """# TESTFALL: TC_CUSTOM_UNKNOWN
NAME: Custom DB Unknown
## Action
10. CAN-Signal DoorContactStatus auf Vollgas setzen
"""
        with self.assertRaises(SpecError) as ctx:
            compile_cases(parse_text_spec(unknown_spec), mappings, profile, "custom_unknown.md")
        self.assertIn("Vollgas", str(ctx.exception))

        # 4. The demo registry built separately is unaffected by the custom one.
        demo = demo_registry()
        demo_mappings = load_mappings(parse_mapping_document(custom_toml), demo)
        demo_spec = """# TESTFALL: TC_DEMO_STILL_OK
NAME: Demo DB untouched
## Action
10. CAN-Signal DoorContactStatus auf Geschlossen setzen
"""
        demo_cases = compile_cases(parse_text_spec(demo_spec), demo_mappings, profile, "demo.md")
        self.assertIn("signal='DoorContactStatus', value=Decimal('0')",
                      render_python(demo_cases, demo, "VectorDummyBench"))

    def test_corrupt_and_missing_can_database_handling(self):
        """Missing files, corrupt JSON and invalid schemas raise visible SpecErrors."""
        # 1. Missing file.
        with self.assertRaises(SpecError) as ctx:
            load_can_signal_catalog(Path("/non/existent/path/never_there_signals.json"))
        self.assertIn("never_there_signals.json", str(ctx.exception))

        # 2. Corrupt JSON file.
        with tempfile.TemporaryDirectory() as tmpdir:
            broken_file = Path(tmpdir) / "broken.json"
            broken_file.write_text("{ this is not valid json }", encoding="utf-8")
            with self.assertRaises(SpecError) as ctx:
                load_can_signal_catalog(broken_file)
            self.assertIn("broken.json", str(ctx.exception))
            self.assertIn("JSON", str(ctx.exception))

        # 3. Invalid schema without a 'signals' key.
        with self.assertRaises(SpecError) as ctx:
            load_can_signal_catalog({"database": "BadSchema"}, name="bad.json")
        self.assertIn("signals", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

