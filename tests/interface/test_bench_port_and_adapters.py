"""Interface tests for BenchPort, CanBenchPort, and simulator adapters."""
from decimal import Decimal
import unittest

from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, DummyBench, VectorDummyBench, load_config
from tcg.ports.bench import BenchPort, CanBenchPort
from tests.common import BaseTestCase, CONFIG


class BenchPortAndAdaptersInterfaceTests(BaseTestCase):

    def test_bench_port_protocol_conformance(self):
        cfg = load_config(CONFIG, self.profile)
        dummy = DummyBench(cfg)
        vector = VectorDummyBench(cfg)
        cd = ControlDeskDummyBench(cfg)

        for b in (dummy, vector, cd):
            self.assertIsInstance(b, BenchPort)
            self.assertIsInstance(b, CanBenchPort)
            self.assertTrue(hasattr(b, 'now'))
            self.assertTrue(hasattr(b, 'wait'))
            self.assertTrue(hasattr(b, 'set_can_signal'))
            self.assertTrue(hasattr(b, 'get_can_signal'))

    def test_vector_and_controldesk_bench_specific_apis(self):
        cfg = load_config(CONFIG, self.profile)
        vector_bench = VectorDummyBench(cfg)
        vector_bench.set_signal('EngineSpeed', 3000)
        self.assertEqual(vector_bench.get_signal('EngineSpeed'), Decimal('3000'))
        self.assertEqual(vector_bench.get_can_signal('EngineSpeed'), Decimal('3000'))

        cd_bench = ControlDeskDummyBench(cfg)
        cd_bench.write_variable('DoorContactStatus', 1)
        self.assertEqual(cd_bench.read_variable('DoorContactStatus'), Decimal('1'))
        self.assertEqual(cd_bench.get_can_signal('DoorContactStatus'), Decimal('1'))


if __name__ == '__main__':
    unittest.main()

