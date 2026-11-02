"""Outbound Adapter: Deterministic in-memory test bench satisfying BenchPort."""
from dataclasses import dataclass
from decimal import Decimal
import json

from tcg.core.model import SpecError
from tcg.ports.bench import BenchPort


@dataclass(frozen=True)
class DemoConfig:
    initial_supply: Decimal
    controller: str
    diagnostic_code: str
    threshold: Decimal
    activation_delay: Decimal
    screens: dict
    initial_parameters: dict
    fault_codes: dict = None
    can_signals: dict = None


def _decimal(value, where):
    if not isinstance(value, str):
        raise SpecError(f'{where}: decimal must be a string')
    try:
        return Decimal(value)
    except Exception:
        raise SpecError(f'{where}: invalid decimal {value!r}') from None


def load_config(path, profile):
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except OSError as error:
        raise SpecError(f'{path.name}: cannot read demo bench config ({error.strerror})') from None
    except json.JSONDecodeError as error:
        raise SpecError(f'{path.name}: invalid JSON: {error}') from None
    required = {'initial_supply', 'controller', 'diagnostic_code', 'threshold', 'activation_delay', 'screens', 'initial_parameters'}
    optional = {'fault_codes', 'can_signals'}
    if not isinstance(data, dict) or not (required <= set(data) <= (required | optional)):
        raise SpecError(f'{path.name}: expected fields {sorted(required)}')
    controller, code = data['controller'], data['diagnostic_code']
    if controller not in profile.resources.get('controller', ()):
        raise SpecError(f'{path.name}: controller {controller!r} is absent from resource profile')
    if code not in profile.resources.get('diagnostic_code', ()):
        raise SpecError(f'{path.name}: diagnostic_code {code!r} is absent from resource profile')
    if not isinstance(data['screens'], dict) or set(data['screens']) - set(profile.resources.get('screen', ())):
        raise SpecError(f'{path.name}: screens must only configure declared screen resources')
    if not isinstance(data['initial_parameters'], dict) or set(data['initial_parameters']) != set(profile.resources.get('parameter', ())):
        raise SpecError(f'{path.name}: initial_parameters must configure every declared parameter')
    if not all(isinstance(value, str) for value in data['screens'].values()):
        raise SpecError(f'{path.name}: screen texts must be strings')
    fault_codes = data.get('fault_codes')
    can_signals = data.get('can_signals')
    if can_signals is not None:
        can_signals = {k: _decimal(v, f'can_signals.{k}') for k, v in can_signals.items()}
    return DemoConfig(
        initial_supply=_decimal(data['initial_supply'], 'initial_supply'),
        controller=controller,
        diagnostic_code=code,
        threshold=_decimal(data['threshold'], 'threshold'),
        activation_delay=_decimal(data['activation_delay'], 'activation_delay'),
        screens=dict(data['screens']),
        initial_parameters={key: _decimal(value, f'initial_parameters.{key}')
                            for key, value in data['initial_parameters'].items()},
        fault_codes=fault_codes if fault_codes is not None else {controller: [code]},
        can_signals=can_signals,
    )


