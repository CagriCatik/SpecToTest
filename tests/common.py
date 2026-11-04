"""Shared test configuration, paths, and helpers for all test suites."""
import ast
from decimal import Decimal
from pathlib import Path
import unittest

from examples.external_registry import REGISTRY as EXTERNAL_REGISTRY
from operations.registry import REGISTRY
from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.dummy_bench import ControlDeskDummyBench, DummyBench, VectorDummyBench, load_config
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.mapping import load_mappings, parse_mapping_document
from tcg.core.profile import load_profile

ROOT = Path(__file__).resolve().parents[1]
SPEC = ROOT / 'inputs/diagnostics/tc_05_diagnostic_timing_undervoltage.md'
BASE_SPEC = ROOT / 'inputs/diagnostics/tc_01_undervoltage_recovery.md'

TC_01 = ROOT / 'inputs/diagnostics/tc_01_undervoltage_recovery.md'
TC_02 = ROOT / 'inputs/hmi/tc_02_hmi_loop_verification.md'
TC_03 = ROOT / 'inputs/diagnostics/tc_03_diagnostic_powercycle.md'
TC_04 = ROOT / 'inputs/limits/tc_04_parameter_limits_sweep.md'
TC_05 = ROOT / 'inputs/diagnostics/tc_05_diagnostic_timing_undervoltage.md'
TC_06 = ROOT / 'inputs/can/tc_06_can_signal_transmission.md'
TC_07 = ROOT / 'inputs/hil/tc_07_controldesk_hil_simulation.md'
TC_08 = ROOT / 'inputs/bms/tc_08_bms_hv_precharge_sequence.md'
TC_09 = ROOT / 'inputs/bms/tc_09_bms_cell_overvoltage_derating.md'
TC_10 = ROOT / 'inputs/bms/tc_10_bms_thermal_derating_sweep.md'
TC_11 = ROOT / 'inputs/bms/tc_11_bms_isolation_monitoring.md'
TC_12 = ROOT / 'inputs/bms/tc_12_bms_signal_tolerances_and_ranges.md'
TC_13 = ROOT / 'inputs/diagnostics/tc_13_reference_undervoltage.md'

MAPPING = ROOT / 'inputs/operation_mapping.toml'
RESOURCES = ROOT / 'inputs/resources.json'
CONFIG = ROOT / 'inputs/demo_bench.json'
EXTERNAL_SPEC = ROOT / 'examples/external_test.txt'
EXTERNAL_MAPPING = ROOT / 'examples/external_mapping.toml'
RUNNER = 'tcg.runtime.runner'


def copy_sections(sections):
    return {name: [(line, dict(data)) for line, data in rows] for name, rows in sections.items()}


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(RESOURCES)
        self.mapping_entries = parse_mapping_document(MAPPING.read_text(encoding='utf-8'), MAPPING.name)
        self.mappings = load_mappings(self.mapping_entries, REGISTRY, MAPPING.name)
        self.sections = read_text_spec(SPEC)

    def cases(self, sections=None, mappings=None, source=SPEC.name):
        return compile_cases(sections or self.sections, mappings or self.mappings, self.profile, source)

    def namespace(self, sections=None, mappings=None, registry=REGISTRY):
        source = render_python(self.cases(sections, mappings), registry, RUNNER)
        namespace = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), namespace)
        return source, namespace

    def bench(self):
        return DummyBench(load_config(CONFIG, self.profile))

