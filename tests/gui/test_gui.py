"""Tests for SpecToTest PySide6 GUI and data models."""
import os
from pathlib import Path
import tempfile
import unittest

# Ensure Qt runs offscreen for automated testing
os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication

from tcg.gui.app import MappingStudioWindow
from tcg.gui.dialog_editor import MappingEditorDialog
from tcg.gui.models import (
    MappingItem,
    MappingStudioState,
    extract_template_placeholders,
    load_registry_from_target,
    validate_single_mapping,
)
from tcg.gui.toml_io import load_mapping_file, save_mapping_file, serialize_mappings


class GuiModelsAndIOTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_extract_template_placeholders(self):
        placeholders = extract_template_placeholders("Versorgung auf {spannung} setzen für {dauer}")
        self.assertEqual(placeholders, ["spannung", "dauer"])

        empty = extract_template_placeholders("Zündung an")
        self.assertEqual(empty, [])

    def test_validate_single_mapping(self):
        registry = load_registry_from_target("operations.registry:REGISTRY")

        # Valid mapping
        ok, err, ph = validate_single_mapping(
            "MAP_TEST",
            "Batterie auf {volt} stellen",
            "set_battery_voltage",
            {"volt": "value"},
            registry,
        )
        self.assertTrue(ok)
        self.assertIsNone(err)
        self.assertEqual(ph, ["volt"])

        # Invalid ID (lowercase)
        ok, err, _ = validate_single_mapping(
            "map_bad",
            "Test",
            "set_battery_voltage",
            {},
            registry,
        )
        self.assertFalse(ok)
        self.assertIn("ungültig", err)

        # Unknown operation
        ok, err, _ = validate_single_mapping(
            "MAP_UNKNOWN",
            "Test",
            "non_existent_op",
            {},
            registry,
        )
        self.assertFalse(ok)
        self.assertIn("Unbekannte Operation", err)

        # Missing required parameter ('value' is required for set_battery_voltage)
        ok, err, _ = validate_single_mapping(
            "MAP_MISSING",
            "Batterie einschalten",
            "set_battery_voltage",
            {},
            registry,
        )
        self.assertFalse(ok)
        self.assertIn("Erforderliche Parameter der Operation nicht gemappt", err)

    def test_toml_io_roundtrip_and_backup(self):
        source_file = Path("inputs/operation_mapping.toml")
        mappings, err = load_mapping_file(source_file)
        self.assertIsNone(err)
        self.assertEqual(len(mappings), 27)

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir) / "test_mapping.toml"

            # Save initial
            success, msg = save_mapping_file(tmp_path, mappings, create_backup=True)
            self.assertTrue(success)
            self.assertTrue(tmp_path.exists())

            # Modify and save again, checking backup creation
            mappings_modified = list(mappings)
            mappings_modified.append({
                "id": "MAP_CUSTOM_NEW",
                "template": "Warte kurz {dauer}",
                "operation": "wait",
                "parameters": {"dauer": "seconds"},
            })
            success, msg = save_mapping_file(tmp_path, mappings_modified, create_backup=True)
            self.assertTrue(success)

            # Check backup file exists
            backup_file = tmp_path.with_suffix(".toml.bak")
            self.assertTrue(backup_file.exists())

            # Read back modified
            reloaded, err = load_mapping_file(tmp_path)
            self.assertIsNone(err)
            self.assertEqual(len(reloaded), 28)
            self.assertEqual(reloaded[-1]["id"], "MAP_CUSTOM_NEW")

    def test_sentence_tester_playground(self):
        state = MappingStudioState(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )

        # Match valid sentence
        res = state.test_sentence("Batteriespannung = 13.8V")
        self.assertTrue(res["success"])
        self.assertTrue(res["matched"])
        self.assertEqual(res["operation"], "set_battery_voltage")
        self.assertTrue(res["phase_valid"])

        # Match with incompatible phase
        res_conflict = state.test_sentence("Batteriespannung = 13.8V", phase="EXPECTED")
        self.assertTrue(res_conflict["success"])
        self.assertFalse(res_conflict["phase_valid"])
        self.assertIn("EXPECTED", res_conflict["phase_msg"])

        # Unmatched sentence
        res_fail = state.test_sentence("Unbekannter Satz der nirgends existiert")
        self.assertFalse(res_fail["success"])
        self.assertIn("no mapping", res_fail["error"])


class GuiWindowIntegrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_main_window_tabs_and_views(self):
        win = MappingStudioWindow(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )
        self.assertEqual(win.tabs.count(), 3)

        # 1. Mappings View
        table_mappings = win.view_mappings.table
        self.assertEqual(table_mappings.rowCount(), 27)

        # Filter Mappings table
        win.view_mappings.search_edit.setText("CAN")
        filtered_count = table_mappings.rowCount()
        self.assertTrue(0 < filtered_count < 27)
        win.view_mappings.search_edit.clear()
        self.assertEqual(table_mappings.rowCount(), 27)

        # 2. Operations View ("Vice Versa")
        table_ops = win.view_operations.table
        self.assertEqual(table_ops.rowCount(), 24)

        # 3. Add a mapping dynamically and verify both views update
        new_item = MappingItem(
            id="MAP_EXTRA_WAIT",
            template="Pause machen {zeit}",
            operation="wait",
            parameters={"zeit": "seconds"},
        )
        win.state.add_mapping(new_item)
        win.on_state_changed()

        self.assertEqual(win.view_mappings.table.rowCount(), 28)
        self.assertTrue(win.state.is_dirty)

        # 4. Switch registry to Service Pilot
        win.switch_registry(
            "examples.service_pilot.registry:SERVICE_REGISTRY",
            "examples/service_pilot/inputs/resources.json",
            prompt_save=False,
        )
        self.assertEqual(len(win.state.operations), 9)

    def test_editor_dialog_preselected_operation(self):
        registry = load_registry_from_target("operations.registry:REGISTRY")
        dialog = MappingEditorDialog(
            registry=registry,
            preselected_operation="set_supply",
        )
        self.assertEqual(dialog.op_combo.currentData(), "set_supply")

        # Set template and verify bindings
        dialog.template_edit.setText("Stromversorgung auf {volt} regeln")
        dialog.on_template_changed()
        self.assertEqual(dialog.binding_table.rowCount(), 1)

        result = dialog.get_result_item()
        self.assertEqual(result.operation, "set_supply")
        self.assertEqual(result.parameters, {"volt": "value"})
        self.assertTrue(dialog.btn_ok.isEnabled())