class DummyBench(BenchPort):
    """In-memory simulated test bench conforming to BenchPort."""

    def __init__(self, config):
        self.config = config
        self.time = Decimal('0')
        self.supply = config.initial_supply
        self.ignition = False
        self.fault_memory = {}
        self.low_since = None
        self.diagnostic = False
        self.selected_screen = None
        self.parameters = dict(config.initial_parameters)
        self.can_signals = dict(getattr(config, 'can_signals', None) or {})
        self.can_bus_active = True
        self.log_entries = []
        self._update()

    def _log(self, operation: str, **kwargs):
        self.log_entries.append({
            'time': f"{self.time:.3f} s",
            'operation': operation,
            'details': {k: str(v) for k, v in kwargs.items()}
        })

    def now(self) -> Decimal:
        return self.time

    def set_ignition(self, state: bool) -> None:
        if type(state) is not bool:
            raise TypeError('ignition state must be a boolean')
        self._log('set_ignition', state=state)
        self.ignition = state

    def set_supply(self, value: Decimal) -> None:
        self._log('set_supply', value=value)
        self.supply = value
        self._update()

    def set_battery_voltage(self, value: Decimal) -> None:
        self.set_supply(value)

    def clear_fault_memory(self, ecu: str) -> None:
        self._log('clear_fault_memory', ecu=ecu)
        self.fault_memory[ecu] = []

    def read_fault_memory(self, ecu: str) -> list[str]:
        entries = self.fault_memory.setdefault(ecu, [])
        if self.supply < self.config.threshold:
            configured = self.config.fault_codes or {}
            codes = configured.get(ecu)
            if codes is None:
                codes = [self.config.diagnostic_code] if ecu == self.config.controller else []
            for c in codes:
                if c not in entries:
                    entries.append(c)
        self._log('read_fault_memory', ecu=ecu, returned_entries=list(entries))
        return list(entries)

    def wait(self, seconds: Decimal | float | int) -> None:
        if seconds < 0:
            raise ValueError('negative waits are invalid')
        self._log('wait', seconds=seconds)
        self.time += seconds
        self._update()

    def diagnostic_active(self, controller: str, code: str) -> bool:
        if (controller, code) == (self.config.controller, self.config.diagnostic_code):
            return self.diagnostic
        return code in self.fault_memory.get(controller, [])

    def select_screen(self, screen: str) -> None:
        if screen not in self.config.screens:
            raise ValueError(f'screen {screen!r} is not provided by this demo bench')
        self._log('select_screen', screen=screen)
        self.selected_screen = screen

    def screen_text(self) -> str:
        return '' if self.selected_screen is None else self.config.screens[self.selected_screen]

    def write_parameter(self, parameter: str, value) -> None:
        if parameter not in self.parameters:
            raise ValueError(f'parameter {parameter!r} is not provided by this demo bench')
        self._log('write_parameter', parameter=parameter, value=value)
        self.parameters[parameter] = value

    def read_parameter(self, parameter: str):
        if parameter not in self.parameters:
            raise ValueError(f'parameter {parameter!r} is not provided by this demo bench')
        val = self.parameters[parameter]
        self._log('read_parameter', parameter=parameter, value=val)
        return val

    def _update(self):
        if self.supply < self.config.threshold:
            if self.low_since is None:
                self.low_since = self.time
            self.diagnostic = self.time - self.low_since >= self.config.activation_delay
        else:
            self.low_since, self.diagnostic = None, False

        # BMS Fault Detection Simulation
        bms_entries = self.fault_memory.setdefault('BMS', [])
        if self.can_signals.get('CellVoltageMax', Decimal('0')) >= Decimal('4.25'):
            if 'DTC_BMS_CELL_OVERVOLTAGE' not in bms_entries:
                bms_entries.append('DTC_BMS_CELL_OVERVOLTAGE')
        if self.can_signals.get('CellVoltageMin', Decimal('3.7')) <= Decimal('2.80'):
            if 'DTC_BMS_CELL_UNDERVOLTAGE' not in bms_entries:
                bms_entries.append('DTC_BMS_CELL_UNDERVOLTAGE')
        if self.can_signals.get('CellTempMax', Decimal('25')) >= Decimal('60'):
            if 'DTC_BMS_OVERTEMPERATURE' not in bms_entries:
                bms_entries.append('DTC_BMS_OVERTEMPERATURE')
        if self.can_signals.get('IsolationResistance', Decimal('1500')) <= Decimal('100'):
            if 'DTC_BMS_ISOLATION_FAULT' not in bms_entries:
                bms_entries.append('DTC_BMS_ISOLATION_FAULT')
        if self.can_signals.get('InterlockStatus', Decimal('1')) == Decimal('0'):
            if 'DTC_BMS_INTERLOCK_OPEN' not in bms_entries:
                bms_entries.append('DTC_BMS_INTERLOCK_OPEN')

    # --- CAN-Bus & Vector CANoe / dSPACE ControlDesk Interface ---
    def set_can_signal(self, signal: str, value) -> None:
        val = Decimal(str(value)) if not isinstance(value, Decimal) else value
        self._log('set_can_signal', signal=signal, value=val)
        self.can_signals[signal] = val
        self._update()

    def get_can_signal(self, signal: str) -> Decimal:
        val = self.can_signals.get(signal, Decimal('0'))
        self._log('get_can_signal', signal=signal, value=val)
        return val

    # Vector CANoe / CANalyzer style aliases
    def set_signal(self, signal: str, value) -> None:
        self.set_can_signal(signal, value)

    def get_signal(self, signal: str) -> Decimal:
        return self.get_can_signal(signal)

    # dSPACE ControlDesk XIL API style aliases
    def write_variable(self, variable: str, value) -> None:
        if variable in self.parameters:
            self.write_parameter(variable, value)
        else:
            self.set_can_signal(variable, value)

    def read_variable(self, variable: str):
        if variable in self.parameters:
            return self.read_parameter(variable)
        return self.get_can_signal(variable)


class VectorDummyBench(DummyBench):
    """Spezifischer Testbench-Adapter mit Vector CANoe/CANalyzer-Semantik."""


class ControlDeskDummyBench(DummyBench):
    """Spezifischer Testbench-Adapter mit dSPACE ControlDesk HiL-Semantik."""


