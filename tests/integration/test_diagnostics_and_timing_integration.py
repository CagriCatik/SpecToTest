"""Integration tests for diagnostic UDS timing, deadlines, and active monitors."""
from decimal import Decimal
import unittest

from operations import diagnostic
from tcg.adapters.outbound.dummy_bench import DummyBench, load_config
from tcg.core.mapping import resolve
from tcg.runtime import CheckFailed
from tests.common import BaseTestCase, CONFIG, copy_sections


class DiagnosticsAndTimingIntegrationTests(BaseTestCase):

    def test_now_within_and_monitor_are_distinct_operations(self):
        mapped = {mapping.id: mapping.contract.id for mapping in self.mappings}
        self.assertEqual(mapped['MAP_DIAGNOSTIC_NOW'], 'expect_diagnostic')
        self.assertEqual(mapped['MAP_DIAGNOSTIC_WITHIN'], 'expect_diagnostic_within')
        self.assertEqual(mapped['MAP_DIAGNOSTIC_MONITOR'], 'monitor_diagnostic')
        _, arguments = resolve('Fehler UNDERVOLTAGE in BCM ist aktiv', self.mappings, self.profile)
        self.assertIs(dict(arguments)['active'], True)

    def test_timeout_failure_runs_cleanup(self):
        sections = copy_sections(self.sections)
        command = next(data for _, data in sections['Ablauf'] if data['Schritt'] == 60)
        command['Befehl'] = ('Auf Fehler UNDERVOLTAGE in BCM aktiv warten, maximal 400 ms, '
                             'Prüfintervall 100 ms')
        _, namespace = self.namespace(sections)
        bench = self.bench()
        with self.assertRaises(CheckFailed):
            namespace['RUNNERS']['TC_05_DIAGNOSTIC_TIMING_UNDERVOLTAGE'](bench)
        self.assertEqual(bench.supply, Decimal('13.5'))

    def test_observation_completed_after_deadline_fails_even_if_value_matches(self):
        class SlowObservationBench:
            def __init__(self):
                self.time = Decimal('0')

            def now(self):
                return self.time

            def diagnostic_active(self, controller, code):
                self.time += Decimal('0.6')
                return True

            def wait(self, seconds):
                self.time += seconds

        with self.assertRaisesRegex(CheckFailed, 'completed after timeout'):
            diagnostic.expect_diagnostic_within(
                SlowObservationBench(), controller='BCM', code='UNDERVOLTAGE', active=True,
                timeout=Decimal('0.5'), interval=Decimal('0.1'))

    def test_monitoring_detects_state_change_and_runs_cleanup(self):
        class ChangingBench(DummyBench):
            def diagnostic_active(self, controller, code):
                actual = super().diagnostic_active(controller, code)
                return False if self.now() >= Decimal('0.7') else actual

        _, namespace = self.namespace()
        bench = ChangingBench(load_config(CONFIG, self.profile))
        with self.assertRaises(CheckFailed):
            namespace['RUNNERS']['TC_05_DIAGNOSTIC_TIMING_UNDERVOLTAGE'](bench)
        self.assertEqual(bench.supply, Decimal('13.5'))


if __name__ == '__main__':
    unittest.main()

