"""Unit tests for test logging, step records, FAIL/ERROR classification, and cleanup errors."""
from decimal import Decimal
import unittest

from operations import hmi
from tcg.adapters.outbound.dummy_bench import DummyBench, load_config
from tcg.runtime import CheckFailed, StepInfo, TestLog
from tests.common import BaseTestCase, CONFIG


class ResultAndLoggingUnitTests(BaseTestCase):

    def test_cleanup_error_does_not_skip_later_cleanup(self):
        class FailingCleanupBench(DummyBench):
            def write_parameter(self, parameter, value):
                if parameter == 'GAIN' and value == 0:
                    raise RuntimeError('injected cleanup error')
                return super().write_parameter(parameter, value)

        bench = FailingCleanupBench(load_config(CONFIG, self.profile))
        info1 = StepInfo('C1', 'CLEANUP', 1, None, None, 'spec.txt', 'MAP', 'cleanup 1')
        info2 = StepInfo('C2', 'CLEANUP', 2, None, None, 'spec.txt', 'MAP', 'cleanup 2')
        log = TestLog('TC_TEST', 'Test', None, 'PROFILE', (info1, info2), bench)
        log.cleanup('C1', hmi.write_parameter, parameter='GAIN', value=Decimal('0'))
        log.cleanup('C2', hmi.write_parameter, parameter='LIMIT', value=Decimal('0'))
        self.assertEqual([(r['execution_id'], r['result']) for r in log.records],
                         [('C1', 'ERROR'), ('C2', 'PASS')])

    def test_clock_failure_does_not_hide_check_failure_or_drop_record(self):
        class BrokenClock:
            def now(self):
                raise RuntimeError('clock unavailable')

        def failing_check(bench):
            raise CheckFailed('observed mismatch')

        info = StepInfo('S10', 'EXPECTED', 10, None, None, 'spec.txt:1 [Ablauf]',
                        'MAP_CHECK', 'check')
        log = TestLog('TC_CLOCK', 'Clock', None, 'PROFILE', (info,), BrokenClock())
        with self.assertRaisesRegex(CheckFailed, 'observed mismatch'):
            log.step('S10', failing_check)
        self.assertEqual(len(log.records), 1)
        self.assertEqual(log.records[0]['result'], 'FAIL')
        self.assertIn('clock unavailable', log.records[0]['logging_error'])
        self.assertEqual([type(error) for error in log.errors], [CheckFailed, RuntimeError])


if __name__ == '__main__':
    unittest.main()

