"""Zentrale Registrierung aller Operationen und Verträge für Testfälle.

Hier werden die in den einzelnen Modulen (ignition.py, diagnostic.py, supply.py, ...)
implementierten Python-Funktionen mit ihren Verträgen registriert.
"""
from contextvars import ContextVar
from dataclasses import dataclass
from decimal import Decimal
import json
from pathlib import Path
import re
from typing import Any

from tcg.core.contracts import OperationContract, ParameterSpec, build_registry
from tcg.core.model import SpecError
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
_current_can_signal: ContextVar[str | None] = ContextVar('_current_can_signal', default=None)


@dataclass(frozen=True)
class CanSignalResource:
    """Wrapper um Resource('can_signal'), der das aktuelle Signal im Thread-/Task-Kontext speichert."""
    resource: Resource

    @property
    def kind(self) -> str:
        return self.resource.kind

    @property
    def lexical(self) -> re.Pattern:
        return self.resource.lexical

    def convert(self, text: str, profile: Any) -> str:
        res = self.resource.convert(text, profile)
        _current_can_signal.set(res)
        return res


CAN_SIGNAL = CanSignalResource(Resource('can_signal'))

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


def _load_can_signal_enums() -> tuple[dict[str, dict[str, Decimal]], set[str]]:
    """Lädt signalabhängige Enum-Zustände aus der CAN-Signaldatenbank (inputs/can_signals.json)."""
    signal_enums: dict[str, dict[str, Decimal]] = {}
    all_known_states: set[str] = set()

    default_signals = {
        'DoorContactStatus': {'Geschlossen': Decimal('0'), 'Offen': Decimal('1')},
        'InterlockStatus': {'Offen': Decimal('0'), 'Geschlossen': Decimal('1')},
        'Clamp15Status': {'Aus': Decimal('0'), 'An': Decimal('1')},
        'BMSState': {
            'Init': Decimal('0'), 'Standby': Decimal('1'), 'Precharge': Decimal('2'),
            'DriveReady': Decimal('3'), 'Charge': Decimal('4'), 'Fault': Decimal('5'),
        },
        'HVMainPosContactState': {'Offen': Decimal('0'), 'Geschlossen': Decimal('1'), 'Fehler': Decimal('2')},
        'HVMainNegContactState': {'Offen': Decimal('0'), 'Geschlossen': Decimal('1'), 'Fehler': Decimal('2')},
        'PrechargeContactState': {'Offen': Decimal('0'), 'Geschlossen': Decimal('1'), 'Fehler': Decimal('2')},
        'CrashSignal': {'Kein Crash': Decimal('0'), 'Crash erkannt': Decimal('1')},
        'BalancingActive': {'Inaktiv': Decimal('0'), 'Aktiv': Decimal('1')},
        'CoolingRequest': {'Aus': Decimal('0'), 'Stufe 1': Decimal('1'), 'Stufe 2': Decimal('2')},
        'IsolationStatus': {'Normal': Decimal('0'), 'Warnung': Decimal('1'), 'Fehler': Decimal('2')},
    }
    for sname, states in default_signals.items():
        signal_enums[sname] = {}
        for desc, val in states.items():
            signal_enums[sname][desc] = val
            signal_enums[sname][desc.replace(' ', '_')] = val
            all_known_states.add(desc)
            all_known_states.add(desc.replace(' ', '_'))

    can_json = Path(__file__).resolve().parent.parent / 'inputs' / 'can_signals.json'
    if can_json.exists():
        try:
            with open(can_json, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for sname, sdata in data.get('signals', {}).items():
                if 'values' in sdata:
                    if sname not in signal_enums:
                        signal_enums[sname] = {}
                    for raw_val, desc in sdata['values'].items():
                        val = Decimal(str(raw_val))
                        signal_enums[sname][desc] = val
                        signal_enums[sname][desc.replace(' ', '_')] = val
                        all_known_states.add(desc)
                        all_known_states.add(desc.replace(' ', '_'))
        except Exception:
            pass

    return signal_enums, all_known_states


@dataclass(frozen=True)
class SymbolicCanSignalValue:
    """Signalabhängige Quantity-Erweiterung für CAN-Signale: akzeptiert Zahlen/Einheiten und DBC-Enums."""
    quantity: Quantity
    signal_enums: dict[str, dict[str, Decimal]]
    all_known_states: set[str]

    @property
    def unit(self):
        return self.quantity.unit

    @property
    def factors(self):
        return self.quantity.factors

    @property
    def dimension(self):
        return self.quantity.dimension

    @property
    def minimum(self):
        return self.quantity.minimum

    @property
    def maximum(self):
        return self.quantity.maximum

    @property
    def lexical(self):
        return re.compile(
            r'(?:-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?(?:\s*[A-Za-z°%/Ω]+)?|[A-Za-z_][A-Za-z0-9_]*|"(?:[^"\\]|\\.)*")'
        )

    def convert(self, text, profile):
        clean = text.strip('"\'')
        sig = _current_can_signal.get()

        if sig is not None:
            sig_enums = self.signal_enums.get(sig, {})
            # 1. Exakter Match für dieses konkrete Signal
            if clean in sig_enums:
                return sig_enums[clean]
            clean_norm = clean.replace(' ', '_').lower()
            for k, v in sig_enums.items():
                if k.lower() == clean.lower() or k.replace(' ', '_').lower() == clean_norm:
                    return v

            # 2. Wenn der Bezeichner ein bekannter DBC-Zustand ist, aber nicht zu DIESEM Signal gehört -> Fehler!
            if clean in self.all_known_states or clean.replace('_', ' ') in self.all_known_states:
                allowed = sorted(set(sig_enums.keys()))
                allowed_str = f"gültige Zustände: {', '.join(allowed)}" if allowed else "keine (kontinuierliches Signal)"
                raise SpecError(
                    f"Zustand {clean!r} ist für CAN-Signal {sig!r} nicht gültig; {allowed_str}"
                )
        elif clean in self.all_known_states or clean.replace('_', ' ') in self.all_known_states:
            raise SpecError(f"Symbolischer Zustand {clean!r} erfordert Signal-Kontext")

        # 3. Standard-Zahlenkonvertierung oder Schleifenvariable
        return self.quantity.convert(text, profile)


_SIGNAL_ENUMS, _ALL_KNOWN_STATES = _load_can_signal_enums()
CAN_SIGNAL_VALUE = SymbolicCanSignalValue(BASE_CAN_SIGNAL_VALUE, _SIGNAL_ENUMS, _ALL_KNOWN_STATES)

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

