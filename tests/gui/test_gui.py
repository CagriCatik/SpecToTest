"""Comprehensive tests for SpecToTest Studio, project profiles, and compilation inspection."""
import os
from pathlib import Path
import tempfile
import unittest

os.environ['QT_QPA_PLATFORM'] = 'offscreen'

from PySide6.QtWidgets import QApplication

from tcg.gui.app import MappingStudioWindow
from tcg.gui.dialog_editor import MappingEditorDialog
from tcg.gui.facade import CompilationFacade
from tcg.gui.models import (
    MappingItem,
    MappingStudioState,
    extract_template_placeholders,
    load_registry_from_target,
    validate_single_mapping,
)
from tcg.gui.profiles import ProjectProfile, get_builtin_profiles
from tcg.gui.toml_io import load_mapping_file, save_mapping_file


class GuiValidationAndConflictTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_duplicate_mapping_id_conflict_is_flagged(self):
        state = MappingStudioState(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )

        # Add two mappings with identical ID
        dup1 = MappingItem(
            id="MAP_CONFLICT_TEST",
            template="Konflikt Test eins {dauer}",
            operation="wait",
            parameters={"dauer": "seconds"},
        )
        dup2 = MappingItem(
            id="MAP_CONFLICT_TEST",
            template="Konflikt Test zwei {dauer}",
            operation="wait",
            parameters={"dauer": "seconds"},
        )
        state.add_mapping(dup1)
        state.add_mapping(dup2)

        # Both items must be marked as invalid with conflict error
        conflict_items = [m for m in state.mappings if m.id == "MAP_CONFLICT_TEST"]
        self.assertEqual(len(conflict_items), 2)
        for item in conflict_items:
            self.assertTrue(item.has_conflict)
            self.assertFalse(item.is_valid)
            self.assertIn("Konflikt: Mapping-ID 'MAP_CONFLICT_TEST' ist mehrfach vergeben", item.validation_error)

    def test_contextual_variable_in_sentence_matcher(self):
        state = MappingStudioState(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )

        # 1. 'Warte missing': should match template structurally, but flag that variable needs loop context
        res_var = state.test_sentence("Warte missing")
        self.assertTrue(res_var["success"])
        self.assertTrue(res_var["matched"])
        self.assertTrue(res_var["is_contextual_variable"])
        self.assertFalse(res_var["phase_valid"])
        self.assertEqual(res_var["variable_names"], ["missing"])
        self.assertIn("Variable 'missing' benötigt einen gültigen Kontext (z.B. Schleife)", res_var["status_text"])

        # 2. 'Warte 5 s': fully resolved literal value
        res_lit = state.test_sentence("Warte 5 s")
        self.assertTrue(res_lit["success"])
        self.assertTrue(res_lit["matched"])
        self.assertFalse(res_lit["is_contextual_variable"])
        self.assertTrue(res_lit["phase_valid"])
        self.assertIn("vollständig validiert", res_lit["status_text"])

    def test_operations_coverage_ignores_invalid_mappings(self):
        state = MappingStudioState(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )

        # Create an artificial operation with only an invalid mapping
        op_info = state.operations.get("wait")
        self.assertIsNotNone(op_info)
        self.assertTrue(op_info.is_mapped)

        # If all mappings for an operation are conflicting/invalid, it must count as unmapped (Lücke)
        invalid_item = MappingItem(
            id="MAP_INVALID_ONLY",
            template="Invalid wait {wrong}",
            operation="wait",
            parameters={"wrong": "seconds"},
            is_valid=False,
            has_conflict=True,
        )
        op_info.linked_mappings = [invalid_item]
        self.assertFalse(op_info.is_mapped)

    def test_project_profile_switch_consistency(self):
        profiles = {p.id: p for p in get_builtin_profiles()}
        state = MappingStudioState(project_profile=profiles['automotive_hil'])
        self.assertEqual(len(state.operations), 24)
        self.assertEqual(state.profile_config.specs_dir, 'inputs')

        # Switch to service pilot
        state.set_project_profile(profiles['service_pilot'])
        self.assertEqual(len(state.operations), 9)
        self.assertEqual(state.profile_config.specs_dir, 'examples/service_pilot/inputs/specs')
        self.assertEqual(state.mapping_file.name, 'mapping.toml')


