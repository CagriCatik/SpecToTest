"""Interface tests for OperationContract, ParameterSpec, and trusted Registry building."""
from pathlib import Path
import tempfile
import unittest

from examples import external_operations
from examples.external_registry import REGISTRY as EXTERNAL_REGISTRY
from generate import generate
from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.contracts import ContractError, OperationContract, ParameterSpec, build_registry
from tcg.core.mapping import load_mappings
from tcg.core.parameters import Boolean, Resource
from tests.common import (
    BASE_SPEC,
    BaseTestCase,
    EXTERNAL_MAPPING,
    EXTERNAL_SPEC,
    MAPPING,
    REGISTRY,
    RESOURCES,
    RUNNER,
    TC_01,
)


class ContractsAndRegistryInterfaceTests(BaseTestCase):

    def test_registry_rejects_non_importable_local_function(self):
        def local_operation(bench, *, value):
            pass

        contract = OperationContract('local_operation', local_operation,
                                     (ParameterSpec('value', Boolean()),), frozenset({'ACTION'}))
        with self.assertRaisesRegex(ContractError, 'module level'):
            build_registry((contract,))

    def test_unused_operation_resource_does_not_block_existing_cases(self):
        unused = OperationContract(
            'unused_camera_operation', external_operations.expect_supply_at_least,
            (ParameterSpec('minimum', Resource('camera')),), frozenset({'EXPECTED'}))
        registry = build_registry((*REGISTRY.values(), unused))
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'generated.py'
            cases = generate(BASE_SPEC, MAPPING, RESOURCES, output, registry, RUNNER)
        self.assertEqual([case.id for case in cases], ['TC_01_UNDERVOLTAGE_RECOVERY'])

    def test_external_operation_extension_generates_imports_and_runs(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'external_generated.py'
            cases = generate(EXTERNAL_SPEC, EXTERNAL_MAPPING, RESOURCES, output,
                             EXTERNAL_REGISTRY, RUNNER)
            source = output.read_text(encoding='utf-8')
            self.assertIn('import examples.external_operations', source)
            namespace = {'__name__': 'generated_external'}
            exec(compile(source, str(output), 'exec'), namespace)
            log = namespace['RUNNERS']['TC_EXTERNAL_OPERATION_001'](self.bench())
        self.assertEqual(log.result, 'PASS')
        self.assertEqual(cases[0].steps[-1].contract.id, 'expect_supply_at_least')
        self.assertFalse(any(step.phase == 'CLEANUP' for step in cases[0].steps))

    def test_external_operations_package_generates_and_executes(self):
        from operations import REGISTRY as OP_REGISTRY
        mappings = load_mappings(self.mapping_entries, OP_REGISTRY, MAPPING.name)
        cases = compile_cases(read_text_spec(TC_01), mappings, self.profile, TC_01.name)
        source = render_python(cases, OP_REGISTRY, RUNNER)
        self.assertIn('import operations.ignition', source)
        self.assertIn('import operations.diagnostic', source)
        self.assertIn('import operations.supply', source)
        self.assertIn('import operations.timing', source)

        ns = {'__name__': 'generated_test'}
        exec(compile(source, 'generated_test.py', 'exec'), ns)
        report = ns['RUNNERS']['TC_01_UNDERVOLTAGE_RECOVERY'](self.bench()).report()
        self.assertEqual(report['result'], 'PASS')


if __name__ == '__main__':
    unittest.main()

