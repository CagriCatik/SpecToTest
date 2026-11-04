"""Contract and Operation Registry for the RecordStore Service Pilot.

Registers all domain operations and their ParameterSpecs without touching the compiler.
"""
from decimal import Decimal

from operations.timing import wait
from tcg.core.contracts import OperationContract, ParameterSpec, build_registry
from tcg.core.parameters import Boolean, Quantity, Resource, String

from . import operations

KEY = Resource('key')
STATUS = Resource('status')
FAULT_TYPE = Resource('fault_type')

DURATION = Quantity(
    dimension='time',
    unit='s',
    factors=(('s', Decimal('1')), ('ms', Decimal('0.001'))),
    minimum=Decimal('0'),
    maximum=Decimal('60'),
)


SERVICE_OPERATIONS = (
    OperationContract(
        id='write_record',
        function=operations.write_record,
        parameters=(
            ParameterSpec('key', KEY),
            ParameterSpec('value', String()),
        ),
        phases=frozenset(('PRECONDITION', 'ACTION', 'CLEANUP')),
    ),
    OperationContract(
        id='expect_record_value',
        function=operations.expect_record_value,
        parameters=(
            ParameterSpec('key', KEY),
            ParameterSpec('expected', String()),
        ),
        phases=frozenset(('EXPECTED',)),
    ),
    OperationContract(
        id='expect_record_missing',
        function=operations.expect_record_missing,
        parameters=(
            ParameterSpec('key', KEY),
        ),
        phases=frozenset(('EXPECTED',)),
    ),
    OperationContract(
        id='delete_record',
        function=operations.delete_record,
        parameters=(
            ParameterSpec('key', KEY),
        ),
        phases=frozenset(('PRECONDITION', 'ACTION', 'CLEANUP')),
    ),
    OperationContract(
        id='restart_service',
        function=operations.restart_service,
        parameters=(),
        phases=frozenset(('PRECONDITION', 'ACTION', 'CLEANUP')),
    ),
    OperationContract(
        id='inject_fault',
        function=operations.inject_fault,
        parameters=(
            ParameterSpec('fault_type', FAULT_TYPE),
        ),
        phases=frozenset(('PRECONDITION', 'ACTION', 'CLEANUP')),
    ),
    OperationContract(
        id='clear_faults',
        function=operations.clear_faults,
        parameters=(),
        phases=frozenset(('PRECONDITION', 'ACTION', 'CLEANUP')),
    ),
    OperationContract(
        id='expect_service_health',
        function=operations.expect_service_health,
        parameters=(
            ParameterSpec('status', STATUS),
        ),
        phases=frozenset(('EXPECTED',)),
    ),
    OperationContract(
        id='wait',
        function=wait,
        parameters=(
            ParameterSpec('seconds', DURATION),
        ),
        phases=frozenset(('ACTION', 'CLEANUP')),
    ),
)


SERVICE_REGISTRY = build_registry(SERVICE_OPERATIONS)
