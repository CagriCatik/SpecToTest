"""Zentrale Registrierung aller Operationen und Verträge für Testfälle.

Hier werden die in den einzelnen Modulen (ignition.py, diagnostic.py, supply.py, ...)
implementierten Python-Funktionen mit ihren Verträgen registriert.
"""
from decimal import Decimal

from tcg.core.contracts import OperationContract, ParameterSpec, bind_registry, build_registry
from tcg.core.parameters import Boolean, Decimal as DecimalType, Quantity, Resource, String

from tcg.comm.model import Capability, ObjectKind, Technology

from . import can, diagnostic, ethernet, hmi, ignition, lin, supply, timing
from tcg.comm.catalog import COMM_CATALOG_KEY
from tcg.comm.model import EMPTY_CATALOG

from .comm_types import RAW, ResourceReference, SignalValue

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

BASE_CAN_SIGNAL_VALUE = Quantity(
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


CAN_TOLERANCE = Quantity(
    dimension='can_signal_tolerance',
    unit='',
    factors=BASE_CAN_SIGNAL_VALUE.factors,
    minimum=Decimal('0'),
    maximum=Decimal('1000000'),
)

# --- Communication resource references (technology- and kind-checked) ---
# Catalogs stay unconfigured on import: importing this module must not read any
# project file. An inbound adapter loads the active project's descriptions and calls
# build_operations_registry() to bind them.
CAN_SIGNAL = ResourceReference(technology=Technology.CAN, kinds=ObjectKind.SIGNAL,
                               label='CAN-Signal', profile_kind='can_signal')
LIN_SIGNAL = ResourceReference(technology=Technology.LIN, kinds=ObjectKind.SIGNAL,
                               label='LIN-Signal')
LIN_SCHEDULE = ResourceReference(technology=Technology.LIN, kinds=ObjectKind.SCHEDULE,
                                 label='LIN-Schedule')
LIN_FRAME = ResourceReference(technology=Technology.LIN, kinds=ObjectKind.FRAME,
                              label='LIN-Frame')
ETH_METHOD = ResourceReference(technology=Technology.ETHERNET, kinds=ObjectKind.METHOD,
                               label='Service-Methode')
ETH_EVENT = ResourceReference(technology=Technology.ETHERNET, kinds=ObjectKind.EVENT,
                              label='Service-Event')

# PHYSICAL values: what the tester writes in the specification, in its unit.
CAN_SIGNAL_VALUE = SignalValue(BASE_CAN_SIGNAL_VALUE, technology=Technology.CAN)
LIN_SIGNAL_VALUE = SignalValue(BASE_CAN_SIGNAL_VALUE, technology=Technology.LIN)
# RAW values: the value on the bus, never scaled.
CAN_SIGNAL_RAW = SignalValue(BASE_CAN_SIGNAL_VALUE, technology=Technology.CAN,
                             semantics=RAW)
LIN_SIGNAL_RAW = SignalValue(BASE_CAN_SIGNAL_VALUE, technology=Technology.LIN,
                             semantics=RAW)

EVENT_COUNT = DecimalType(Decimal('0'), Decimal('1000'))


def build_operations_registry(catalog=None):
    """Return a registry bound to one project's communication catalog.

    `catalog` holds every network and technology the project configures; pass None
    for a project that uses no bus descriptions at all.

    The returned registry is a fresh, independent copy: REGISTRY and registries built
    for other projects are untouched.
    """
    return bind_registry(REGISTRY, {COMM_CATALOG_KEY: catalog or EMPTY_CATALOG})


VEHICLE_SPEED_VALUE = Quantity(
    dimension='vehicle_speed',
    unit='km/h',
    factors=(('km/h', Decimal('1')),),
    minimum=Decimal('0'),
    maximum=Decimal('350'),
)

ENGINE_SPEED_VALUE = Quantity(
    dimension='engine_speed',
    unit='rpm',
    factors=(('rpm', Decimal('1')),),
    minimum=Decimal('0'),
    maximum=Decimal('10000'),
)

SOC_VALUE = Quantity(
    dimension='soc',
    unit='%',
    factors=(('%', Decimal('1')),),
    minimum=Decimal('0'),
    maximum=Decimal('100'),
)

# Phasen
SETUP = frozenset({'PRECONDITION', 'ACTION', 'CLEANUP'})
CHECK = frozenset({'EXPECTED'})

# Benötigte Testbench-Fähigkeiten (siehe tcg.comm.capabilities)
READ = frozenset({Capability.READ_SIGNAL.value})
WRITE = frozenset({Capability.WRITE_SIGNAL.value})
SEND_FRAME = frozenset({Capability.SEND_FRAME.value})
SET_SCHEDULE = frozenset({Capability.SET_LIN_SCHEDULE.value})
CALL_METHOD = frozenset({Capability.CALL_METHOD.value})
SUBSCRIBE = frozenset({Capability.SUBSCRIBE_EVENT.value})

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
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), SETUP,
                      WRITE),
    OperationContract('expect_can_signal', can.expect_can_signal,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), CHECK, READ),
    OperationContract('expect_can_signal_tolerance', can.expect_can_signal_tolerance,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE),
                       ParameterSpec('tolerance', CAN_TOLERANCE)), CHECK, READ),
    OperationContract('expect_can_signal_range', can.expect_can_signal_range,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('min_value', CAN_SIGNAL_VALUE),
                       ParameterSpec('max_value', CAN_SIGNAL_VALUE)), CHECK, READ),
    OperationContract('expect_can_signal_min', can.expect_can_signal_min,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('min_value', CAN_SIGNAL_VALUE)), CHECK, READ),
    OperationContract('expect_can_signal_max', can.expect_can_signal_max,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('max_value', CAN_SIGNAL_VALUE)), CHECK, READ),
    OperationContract('expect_can_signal_greater', can.expect_can_signal_greater,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), CHECK, READ),
    OperationContract('expect_can_signal_less', can.expect_can_signal_less,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE)), CHECK, READ),
    OperationContract('wait_can_signal', can.wait_can_signal,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_VALUE),
                       ParameterSpec('timeout', DURATION), ParameterSpec('interval', INTERVAL)), CHECK, READ),

    # Rohwert-Varianten: ausdrücklich der Wert auf dem Bus, ohne Skalierung
    OperationContract('set_can_signal_raw', can.set_can_signal,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_RAW)),
                      SETUP, WRITE),
    OperationContract('expect_can_signal_raw', can.expect_can_signal,
                      (ParameterSpec('signal', CAN_SIGNAL), ParameterSpec('value', CAN_SIGNAL_RAW)),
                      CHECK, READ),

    # LIN: Signale teilen die Semantik mit CAN, Schedules sind LIN-spezifisch
    OperationContract('set_lin_signal', can.set_can_signal,
                      (ParameterSpec('signal', LIN_SIGNAL), ParameterSpec('value', LIN_SIGNAL_VALUE)),
                      SETUP, WRITE),
    OperationContract('expect_lin_signal', can.expect_can_signal,
                      (ParameterSpec('signal', LIN_SIGNAL), ParameterSpec('value', LIN_SIGNAL_VALUE)),
                      CHECK, READ),
    OperationContract('set_lin_signal_raw', can.set_can_signal,
                      (ParameterSpec('signal', LIN_SIGNAL), ParameterSpec('value', LIN_SIGNAL_RAW)),
                      SETUP, WRITE),
    OperationContract('set_lin_schedule', lin.set_lin_schedule,
                      (ParameterSpec('schedule', LIN_SCHEDULE),), SETUP, SET_SCHEDULE),
    OperationContract('expect_lin_schedule', lin.expect_lin_schedule,
                      (ParameterSpec('schedule', LIN_SCHEDULE),), CHECK, SET_SCHEDULE),
    OperationContract('send_lin_frame', lin.send_lin_frame,
                      (ParameterSpec('frame', LIN_FRAME),), SETUP, SEND_FRAME),

    # Ethernet: serviceorientiert, keine Signal-Semantik
    OperationContract('call_service_method', ethernet.call_service_method,
                      (ParameterSpec('method', ETH_METHOD),
                       ParameterSpec('argument', String(), default=''),
                       ParameterSpec('result_variable', String(), default='')),
                      SETUP, CALL_METHOD),
    OperationContract('expect_method_result', ethernet.expect_method_result,
                      (ParameterSpec('method', ETH_METHOD),
                       ParameterSpec('argument', String(), default=''),
                       ParameterSpec('expected', String(), default='')),
                      CHECK, CALL_METHOD),
    OperationContract('subscribe_event', ethernet.subscribe_event,
                      (ParameterSpec('event', ETH_EVENT),), SETUP, SUBSCRIBE),
    OperationContract('expect_event_received', ethernet.expect_event_received,
                      (ParameterSpec('event', ETH_EVENT),
                       ParameterSpec('count', EVENT_COUNT, default=1)),
                      CHECK, SUBSCRIBE),
))

