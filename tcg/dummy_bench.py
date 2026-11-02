"""A deterministic demo adapter with observable diagnostic, HMI and parameter state.

The rules here are demonstration-only. They are not known by the compiler, renderer
or runtime and make no statement about a real bench or ECU.
"""
from dataclasses import dataclass
from decimal import Decimal
import json

from .model import SpecError


@dataclass(frozen=True)
class DemoConfig:
    initial_supply: Decimal
    controller: str
    diagnostic_code: str
    threshold: Decimal
    activation_delay: Decimal
    screens: dict
    initial_parameters: dict


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
    if not isinstance(data, dict) or set(data) != required:
        raise SpecError(f'{path.name}: expected exactly {sorted(required)}')
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
    return DemoConfig(_decimal(data['initial_supply'], 'initial_supply'), controller, code,
                      _decimal(data['threshold'], 'threshold'), _decimal(data['activation_delay'], 'activation_delay'),
                      dict(data['screens']), {key: _decimal(value, f'initial_parameters.{key}')
                                               for key, value in data['initial_parameters'].items()})


class DummyBench:
    def __init__(self, config):
        self.config = config
        self.time = Decimal('0')
        self.supply = config.initial_supply
        self.low_since = None
        self.diagnostic = False
        self.selected_screen = None
        self.parameters = dict(config.initial_parameters)
        self._update()

    def now(self):
        return self.time

    def set_supply(self, value):
        self.supply = value
        self._update()

    def wait(self, seconds):
        if seconds < 0:
            raise ValueError('negative waits are invalid')
        self.time += seconds
        self._update()

    def diagnostic_active(self, controller, code):
        if (controller, code) != (self.config.controller, self.config.diagnostic_code):
            raise ValueError(f'diagnostic {controller}/{code} is not provided by this demo bench')
        return self.diagnostic

    def select_screen(self, screen):
        if screen not in self.config.screens:
            raise ValueError(f'screen {screen!r} is not provided by this demo bench')
        self.selected_screen = screen

    def screen_text(self):
        return '' if self.selected_screen is None else self.config.screens[self.selected_screen]

    def write_parameter(self, parameter, value):
        if parameter not in self.parameters:
            raise ValueError(f'parameter {parameter!r} is not provided by this demo bench')
        self.parameters[parameter] = value

    def read_parameter(self, parameter):
        if parameter not in self.parameters:
            raise ValueError(f'parameter {parameter!r} is not provided by this demo bench')
        return self.parameters[parameter]

    def _update(self):
        if self.supply < self.config.threshold:
            if self.low_since is None:
                self.low_since = self.time
            self.diagnostic = self.time - self.low_since >= self.config.activation_delay
        else:
            self.low_since, self.diagnostic = None, False