class GuiFacadeAndInspectionTests(unittest.TestCase):

    def test_compilation_facade_and_step_inspection(self):
        state = MappingStudioState(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )
        mapping_dicts = [m.to_dict() for m in state.mappings if m.is_valid and not m.has_conflict]

        spec_content = """# Testfall TC_INSPECT
## Precondition
10. Zündung an

## Action
20. Batteriespannung = 7000mV
30. Warte 1 s

## Expected Result
20. Fehlerspeichereintrag DTC00173 eingetragen
"""
        result = CompilationFacade.compile_text(
            text=spec_content,
            source_name="tc_inspect.md",
            registry=state.registry,
            mapping_dicts=mapping_dicts,
            profile=state.profile,
        )

        self.assertTrue(result.success, f"Compilation failed: {result.summary}")
        self.assertEqual(len(result.cases), 1)
        self.assertIn("def run_tc_inspect", result.python_code)

        # Inspect line 6: "20. Batteriespannung = 7000mV"
        step_action = result.steps_by_line.get(6)
        self.assertIsNotNone(step_action)
        self.assertEqual(step_action.mapping_id, "MAP_BATTERY_VOLTAGE")
        self.assertEqual(step_action.operation_name, "set_battery_voltage")
        # Parameter normalized from 7000mV to Decimal('7.000')
        from decimal import Decimal
        self.assertEqual(step_action.arguments["value"], Decimal('7'))
        self.assertIn("set_battery_voltage(bench, value=Decimal('7.000'))", step_action.rendered_call)

    def test_impact_analysis_counts(self):
        state = MappingStudioState(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )
        specs_files = CompilationFacade.list_spec_files("inputs")
        self.assertTrue(len(specs_files) > 0)

        mapping_dicts = [m.to_dict() for m in state.mappings if m.is_valid and not m.has_conflict]
        impacts = CompilationFacade.analyze_impact(
            specs_files=specs_files,
            registry=state.registry,
            mapping_dicts=mapping_dicts,
            profile=state.profile,
        )

        # Core mappings like MAP_BATTERY_VOLTAGE or MAP_WAIT must have positive usage counts
        self.assertIn("MAP_WAIT", impacts)
        self.assertIn("MAP_BATTERY_VOLTAGE", impacts)
        wait_impact = impacts["MAP_WAIT"]
        self.assertTrue(wait_impact.total_usages > 0)
        self.assertTrue(len(wait_impact.affected_cases) > 0)


class GuiWindowWorkspacesIntegrationTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_studio_window_workspaces_and_profile_switch(self):
        win = MappingStudioWindow()
        self.assertEqual(win.tabs.count(), 3)
        self.assertEqual(win.tabs.tabText(0), "Spezifikationen")
        self.assertEqual(win.tabs.tabText(1), "Operationskatalog")
        self.assertEqual(win.tabs.tabText(2), "Satzprüfung")

        # Workspace 1: Spezifikationen loaded files
        specs_count = win.workspace_specs.file_list.count()
        self.assertTrue(specs_count > 0)

        # Verify current loaded file in editor
        self.assertIsNotNone(win.workspace_specs.current_spec_path)
        self.assertTrue(len(win.workspace_specs.editor.toPlainText()) > 0)

        # Workspace 2: Catalog has Mappings and Operations sub-tabs
        self.assertEqual(win.workspace_catalog.sub_tabs.count(), 2)

        # Switch profile to service pilot
        service_prof = next(p for p in win.builtin_profiles if p.id == "service_pilot")
        win.switch_project_profile(service_prof, prompt_save=False)

        # Verify profile updated across workspaces
        self.assertEqual(win.state.profile_config.id, "service_pilot")
        self.assertEqual(len(win.state.operations), 9)
        self.assertEqual(win.state.profile_config.specs_dir, "examples/service_pilot/inputs/specs")
