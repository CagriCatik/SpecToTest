"""Generic, deterministic parameter types used by operation contracts."""
from contextvars import ContextVar, Token
from dataclasses import dataclass
from decimal import Decimal as DecimalValue, InvalidOperation, localcontext
import json
import re

from .model import SpecError, VariableRef

_step_context: ContextVar[dict[str, str] | None] = ContextVar('_step_context', default=None)


def set_step_context(raw_parameters: dict[str, str]) -> Token:
    """Setzt die Rohparameter der aktuellen Anweisung im Thread-/Task-Kontext."""
    return _step_context.set(raw_parameters)


def get_step_context() -> dict[str, str] | None:
    """Gibt die Rohparameter der aktuellen Anweisung zurück (oder None außerhalb von resolve)."""
    return _step_context.get()


def reset_step_context(token: Token) -> None:
    """Setzt den Anweisungskontext nach der Auflösung zurück."""
    _step_context.reset(token)


IDENTIFIER_PATTERN = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
QUANTITY_LITERAL = re.compile(r'^(-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?)\s*([A-Za-z°%/Ω]+)?$')



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
    lexical: re.Pattern = re.compile(r'-?(?:0|[1-9][0-9]*)|[A-Za-z_][A-Za-z0-9_]*')

    def convert(self, text, profile):
        if IDENTIFIER_PATTERN.fullmatch(text):
            return VariableRef(text)
        value = int(text)
        if (self.minimum is not None and value < self.minimum) or (self.maximum is not None and value > self.maximum):
            raise SpecError(f'{value} outside allowed range [{self.minimum}, {self.maximum}]')
        return value


@dataclass(frozen=True)
class Decimal:
    minimum: DecimalValue | None = None
    maximum: DecimalValue | None = None
    lexical: re.Pattern = re.compile(r'-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?|[A-Za-z_][A-Za-z0-9_]*')

    def convert(self, text, profile):
        if IDENTIFIER_PATTERN.fullmatch(text):
            return VariableRef(text)
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
    lexical: re.Pattern = re.compile(r'(?:-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?(?:\s*[A-Za-z°%/Ω]+)?|[A-Za-z_][A-Za-z0-9_]*)')

    def convert(self, text, profile):
        if IDENTIFIER_PATTERN.fullmatch(text):
            return VariableRef(text)
        match = QUANTITY_LITERAL.fullmatch(text)
        if not match:
            raise SpecError(f'expected quantity (e.g. 7000mV, 13.8V) or variable, got {text!r}')
        factors = dict(self.factors)
        unit = match[2]
        if unit is not None:
            if unit not in factors:
                raise SpecError(f'unit {unit!r} not allowed; allowed: {", ".join(factors)}')
            factor = factors[unit]
        else:
            factor = DecimalValue('1')
        number = _decimal(match[1], 'quantity')
        with localcontext() as context:
            context.prec = max(28, len(number.as_tuple().digits) + len(factor.as_tuple().digits) + 2)
            value = number * factor
        if not self.minimum <= value <= self.maximum:
            raise SpecError(f'{text!r} outside {self.dimension} range [{self.minimum}, {self.maximum}] {self.unit}')
        return value


@dataclass(frozen=True)
class Resource:
    """An identifier declared by a resource profile under one explicit kind."""
    kind: str
    lexical: re.Pattern = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')

    def convert(self, text, profile):
        allowed = profile.resources.get(self.kind)
        if allowed is None:
            raise SpecError(f'resource kind {self.kind!r} is absent from profile {profile.profile_id}')
        if text not in allowed:
            raise SpecError(f'unknown {self.kind} {text!r}; profile declares: {", ".join(allowed)}')
        return text
