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

        # Check Action <-> Expectation linking (Action step 20 at line 6 links to Expectation step 20 at line 10)
        self.assertEqual(step_action.linked_step_line, 10)
        step_exp = result.steps_by_line.get(10)
        self.assertIsNotNone(step_exp)
        self.assertEqual(step_exp.linked_step_line, 6)

    def test_compilation_facade_rejects_duplicate_mapping_ids(self):
        state = MappingStudioState(
            registry_target="operations.registry:REGISTRY",
            mapping_file="inputs/operation_mapping.toml",
            resources_file="inputs/resources.json",
        )
        mapping_dicts = [m.to_dict() for m in state.mappings if m.is_valid and not m.has_conflict]
        # Inject duplicate mapping id
        dup_dict = dict(mapping_dicts[0])
        mapping_dicts.append(dup_dict)

        result = CompilationFacade.compile_text(
            text="# Test\n## Action\n10. Warte 1 s",
            source_name="dup_test.md",
            registry=state.registry,
            mapping_dicts=mapping_dicts,
            profile=state.profile,
        )
        self.assertFalse(result.success)
        self.assertTrue(any("mehrfach definiert" in err.message for err in result.errors))

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

        # Workspace 2: Unified Catalog has operations list and templates table
        self.assertTrue(win.workspace_catalog.op_list.count() > 0)
        self.assertIsNotNone(win.workspace_catalog.btn_generate_sentence)
        self.assertIsNotNone(win.workspace_catalog.btn_insert_spec)

        # Switch profile to service pilot
        service_prof = next(p for p in win.builtin_profiles if p.id == "service_pilot")
        win.switch_project_profile(service_prof, prompt_save=False)

        # Verify profile updated across workspaces
        self.assertEqual(win.state.profile_config.id, "service_pilot")
        self.assertEqual(len(win.state.operations), 9)
        self.assertEqual(win.state.profile_config.specs_dir, "examples/service_pilot/inputs/specs")

    def test_vice_versa_sentence_generation_and_insertion(self):
        win = MappingStudioWindow()
        catalog = win.workspace_catalog

        # 1. Select 'wait' operation
        catalog.select_operation_by_name("wait")
        self.assertEqual(catalog.current_op_name, "wait")
        self.assertTrue(catalog.table_templates.rowCount() > 0)

        # Select first template: 'Warte {dauer}'
        catalog.table_templates.selectRow(0)

        # Set parameter: 500 ms
        param_widget = catalog.param_inputs.get("dauer")
        self.assertIsNotNone(param_widget)
        # It's a QuantityWidget with spinbox and unit_combo
        param_widget.spinbox.setValue(500)
        param_widget.unit_combo.setCurrentText("ms")

        # 2. Generate sentence
        catalog.generate_vice_versa_sentence()
        generated = catalog.txt_preview_sentence.text().strip()
        self.assertEqual(generated, "Warte 500 ms")

        # 3. Verify reverse resolution proof
        ok, op_name, args, err = catalog.verify_generated_sentence(generated)
        self.assertTrue(ok)
        self.assertEqual(op_name, "wait")
        from decimal import Decimal
        self.assertEqual(args.get("seconds"), Decimal("0.500"))

        # 4. Insert into open specification
        initial_text = win.workspace_specs.editor.toPlainText()
        catalog.insert_into_active_specification()

        # Should switch to Spezifikationen tab (index 0) and contain the sentence
        self.assertEqual(win.tabs.currentIndex(), 0)
        new_text = win.workspace_specs.editor.toPlainText()
        self.assertIn("Warte 500 ms", new_text)
        self.assertTrue(win.workspace_specs.is_spec_dirty)

    def test_specification_dirty_tracking(self):
        win = MappingStudioWindow()
        specs = win.workspace_specs
        self.assertFalse(specs.is_spec_dirty)

        # Simulate user typing
        specs.editor.insertPlainText("\n# Dirty test comment")
        self.assertTrue(specs.is_spec_dirty)

        # Reset without disk save
        specs.is_spec_dirty = False
        self.assertFalse(specs.is_spec_dirty)

    def test_transactional_profile_switch_rejects_broken_profile(self):
        win = MappingStudioWindow()
        initial_id = win.state.profile_config.id

        broken_prof = ProjectProfile(
            id="broken_profile",
            name="Broken",
            registry_target="non_existent_module.invalid:NONE",
            mapping_files=["inputs/operation_mapping.toml"],
            resources_file="inputs/resources.json",
            specs_dir="inputs",
        )

        ok, err = win.state.set_project_profile(broken_prof)
        self.assertFalse(ok)
        self.assertIn("non_existent_module", err)
        # Ensure state was not corrupted
        self.assertEqual(win.state.profile_config.id, initial_id)
        self.assertEqual(len(win.state.operations), 24)

    def test_action_expectation_navigation(self):
        win = MappingStudioWindow()
        specs = win.workspace_specs

        spec_sample = """# TC_NAV
## Action
10. Batteriespannung = 12V

## Expected Result
10. Fehlerspeichereintrag DTC00173 eingetragen
"""
        specs.editor.setPlainText(spec_sample)
        specs.compile_current_text()

        # Place cursor on line 3 ("10. Batteriespannung = 12V")
        cursor = specs.editor.textCursor()
        cursor.setPosition(specs.editor.document().findBlockByNumber(2).position())
        specs.editor.setTextCursor(cursor)
        specs.inspect_current_line()

        # Check linked line is line 6 (index 5)
        self.assertIsNotNone(specs.current_linked_line)
        self.assertEqual(specs.current_linked_line, 6)

        # Jump to linked line
        specs.jump_to_linked_line()
        current_cursor_line = specs.editor.textCursor().blockNumber() + 1
        self.assertEqual(current_cursor_line, 6)
