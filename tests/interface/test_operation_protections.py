"""Interface tests for actuator write protections, typed exceptions, and readback verification."""
from decimal import Decimal
import unittest

from tcg.ports.bench import (
    BenchConnectionError,
    BenchError,
    BenchLimitViolationError,
    BenchResourceNotFoundError,
    BenchWriteError,
)
from tests.common import BaseTestCase


class OperationProtectionsInterfaceTests(BaseTestCase):

    def test_operation_protection_mechanisms_and_readback_verification(self):
        bench = self.bench()

        # 1. Protection against setting unconfigured CAN signal
        with self.assertRaises(BenchResourceNotFoundError):
            bench.set_can_signal('NonExistentSignal_XYZ', Decimal('100'))

        # 2. Protection against setting signal when CAN bus is offline
        bench.can_bus_active = False
        with self.assertRaises(BenchConnectionError):
            bench.set_can_signal('EngineSpeed', Decimal('2000'))
        bench.can_bus_active = True

        # 3. Protection against out-of-bounds power supply voltages
        with self.assertRaises(BenchLimitViolationError):
            bench.set_supply(Decimal('-5'))
        with self.assertRaises(BenchLimitViolationError):
            bench.set_supply(Decimal('100'))

        # 4. Protection against writing unknown parameter
        with self.assertRaises(BenchResourceNotFoundError):
            bench.write_parameter('UNKNOWN_PARAM', Decimal('1'))

        # 5. Protection against invalid screen
        with self.assertRaises(BenchResourceNotFoundError):
            bench.select_screen('NON_EXISTENT_SCREEN')

        # 6. Protection against invalid ignition state
        with self.assertRaises(TypeError):
            bench.set_ignition('not_a_bool')

        # 7. Verification that successful operations are logged as CONFIRMED with verified values
        bench.set_can_signal('EngineSpeed', Decimal('2500'))
        last_log = bench.log_entries[-1]
        self.assertEqual(last_log['operation'], 'set_can_signal')
        self.assertEqual(last_log['details']['status'], 'CONFIRMED')
        self.assertEqual(last_log['details']['verified_value'], '2500')

        bench.set_supply(Decimal('12.5'))
        last_log = bench.log_entries[-1]
        self.assertEqual(last_log['operation'], 'set_supply')
        self.assertEqual(last_log['details']['status'], 'CONFIRMED')
        self.assertEqual(last_log['details']['verified_value'], '12.5')


if __name__ == '__main__':
    unittest.main()

