"""End-to-End test for reference testcase (TC_13_UNDERVOLTAGE_REFERENCE) validating all 9 assertions."""
from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from generate import generate
from tcg.adapters.outbound.dummy_bench import DummyBench, load_config
from tcg.runtime import CheckFailed
from tests.common import BaseTestCase, CONFIG, MAPPING, REGISTRY, RESOURCES, ROOT, RUNNER, TC_13


class ReferenceCaseE2ETests(BaseTestCase):

    def test_reference_undervoltage_all_assertions(self):
        ref_spec = TC_13
        self.assertTrue(ref_spec.exists())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'test_ref.py'
            cases = generate(ref_spec, MAPPING, RESOURCES, output, REGISTRY, RUNNER)
            self.assertEqual(cases[0].id, 'TC_UNDERVOLTAGE_REFERENCE')

            # Assertion 1: Supply for action 40 is normalized to 7 V
            step_40 = [s for s in cases[0].steps if getattr(s, 'test_step', None) == 40][0]
            self.assertEqual(dict(step_40.arguments)['value'], Decimal('7'))

            # Assertion 2: Expectation 60 runs immediately after action 60
            step_tuples = [(s.test_step, s.phase) for s in cases[0].steps if getattr(s, 'test_step', None) is not None]
            idx_60_act = step_tuples.index((60, 'ACTION'))
            self.assertEqual(step_tuples[idx_60_act + 1], (60, 'EXPECTED'))

            # Assertion 9: Two generations with identical inputs produce byte-identical Python files
            output2 = Path(directory) / 'test_ref2.py'
            generate(ref_spec, MAPPING, RESOURCES, output2, REGISTRY, RUNNER)
            self.assertEqual(output.read_bytes(), output2.read_bytes())

            # Assertion 8: Changing 7000mV to 8000mV changes normalized operation argument to 8 V
            mod_text = ref_spec.read_text(encoding='utf-8').replace('7000mV', '8000mV')
            mod_spec = Path(directory) / 'tc_ref_mod.txt'
            mod_spec.write_text(mod_text, encoding='utf-8')
            output_mod = Path(directory) / 'test_ref_mod.py'
            cases_mod = generate(mod_spec, MAPPING, RESOURCES, output_mod, REGISTRY, RUNNER)
            step_40_mod = [s for s in cases_mod[0].steps if getattr(s, 'test_step', None) == 40][0]
            self.assertEqual(dict(step_40_mod.arguments)['value'], Decimal('8'))

            # Execution tests
            source = output.read_text(encoding='utf-8')
            ns = {'__name__': 'ref_test'}
            exec(compile(source, str(output), 'exec'), ns)
            runner_fn = ns['RUNNERS']['TC_UNDERVOLTAGE_REFERENCE']

            # Assertion 3 & Successful execution
            bench = self.bench()
            bench.fault_memory['BCM1'] = ['DTC00173']
            res = runner_fn(bench)
            self.assertEqual(res.result, 'PASS')

            # Assertion 4: Negative check result yields FAIL
            class MismatchFaultBench(DummyBench):
                def read_fault_memory(self, ecu):
                    return ['DTC99999']
            bench_fail = MismatchFaultBench(load_config(CONFIG, self.profile))
            with self.assertRaises(CheckFailed):
                runner_fn(bench_fail)

            # Assertion 5: Communication error yields ERROR
            class BrokenCommBench(DummyBench):
                def read_fault_memory(self, ecu):
                    raise ConnectionResetError('CAN communication lost')
            bench_comm = BrokenCommBench(load_config(CONFIG, self.profile))
            with self.assertRaises(ConnectionResetError):
                runner_fn(bench_comm)

            # Assertion 6: Precondition failure still attempts Postcondition cleanup
            class FailingPrecondBench(DummyBench):
                def __init__(self, config):
                    super().__init__(config)
                    self.cleanup_attempted = []
                def set_ignition(self, state):
                    if state is True:
                        raise RuntimeError('ignition switch hardware failure')
                    self.cleanup_attempted.append(f'ignition_{state}')
                def set_battery_voltage(self, voltage):
                    self.cleanup_attempted.append(f'battery_voltage_{voltage}')
                def clear_fault_memory(self, ecu):
                    self.cleanup_attempted.append(f'clear_{ecu}')

            bench_pre = FailingPrecondBench(load_config(CONFIG, self.profile))
            with self.assertRaises(RuntimeError):
                runner_fn(bench_pre)
            self.assertIn('battery_voltage_13.8', bench_pre.cleanup_attempted)
            self.assertIn('ignition_False', bench_pre.cleanup_attempted)
            self.assertIn('clear_BCM1', bench_pre.cleanup_attempted)

            # Assertion 7: Cleanup error in step 70 does not skip steps 80 and 90
            class FailingCleanupStep70Bench(DummyBench):
                def __init__(self, config):
                    super().__init__(config)
                    self.cleanup_attempted = []
                def set_battery_voltage(self, voltage):
                    if voltage == Decimal('13.8'):
                        raise RuntimeError('battery voltage rail shorted in cleanup')
                    super().set_battery_voltage(voltage)
                def set_ignition(self, state):
                    self.cleanup_attempted.append(f'ignition_{state}')
                    super().set_ignition(state)
                def clear_fault_memory(self, ecu):
                    self.cleanup_attempted.append(f'clear_{ecu}')
                    super().clear_fault_memory(ecu)

            bench_cln = FailingCleanupStep70Bench(load_config(CONFIG, self.profile))
            bench_cln.fault_memory['BCM1'] = ['DTC00173']
            with self.assertRaises(RuntimeError) as ctx:
                runner_fn(bench_cln)
            self.assertIn('battery voltage rail shorted', str(ctx.exception))
            # Steps 80 and 90 were STILL executed!
            self.assertIn('ignition_False', bench_cln.cleanup_attempted)
            self.assertIn('clear_BCM1', bench_cln.cleanup_attempted)


if __name__ == '__main__':
    unittest.main()

