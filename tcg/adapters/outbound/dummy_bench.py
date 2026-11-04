"""Outbound Adapter: Deterministic in-memory test bench satisfying BenchPort."""
from dataclasses import dataclass
from decimal import Decimal
import json

from tcg.core.model import SpecError
from tcg.ports.bench import (
    BenchConnectionError,
    BenchError,
    BenchLimitViolationError,
    BenchPort,
    BenchResourceNotFoundError,
    BenchWriteError,
)


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
    """In-memory simulated test bench conforming to BenchPort.

    Simulates basic electrical supply, ignition, CAN signals, and ECU fault memories.
    Simulation only; does not connect to real physical hardware.
    """
    BENCH_NAME = "DummyBench (Simulation)"
    is_simulation = True

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
        # LIN and service-oriented Ethernet simulation state
        self.lin_schedule = None
        self.sent_frames = []
        self.method_calls = []
        self.method_results = dict(getattr(config, 'method_results', None) or {})
        self.subscribed_events = set()
        self.received_events = {}
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
        self.ignition = state
        if self.ignition != state:
            raise BenchWriteError(f"Ignition state could not be set to {state}")
        self._log('set_ignition', state=state, status='CONFIRMED', verified_state=state)

    def set_supply(self, value: Decimal) -> None:
        val = Decimal(str(value)) if not isinstance(value, Decimal) else value
        if val < Decimal('0'):
            raise BenchLimitViolationError(f"Negative power supply voltage {val}V is invalid")
        if val > Decimal('60'):
            raise BenchLimitViolationError(f"Power supply voltage {val}V exceeds 60V maximum operating limit")
        self.supply = val
        self._update()
        if self.supply != val:
            raise BenchWriteError(f"Power supply voltage readback mismatch: expected {val}V, got {self.supply}V")
        self._log('set_supply', value=val, status='CONFIRMED', verified_value=val)

    def set_battery_voltage(self, value: Decimal) -> None:
        self.set_supply(value)

    def clear_fault_memory(self, ecu: str) -> None:
        self.fault_memory[ecu] = []
        if len(self.fault_memory.get(ecu, [])) != 0:
            raise BenchWriteError(f"Fault memory for ECU {ecu} could not be cleared")
        self._log('clear_fault_memory', ecu=ecu, status='CONFIRMED', cleared=True)

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
            raise BenchResourceNotFoundError(f'screen {screen!r} is not provided by this demo bench')
        self.selected_screen = screen
        if self.selected_screen != screen:
            raise BenchWriteError(f"Screen selection '{screen}' could not be verified")
        self._log('select_screen', screen=screen, status='CONFIRMED', active_screen=screen)

    def screen_text(self) -> str:
        return '' if self.selected_screen is None else self.config.screens[self.selected_screen]

    def write_parameter(self, parameter: str, value) -> None:
        if parameter not in self.parameters:
            raise BenchResourceNotFoundError(f'parameter {parameter!r} is not provided by this demo bench')
        val = Decimal(str(value)) if not isinstance(value, Decimal) and isinstance(value, (int, float, str)) else value
        self.parameters[parameter] = val
        if self.parameters[parameter] != val:
            raise BenchWriteError(f"Parameter '{parameter}' readback mismatch")
        self._log('write_parameter', parameter=parameter, value=val, status='CONFIRMED', verified_value=val)

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
        if not getattr(self, 'can_bus_active', True):
            raise BenchConnectionError(f"Cannot set CAN signal '{signal}': CAN bus is inactive or in Bus-Off state")
        if self.can_signals and signal not in self.can_signals:
            raise BenchResourceNotFoundError(f"CAN signal '{signal}' is not configured on this test bench")
        val = Decimal(str(value)) if not isinstance(value, Decimal) else value
        self.can_signals[signal] = val
        self._update()
        actual = self.can_signals.get(signal)
        if actual != val:
            raise BenchWriteError(f"CAN signal '{signal}' readback mismatch: expected {val}, got {actual}")
        self._log('set_can_signal', signal=signal, value=val, status='CONFIRMED', verified_value=val)

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


    # --- LIN (simulation) ---
    def set_lin_schedule(self, schedule: str) -> None:
        self.lin_schedule = schedule
        self._log('set_lin_schedule', schedule=schedule, status='CONFIRMED')

    def get_lin_schedule(self):
        self._log('get_lin_schedule', schedule=str(self.lin_schedule))
        return self.lin_schedule

    def send_frame(self, frame: str) -> None:
        self.sent_frames.append(frame)
        self._log('send_frame', frame=frame, status='CONFIRMED')

    # --- Service-oriented Ethernet (simulation) ---
    def call_method(self, method: str, argument=''):
        self.method_calls.append((method, argument))
        result = self.method_results.get(method, '')
        self._log('call_method', method=method, argument=str(argument),
                  result=str(result))
        return result

    def subscribe_event(self, event: str) -> None:
        self.subscribed_events.add(event)
        # A subscription is what makes an event observable; the simulation records
        # one delivery per subscription so a test can assert on it.
        self.received_events[event] = self.received_events.get(event, 0) + 1
        self._log('subscribe_event', event=event, status='CONFIRMED')

    def received_event_count(self, event: str) -> int:
        if event not in self.subscribed_events:
            raise BenchResourceNotFoundError(
                f"Event '{event}' was never subscribed on this test bench")
        count = self.received_events.get(event, 0)
        self._log('received_event_count', event=event, count=count)
        return count


class VectorDummyBench(DummyBench):
    """Spezifischer Testbench-Adapter mit Vector CANoe/CANalyzer-Semantik (Simulation)."""
    BENCH_NAME = "Vector CANoe Simulation (Dummy)"


class ControlDeskDummyBench(DummyBench):
    """Spezifischer Testbench-Adapter mit dSPACE ControlDesk HiL-Semantik (Simulation)."""
    BENCH_NAME = "dSPACE ControlDesk Simulation (Dummy)"


class CanOnlyDummyBench(DummyBench):
    """A bench that serves CAN signals only.

    It declares its capabilities explicitly and does not implement LIN or service
    operations, so requesting one fails visibly instead of being simulated away.
    """
    BENCH_NAME = "CAN-only Simulation (Dummy)"
    BENCH_CAPABILITIES = frozenset({'read_signal', 'write_signal'})

    set_lin_schedule = None
    get_lin_schedule = None
    send_frame = None
    call_method = None
    subscribe_event = None
    received_event_count = None


