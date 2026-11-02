"""Zentrale Registrierung aller Operationen und Verträge für Testfälle.

Hier werden die in den einzelnen Modulen (ignition.py, diagnostic.py, supply.py, ...)
implementierten Python-Funktionen mit ihren Verträgen registriert.
"""
from decimal import Decimal

from tcg.core.contracts import OperationContract, ParameterSpec, build_registry
from tcg.core.parameters import Boolean, Decimal as DecimalType, Quantity, Resource, String

from . import can, diagnostic, hmi, ignition, supply, timing

# 1. Parameter-Typdefinitionen (Einheiten, Wertebereiche, Ressourcen)
SUPPLY_VOLTAGE = Quantity(
    dimension='voltage',
    unit='V',
    factors=(('V', Decimal('1')), ('mV', Decimal('0.001'))),
    minimum=Decimal('0'),
    maximum=Decimal('16'),
)

DURATION = Quantity(
    dimension='time',
    unit='s',
    factors=(('s', Decimal('1')), ('ms', Decimal('0.001'))),
    minimum=Decimal('0'),
    maximum=Decimal('60'),
)

INTERVAL = Quantity(
    dimension='poll interval',
    unit='s',
    factors=(('s', Decimal('1')), ('ms', Decimal('0.001'))),
    minimum=Decimal('0.001'),
    maximum=Decimal('60'),
)

IGNITION_STATE = Boolean('an', 'aus')
BOOLEAN_STATUS = Boolean('aktiv', 'inaktiv')
ECU = Resource('controller')
DTC = Resource('diagnostic_code')
SCREEN = Resource('screen')
PARAMETER = Resource('parameter')
PARAMETER_VALUE = DecimalType(Decimal('0'), Decimal('100'))
CAN_SIGNAL = Resource('can_signal')
CAN_SIGNAL_VALUE = Quantity(
    dimension='can_signal_value',
    unit='',
    factors=(
        ('rpm', Decimal('1')),
        ('km/h', Decimal('1')),
        ('%', Decimal('1')),
        ('V', Decimal('1')),
        ('mV', Decimal('0.001')),
        ('A', Decimal('1')),
        ('mA', Decimal('0.001')),
        ('kOhm', Decimal('1')),
        ('Ohm', Decimal('0.001')),
        ('kΩ', Decimal('1')),
        ('Ω', Decimal('0.001')),
        ('°C', Decimal('1')),
        ('C', Decimal('1')),
        ('degC', Decimal('1')),
        ('kW', Decimal('1')),
        ('W', Decimal('0.001')),
        ('raw', Decimal('1')),
        ('', Decimal('1')),
    ),
    minimum=Decimal('-1000000'),
    maximum=Decimal('1000000'),
)

# Phasen
SETUP = frozenset({'PRECONDITION', 'ACTION', 'CLEANUP'})
CHECK = frozenset({'EXPECTED'})

# 2. Registrierung aller Operationen
REGISTRY = build_registry((
    # Zündung (ignition.py)
    OperationContract('set_ignition', ignition.set_ignition,
                      (ParameterSpec('state', IGNITION_STATE),), SETUP),

    # Diagnose / Fehlerspeicher (diagnostic.py)
    OperationContract('clear_fault_memory', diagnostic.clear_fault_memory,
                      (ParameterSpec('ecu', ECU),), SETUP),
    OperationContract('read_fault_memory', diagnostic.read_fault_memory,
                      (ParameterSpec('ecu', ECU),), SETUP),
    OperationContract('expect_fault_memory_entry', diagnostic.expect_fault_memory_entry,
                      (ParameterSpec('code', DTC), ParameterSpec('ecu', ECU, default='BCM1')), CHECK),
    OperationContract('expect_fault_memory_empty', diagnostic.expect_fault_memory_empty,
                      (ParameterSpec('ecu', ECU),), CHECK),
    OperationContract('expect_diagnostic', diagnostic.expect_diagnostic,
                      (ParameterSpec('controller', ECU), ParameterSpec('code', DTC),
                       ParameterSpec('active', BOOLEAN_STATUS)), CHECK),
    OperationContract('expect_diagnostic_within', diagnostic.expect_diagnostic_within,
                      (ParameterSpec('controller', ECU), ParameterSpec('code', DTC),
                       ParameterSpec('active', BOOLEAN_STATUS), ParameterSpec('timeout', DURATION),
                       ParameterSpec('interval', INTERVAL)), CHECK),
    OperationContract('monitor_diagnostic', diagnostic.monitor_diagnostic,
                      (ParameterSpec('controller', ECU), ParameterSpec('code', DTC),
                       ParameterSpec('active', BOOLEAN_STATUS), ParameterSpec('duration', DURATION),
                       ParameterSpec('interval', INTERVAL)), CHECK),

    # Spannungsversorgung & Batterie (supply.py)
    OperationContract('set_battery_voltage', supply.set_battery_voltage,
                      (ParameterSpec('value', SUPPLY_VOLTAGE),), SETUP),
    OperationContract('set_supply', supply.set_supply,
                      (ParameterSpec('value', SUPPLY_VOLTAGE),), SETUP),

    # Wartezeiten (timing.py)
    OperationContract('wait', timing.wait,
                      (ParameterSpec('seconds', DURATION),), SETUP),

    # HMI & Parameter (hmi.py)
    OperationContract('select_screen', hmi.select_screen,
                      (ParameterSpec('screen', SCREEN),), SETUP),
    OperationContract('expect_screen_text', hmi.expect_screen_text,
                      (ParameterSpec('text', String()),), CHECK),
    OperationContract('write_parameter', hmi.write_parameter,
                      (ParameterSpec('parameter', PARAMETER), ParameterSpec('value', PARAMETER_VALUE)), SETUP),
    OperationContract('expect_parameter', hmi.expect_parameter,
                      (ParameterSpec('parameter', PARAMETER), ParameterSpec('value', PARAMETER_VALUE)), CHECK),

    # CAN-Bus & Vector / ControlDesk (can.py)
    OperationContract('set_can_signal', can.set_can_signal,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), SETUP),
    OperationContract('expect_can_signal', can.expect_can_signal,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), CHECK),
    OperationContract('expect_can_signal_tolerance', can.expect_can_signal_tolerance,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE),
                       ParameterSpec('tolerance', CAN_SIGNAL_VALUE)), CHECK),
    OperationContract('expect_can_signal_range', can.expect_can_signal_range,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('min_value', CAN_SIGNAL_VALUE),
                       ParameterSpec('max_value', CAN_SIGNAL_VALUE)), CHECK),
    OperationContract('expect_can_signal_min', can.expect_can_signal_min,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('min_value', CAN_SIGNAL_VALUE)), CHECK),
    OperationContract('expect_can_signal_max', can.expect_can_signal_max,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('max_value', CAN_SIGNAL_VALUE)), CHECK),
    OperationContract('expect_can_signal_greater', can.expect_can_signal_greater,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), CHECK),
    OperationContract('expect_can_signal_less', can.expect_can_signal_less,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), CHECK),
    OperationContract('wait_can_signal', can.wait_can_signal,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE),
                       ParameterSpec('timeout', DURATION), ParameterSpec('interval', INTERVAL)), CHECK),
))

