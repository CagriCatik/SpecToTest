"""The example application's operation registration, separate from the core."""
from decimal import Decimal

from . import demo_operations as ops
from .contracts import OperationContract, ParameterSpec, build_registry
from .parameters import Boolean, Decimal as DecimalType, Quantity, Resource, String

SUPPLY = Quantity('voltage', 'V', (('V', Decimal('1')), ('mV', Decimal('0.001'))), Decimal('0'), Decimal('16'))
DURATION = Quantity('time', 's', (('s', Decimal('1')), ('ms', Decimal('0.001'))), Decimal('0'), Decimal('60'))
INTERVAL = Quantity('poll interval', 's', (('s', Decimal('1')), ('ms', Decimal('0.001'))),
                    Decimal('0.001'), Decimal('60'))
PARAMETER_VALUE = DecimalType(Decimal('0'), Decimal('100'))
CONTROLLER = Resource('controller')
DIAGNOSTIC = Resource('diagnostic_code')
SCREEN = Resource('screen')
PARAMETER = Resource('parameter')

SETUP = frozenset({'PRECONDITION', 'ACTION', 'CLEANUP'})
CHECK = frozenset({'EXPECTED'})

REGISTRY = build_registry((
    OperationContract('set_supply', ops.set_supply, (ParameterSpec('value', SUPPLY),), SETUP),
    OperationContract('wait', ops.wait, (ParameterSpec('seconds', DURATION),), SETUP),
    OperationContract('expect_diagnostic', ops.expect_diagnostic,
                      (ParameterSpec('controller', CONTROLLER), ParameterSpec('code', DIAGNOSTIC),
                       ParameterSpec('active', Boolean('aktiv', 'inaktiv'))), CHECK),
    OperationContract('expect_diagnostic_within', ops.expect_diagnostic_within,
                      (ParameterSpec('controller', CONTROLLER), ParameterSpec('code', DIAGNOSTIC),
                       ParameterSpec('active', Boolean('aktiv', 'inaktiv')), ParameterSpec('timeout', DURATION),
                       ParameterSpec('interval', INTERVAL)), CHECK),
    OperationContract('monitor_diagnostic', ops.monitor_diagnostic,
                      (ParameterSpec('controller', CONTROLLER), ParameterSpec('code', DIAGNOSTIC),
                       ParameterSpec('active', Boolean('aktiv', 'inaktiv')), ParameterSpec('duration', DURATION),
                       ParameterSpec('interval', INTERVAL)), CHECK),
    OperationContract('select_screen', ops.select_screen, (ParameterSpec('screen', SCREEN),), SETUP),
    OperationContract('expect_screen_text', ops.expect_screen_text, (ParameterSpec('text', String()),), CHECK),
    OperationContract('write_parameter', ops.write_parameter,
                      (ParameterSpec('parameter', PARAMETER), ParameterSpec('value', PARAMETER_VALUE)), SETUP),
    OperationContract('expect_parameter', ops.expect_parameter,
                      (ParameterSpec('parameter', PARAMETER), ParameterSpec('value', PARAMETER_VALUE)), CHECK),
))
