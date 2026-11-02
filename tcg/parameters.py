"""Generic, deterministic parameter types used by operation contracts."""
from dataclasses import dataclass
from decimal import Decimal as DecimalValue, InvalidOperation
import json
import re

from .model import SpecError


def _decimal(text, label):
    try:
        return DecimalValue(text.replace(',', '.'))
    except (InvalidOperation, AttributeError):
        raise SpecError(f'{label}: invalid decimal {text!r}') from None


@dataclass(frozen=True)
class String:
    """A JSON string literal, so arbitrary display text stays unambiguous."""
    lexical: re.Pattern = re.compile(r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9a-fA-F]{4}))*"')

    def convert(self, text, profile):
        try:
            value = json.loads(text)
        except json.JSONDecodeError:
            raise SpecError(f'expected JSON string, got {text!r}') from None
        if not isinstance(value, str):
            raise SpecError(f'expected JSON string, got {text!r}')
        return value


@dataclass(frozen=True)
class Boolean:
    true_text: str = 'true'
    false_text: str = 'false'

    @property
    def lexical(self):
        return re.compile(f'(?:{re.escape(self.true_text)}|{re.escape(self.false_text)})')

    def convert(self, text, profile):
        return text == self.true_text


@dataclass(frozen=True)
class Integer:
    minimum: int | None = None
    maximum: int | None = None
    lexical: re.Pattern = re.compile(r'-?(?:0|[1-9][0-9]*)')

    def convert(self, text, profile):
        value = int(text)
        if (self.minimum is not None and value < self.minimum) or (self.maximum is not None and value > self.maximum):
            raise SpecError(f'{value} outside allowed range [{self.minimum}, {self.maximum}]')
        return value


@dataclass(frozen=True)
class Decimal:
    minimum: DecimalValue | None = None
    maximum: DecimalValue | None = None
    lexical: re.Pattern = re.compile(r'-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?')

    def convert(self, text, profile):
        value = _decimal(text, 'decimal')
        if (self.minimum is not None and value < self.minimum) or (self.maximum is not None and value > self.maximum):
            raise SpecError(f'{value} outside allowed range [{self.minimum}, {self.maximum}]')
        return value


@dataclass(frozen=True)
class Enum:
    options: tuple  # ((specified word, typed value), ...)
    lexical: re.Pattern = re.compile(r'\S+')

    def convert(self, text, profile):
        options = dict(self.options)
        if text not in options:
            raise SpecError(f'{text!r} not allowed; allowed: {", ".join(options)}')
        return options[text]


@dataclass(frozen=True)
class Quantity:
    """A bounded physical quantity; all rules belong to this contract type."""
    dimension: str
    unit: str
    factors: tuple  # ((input unit, Decimal factor to unit), ...)
    minimum: DecimalValue
    maximum: DecimalValue
    lexical: re.Pattern = re.compile(r'-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)? \S+')

    def convert(self, text, profile):
        match = re.fullmatch(r'(-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?) (\S+)', text)
        if not match:
            raise SpecError(f'expected "<number> <unit>", got {text!r}')
        factors = dict(self.factors)
        if match[2] not in factors:
            raise SpecError(f'unit {match[2]!r} not allowed; allowed: {", ".join(factors)}')
        value = _decimal(match[1], 'quantity') * factors[match[2]]
        if not self.minimum <= value <= self.maximum:
            raise SpecError(f'{text!r} outside {self.dimension} range [{self.minimum}, {self.maximum}] {self.unit}')
        return value


@dataclass(frozen=True)
class Resource:
    """An identifier declared by a resource profile under one explicit kind."""
    kind: str
    lexical: re.Pattern = re.compile(r'[A-Z][A-Z0-9_]*')

    def convert(self, text, profile):
        allowed = profile.resources.get(self.kind)
        if allowed is None:
            raise SpecError(f'resource kind {self.kind!r} is absent from profile {profile.profile_id}')
        if text not in allowed:
            raise SpecError(f'unknown {self.kind} {text!r}; profile declares: {", ".join(allowed)}')
        return text
