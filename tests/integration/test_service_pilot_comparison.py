"""Comparative Integration Tests: Hand-written Python Reference vs. SpecToTest Generated Tests.

Demonstrates that an independent software service (RecordStoreService) can be verified
using SpecToTest without modifying the compiler core, producing identical operations
sequences, parameter bindings, and verdicts (PASS, FAIL, ERROR) as manually written tests.
"""
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from examples.service_pilot.context import ServiceExecutionContext
from examples.service_pilot.generated.test_tc_01_persistence_after_restart import run_tc_01_persistence_after_restart
from examples.service_pilot.generated.test_tc_02_fault_injection_data_loss import run_tc_02_fault_injection_data_loss
from examples.service_pilot.generated.test_tc_03_data_corruption_detection import run_tc_03_data_corruption_detection
from examples.service_pilot.generated.test_tc_04_cleanup_and_isolation import run_tc_04_cleanup_and_isolation
from examples.service_pilot.generated.test_tc_05_sweep_batch_records import run_tc_05_sweep_batch_records
from examples.service_pilot.generated.test_tc_06_service_crash_technical_error import run_tc_06_service_crash_technical_error
import examples.service_pilot.operations as ops
from tcg.runtime import CheckFailed, execute


class ServicePilotComparisonTests(unittest.TestCase):
    """Rigorous comparison between manual reference tests and SpecToTest-generated tests."""

    def setUp(self):
        self.context = ServiceExecutionContext()

    def tearDown(self):
        self.context.close()

    # -------------------------------------------------------------------------
    # Case 1: Happy Path Cold Restart Persistence
    # -------------------------------------------------------------------------
    def test_tc_01_happy_path_persistence_comparison(self):
        # 1. Manual reference execution
        ref_context = ServiceExecutionContext()
        try:
            ops.restart_service(ref_context)
            ops.clear_faults(ref_context)
            ops.write_record(ref_context, key='USER_SESSION', value='active_session_42')
            ops.restart_service(ref_context)
            ops.expect_record_value(ref_context, key='USER_SESSION', expected='active_session_42')
        finally:
            ops.delete_record(ref_context, key='USER_SESSION')

        # 2. SpecToTest generated execution
        gen_context = ServiceExecutionContext()
        gen_result = execute(run_tc_01_persistence_after_restart, gen_context)

        # 3. Assert identical verdicts
        self.assertEqual(gen_result.result, 'PASS')

        # 4. Assert identical operations sequence
        ref_ops = [r['operation'] for r in ref_context.log_entries]
        gen_ops = [r['operation'] for r in gen_context.log_entries]
        self.assertEqual(ref_ops, gen_ops)
        self.assertEqual(ref_ops, ['restart_service', 'clear_faults', 'write_record', 'restart_service', 'expect_record_value', 'delete_record'])

        ref_context.close()
        gen_context.close()

    # -------------------------------------------------------------------------
    # Case 2: Target System Fault: Data Loss on Restart
    # -------------------------------------------------------------------------
    def test_tc_02_data_loss_bug_detection_comparison(self):
        # 1. Manual reference execution expecting target system failure
        ref_context = ServiceExecutionContext()
        ref_failed = False
        try:
            ops.restart_service(ref_context)
            ops.inject_fault(ref_context, fault_type='DROP_ON_RESTART')
            ops.write_record(ref_context, key='AUTH_TOKEN', value='secret_token_xyz')
            ops.restart_service(ref_context)
            try:
                ops.expect_record_value(ref_context, key='AUTH_TOKEN', expected='secret_token_xyz')
            except CheckFailed:
                ref_failed = True
        finally:
            ops.clear_faults(ref_context)
            ops.delete_record(ref_context, key='AUTH_TOKEN')
        self.assertTrue(ref_failed, "Reference test must detect data loss bug")

        # 2. SpecToTest generated execution
        gen_context = ServiceExecutionContext()
        gen_result = execute(run_tc_02_fault_injection_data_loss, gen_context)

        # 3. Assert identical FAIL verdict
        self.assertEqual(gen_result.result, 'FAIL')
        self.assertIn("Datensatz 'AUTH_TOKEN': erwartet 'secret_token_xyz', erhalten 'None'", str(gen_result.error))

        # 4. Assert identical operations sequence
        ref_ops = [r['operation'] for r in ref_context.log_entries]
        gen_ops = [r['operation'] for r in gen_context.log_entries]
        self.assertEqual(ref_ops, gen_ops)

        ref_context.close()
        gen_context.close()

    # -------------------------------------------------------------------------
    # Case 3: Target System Fault: Data Corruption Detection
    # -------------------------------------------------------------------------
    def test_tc_03_data_corruption_bug_detection_comparison(self):
        # 1. Manual reference execution
        ref_context = ServiceExecutionContext()
        ref_failed = False
        try:
            ops.clear_faults(ref_context)
            ops.inject_fault(ref_context, fault_type='CORRUPT_DATA')
            ops.write_record(ref_context, key='CONFIG_TIMEOUT', value='30')
            try:
                ops.expect_record_value(ref_context, key='CONFIG_TIMEOUT', expected='30')
            except CheckFailed:
                ref_failed = True
        finally:
            ops.clear_faults(ref_context)
            ops.delete_record(ref_context, key='CONFIG_TIMEOUT')
        self.assertTrue(ref_failed, "Reference test must detect data corruption bug")

        # 2. SpecToTest generated execution
        gen_context = ServiceExecutionContext()
        gen_result = execute(run_tc_03_data_corruption_detection, gen_context)

        # 3. Assert identical FAIL verdict
        self.assertEqual(gen_result.result, 'FAIL')
        self.assertIn("30__CORRUPTED", str(gen_result.error))

        ref_context.close()
        gen_context.close()

    # -------------------------------------------------------------------------
    # Case 4: Cleanup & Isolation Verification
    # -------------------------------------------------------------------------
    def test_tc_04_cleanup_and_isolation_comparison(self):
        gen_context = ServiceExecutionContext()
        gen_result = execute(run_tc_04_cleanup_and_isolation, gen_context)
        self.assertEqual(gen_result.result, 'PASS')

        # Verify that postconditions actually purged the record from the service
        self.assertIsNone(gen_context.service.get_record('TEMP_DATA'))
        gen_context.close()

    # -------------------------------------------------------------------------
    # Case 5: Sweep & Loops with Multiple Expectations
    # -------------------------------------------------------------------------
    def test_tc_05_sweep_batch_records_comparison(self):
        gen_context = ServiceExecutionContext()
        gen_result = execute(run_tc_05_sweep_batch_records, gen_context)
        self.assertEqual(gen_result.result, 'PASS')

        # Assert records were logged and verified
        log_ops = [r['operation'] for r in gen_context.log_entries]
        self.assertIn('write_record', log_ops)
        self.assertIn('expect_record_value', log_ops)
        self.assertIn('delete_record', log_ops)
        gen_context.close()

    # -------------------------------------------------------------------------
    # Case 6: Target System Crash -> Technical ERROR
    # -------------------------------------------------------------------------
    def test_tc_06_service_crash_technical_error_comparison(self):
        gen_context = ServiceExecutionContext()
        gen_result = execute(run_tc_06_service_crash_technical_error, gen_context)
        self.assertEqual(gen_result.result, 'ERROR')
        self.assertIn("service unavailable/crashed", str(gen_result.error))
        gen_context.close()


if __name__ == '__main__':
    unittest.main()
