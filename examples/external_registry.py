"""Demo registry extended by one independently implemented operation."""
from decimal import Decimal

from operations.registry import REGISTRY as BASE_REGISTRY
from tcg.core.contracts import OperationContract, ParameterSpec, build_registry
from tcg.core.parameters import Quantity

from . import external_operations as ops


VOLTAGE = Quantity('voltage', 'V', (('V', Decimal('1')), ('mV', Decimal('0.001'))),
                   Decimal('0'), Decimal('16'))

REGISTRY = build_registry((
    *BASE_REGISTRY.values(),
    OperationContract(
        'expect_supply_at_least',
        ops.expect_supply_at_least,
        (ParameterSpec('minimum', VOLTAGE),),
        frozenset({'EXPECTED'}),
    ),
))
