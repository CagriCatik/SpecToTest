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
CAN_SIGNAL = Resource('can_signal')

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


def load_can_signal_database(source: str | Path | dict | None = None) -> tuple[dict[str, dict[str, Decimal]], set[str]]:
    """Lädt signalabhängige Enum-Zustände strikt und ausschließlich aus der übergebenen CAN-Signaldatenbank.

    source kann ein Dateipfad (str oder Path) oder ein bereits geparstes dict sein.
    Wird source=None übergeben, wird standardmäßig inputs/can_signals.json geladen.

    Fehlerbehandlung:
    - Fehlende Datei -> FileNotFoundError
    - Ungültiges JSON / ungültiges Schema -> SpecError
    - Keine stillschweigenden Fallbacks auf festverdrahtete Demo-Zustände!
    """
    if source is None:
        source = Path(__file__).resolve().parent.parent / 'inputs' / 'can_signals.json'

    if isinstance(source, (str, Path)):
        path = Path(source)
        if not path.is_file():
            raise FileNotFoundError(f"CAN-Signaldatenbank nicht gefunden: {path}")
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except json.JSONDecodeError as err:
            raise SpecError(f"Beschädigte CAN-Signaldatenbank ({path.name}): {err}") from None
        except OSError as err:
            raise SpecError(f"Konnte CAN-Signaldatenbank nicht lesen ({path.name}): {err.strerror}") from None
    elif isinstance(source, dict):
        data = source
    else:
        raise SpecError(f"Ungültige CAN-Signaldatenbank-Quelle: {type(source).__name__}")

    if not isinstance(data, dict) or 'signals' not in data or not isinstance(data['signals'], dict):
        raise SpecError("Ungültiges Schema der CAN-Signaldatenbank: Schlüssel 'signals' fehlt oder ist kein Objekt")

    signal_enums: dict[str, dict[str, Decimal]] = {}
    all_known_states: set[str] = set()

    for sname, sdata in data['signals'].items():
        if isinstance(sdata, dict) and 'values' in sdata and isinstance(sdata['values'], dict):
            enums_for_signal: dict[str, Decimal] = {}
            for raw_val, desc in sdata['values'].items():
                try:
                    val = Decimal(str(raw_val))
                except Exception:
                    raise SpecError(f"Ungültiger Rohwert {raw_val!r} für Signal {sname!r} in CAN-Datenbank")
                enums_for_signal[desc] = val
                enums_for_signal[desc.replace(' ', '_')] = val
                all_known_states.add(desc)
                all_known_states.add(desc.replace(' ', '_'))
            if enums_for_signal:
                signal_enums[sname] = enums_for_signal

    return signal_enums, all_known_states


@dataclass
class SymbolicCanSignalValue:
    """Signalabhängige Quantity-Erweiterung für CAN-Signale: akzeptiert Zahlen/Einheiten und DBC-Enums."""
    quantity: Quantity
    signal_enums: dict[str, dict[str, Decimal]]
    all_known_states: set[str]

    def configure_database(self, source: str | Path | dict | None = None) -> None:
        """Aktualisiert die Enum-Zustände aus einer expliziten Signaldatenbank."""
        enums, states = load_can_signal_database(source)
        self.signal_enums = enums
        self.all_known_states = states

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
        from tcg.core.parameters import get_step_context
        ctx = get_step_context()
        sig = (ctx.get('signal') or ctx.get('can_signal')) if ctx else None
        if sig is not None:
            sig = sig.strip('"\'')

        if sig is not None:
            sig_enums = self.signal_enums.get(sig, {})
            # 1. Exakter Match für dieses konkrete Signal
            if clean in sig_enums:
                return sig_enums[clean]
            clean_norm = clean.replace(' ', '_').lower()
            for k, v in sig_enums.items():
                if k.lower() == clean.lower() or k.replace(' ', '_').lower() == clean_norm:
                    return v

            # 2. Wenn der Bezeichner ein bekannter Zustand ist, aber nicht zu DIESEM Signal gehört -> Fehler!
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


_SIGNAL_ENUMS, _ALL_KNOWN_STATES = load_can_signal_database()
CAN_SIGNAL_VALUE = SymbolicCanSignalValue(BASE_CAN_SIGNAL_VALUE, _SIGNAL_ENUMS, _ALL_KNOWN_STATES)


def configure_can_database(source: str | Path | dict | None = None) -> None:
    """Konfiguriert die aktive CAN-Signaldatenbank für alle CAN-Operationen."""
    CAN_SIGNAL_VALUE.configure_database(source)


_load_can_signal_enums = load_can_signal_database

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

