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

    def test_multi_mapping_files_save_preserves_origin_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            file_a = Path(tmpdir) / "mappings_a.toml"
            file_b = Path(tmpdir) / "mappings_b.toml"

            map_a = [{
                "id": "MAP_A",
                "template": "Aktion A {dauer}",
                "operation": "wait",
                "parameters": {"dauer": "seconds"}
            }]
            map_b = [{
                "id": "MAP_B",
                "template": "Aktion B {dauer}",
                "operation": "wait",
                "parameters": {"dauer": "seconds"}
            }]
            save_mapping_file(file_a, map_a)
            save_mapping_file(file_b, map_b)

            prof = ProjectProfile(
                id="multi_test",
                name="Multi Test",
                registry_target="operations.registry:REGISTRY",
                mapping_files=[str(file_a), str(file_b)],
                resources_file="inputs/resources.json",
                specs_dir="inputs",
            )
            state = MappingStudioState(project_profile=prof)
            self.assertEqual(len(state.mappings), 2)

            # Trigger save
            ok, msg = state.save_all_mapping_files()
            self.assertTrue(ok, msg)

            # Re-read raw files from disk
            raw_a, err_a = load_mapping_file(file_a)
            raw_b, err_b = load_mapping_file(file_b)
            self.assertIsNone(err_a)
            self.assertIsNone(err_b)

            # Verify File A has ONLY 1 mapping and File B has ONLY 1 mapping (no pollution!)
            self.assertEqual(len(raw_a), 1)
            self.assertEqual(raw_a[0]["id"], "MAP_A")

            self.assertEqual(len(raw_b), 1)
            self.assertEqual(raw_b[0]["id"], "MAP_B")


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

        # Workspace 2: Operationskatalog has operations list and templates table
        self.assertTrue(win.workspace_catalog.op_list.count() > 0)
        self.assertIsNotNone(win.workspace_catalog.btn_new_mapping)
        self.assertIsNotNone(win.workspace_catalog.btn_edit_mapping)
        # Verify sentence generator and insert button do NOT exist in CatalogWorkspace
        self.assertFalse(hasattr(win.workspace_catalog, 'btn_generate_sentence'))
        self.assertFalse(hasattr(win.workspace_catalog, 'btn_insert_spec'))

        # Switch profile to service pilot
        service_prof = next(p for p in win.builtin_profiles if p.id == "service_pilot")
        win.switch_project_profile(service_prof, prompt_save=False)

        # Verify profile updated across workspaces
        self.assertEqual(win.state.profile_config.id, "service_pilot")
        self.assertEqual(len(win.state.operations), 9)
        self.assertEqual(win.state.profile_config.specs_dir, "examples/service_pilot/inputs/specs")

    def test_operations_catalog_focused_inspection_and_management(self):
        win = MappingStudioWindow()
        catalog = win.workspace_catalog

        # 1. Select 'wait' operation
        catalog.select_operation_by_name("wait")
        self.assertEqual(catalog.current_op_name, "wait")
        self.assertTrue(catalog.table_templates.rowCount() > 0)

        # Details are updated
        self.assertIn("wait", catalog.lbl_op_title.text())
        self.assertIn("Warte {dauer}", catalog.table_templates.item(0, 1).text())

        # Verify buttons for mapping management are present and active
        self.assertTrue(catalog.btn_new_mapping.isEnabled())
        self.assertTrue(catalog.btn_edit_mapping.isEnabled())

        # Verify that catalog does NOT contain parameter inputs or step generation actions
        self.assertFalse(hasattr(catalog, 'param_inputs'))
        self.assertFalse(hasattr(catalog, 'lbl_generated_sentence'))
        self.assertFalse(hasattr(catalog, 'btn_insert_spec'))

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

    def test_step_assistant_phase_awareness_and_insertion(self):
        win = MappingStudioWindow()
        specs = win.workspace_specs
        assistant = specs.step_assistant

        # 1. Action phase
        assistant.set_phase("ACTION")
        self.assertEqual(assistant.current_phase, "ACTION")
        action_ops = [assistant.combo_ops.itemData(i) for i in range(assistant.combo_ops.count())]
        self.assertIn("wait", action_ops)
        self.assertIn("set_battery_voltage", action_ops)
        # Check operations like expect_fault_memory_entry should NOT be in Action
        self.assertNotIn("expect_fault_memory_entry", action_ops)

        # 2. Expected Result phase
        assistant.set_phase("EXPECTED_RESULT")
        self.assertEqual(assistant.current_phase, "EXPECTED_RESULT")
        check_ops = [assistant.combo_ops.itemData(i) for i in range(assistant.combo_ops.count())]
        self.assertIn("expect_fault_memory_entry", check_ops)
        self.assertNotIn("set_battery_voltage", check_ops)

        # 3. Parameter form and insertion
        specs.editor.setPlainText("# Test\n## Expected Result\n")
        specs.editor.moveCursor(specs.editor.textCursor().MoveOperation.End)

        idx = assistant.combo_ops.findData("expect_fault_memory_entry")
        assistant.combo_ops.setCurrentIndex(idx)
        assistant.on_operation_changed()

        # Check preview sentence and auto-verification
        preview_text = assistant.txt_preview.text()
        self.assertIn("Fehlerspeichereintrag", preview_text)
        self.assertIn("Gültig", assistant.lbl_verify.text())

        assistant.on_insert_clicked()
        self.assertIn(preview_text, specs.editor.toPlainText())

        # 4. Action phase insertion with typed quantity parameter (500 ms)
        specs.editor.setPlainText("# Test\n## Action\n")
        specs.editor.moveCursor(specs.editor.textCursor().MoveOperation.End)

        assistant.set_phase("ACTION")
        idx_wait = assistant.combo_ops.findData("wait")
        assistant.combo_ops.setCurrentIndex(idx_wait)
        assistant.on_operation_changed()

        param_widget = assistant.param_widgets.get("dauer")
        self.assertIsNotNone(param_widget)
        param_widget.spinbox.setValue(500)
        param_widget.unit_combo.setCurrentText("ms")
        assistant.update_preview_from_inputs()

        self.assertEqual(assistant.txt_preview.text().strip(), "Warte 500 ms")
        self.assertIn("Gültig", assistant.lbl_verify.text())
        assistant.on_insert_clicked()
        self.assertIn("Warte 500 ms", specs.editor.toPlainText())

    def test_background_analysis_revision_tracking(self):
        win = MappingStudioWindow()
        specs = win.workspace_specs
        mgr = specs.analysis_manager

        initial_rev = mgr.current_doc_revision

        # Schedule revision
        rev1 = mgr.schedule_doc_analysis(
            text="# Test\n## Action\n10. Warte 1 s",
            source_name="test_rev.md",
            registry=win.state.registry,
            mapping_dicts=win.state.get_mappings_dicts(),
            profile=win.state.profile,
        )
        self.assertEqual(rev1, initial_rev + 1)

        # Wait for thread pool to finish
        mgr.thread_pool.waitForDone(2000)
        self.app.processEvents()

        # Check status updated
        self.assertIn("Aktuell geprüft", specs.lbl_analysis_status.text())

        # Test stale result protection: If an older result arrives for a superseded revision
        older_res = CompilationFacade.compile_text(
            text="# Stale\n## Action\n10. Warte 2 s",
            source_name="stale.md",
            registry=win.state.registry,
            mapping_dicts=win.state.get_mappings_dicts(),
            profile=win.state.profile,
        )
        # Emit with obsolete revision (rev1 - 1)
        specs.on_doc_analysis_finished(older_res, revision=rev1 - 1)
        self.assertIn("Ergebnis veraltet", specs.lbl_analysis_status.text())

    def test_multi_tier_problem_list_filtering(self):
        win = MappingStudioWindow()
        specs = win.workspace_specs

        # Create a document with an error
        broken_spec = """# Broken
## Action
10. Unbekannter Befehl ohne Mapping 123
"""
        specs.editor.setPlainText(broken_spec)
        specs.compile_current_text(sync=True)

        # Verify problems recorded
        self.assertTrue(len(specs.all_problems) > 0)
        doc_probs = [p for p in specs.all_problems if p.level == "Dokument"]
        self.assertTrue(len(doc_probs) > 0)

        # Filter by Dokument
        specs.set_problem_filter("Dokument")
        self.assertEqual(specs.error_table.rowCount(), len(doc_probs))

        # Filter by Projekt
        specs.set_problem_filter("Projekt")
        proj_count = sum(1 for p in specs.all_problems if p.level == "Projekt")
        self.assertEqual(specs.error_table.rowCount(), proj_count)
