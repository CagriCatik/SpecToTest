"""Generic, deterministic parameter types used by operation contracts.

Parameter types are immutable value objects. A simple type converts one matched
text on its own::

    type.convert(text, profile) -> value

A type whose meaning depends on a sibling argument of the *same* operation call
declares the names of those siblings and receives them explicitly::

    type.depends_on = ('signal',)
    type.convert(text, profile, dependencies={'signal': 'DoorContactStatus'}) -> value

Nothing is carried between calls: there is no ambient context, no module state and
no "last used argument". `resolution_order` fixes the conversion order from the
operation contract alone, so the order of placeholders in a sentence template is
irrelevant. See `tcg/core/mapping.py:resolve` for the processing steps.

A type may additionally offer `bind(project_data)`, returning a new instance bound
to the active project's configuration (see `tcg.core.contracts.bind_registry`), and
`describe_unresolved_identifier(name)`, contributing a hint when an identifier can
be resolved neither as a value nor as a variable.
"""
from dataclasses import dataclass
from decimal import Decimal as DecimalValue, InvalidOperation, localcontext
import json
import re

from .model import SpecError, VariableRef

DEPENDENCY_ATTRIBUTE = 'depends_on'


def dependencies_of(parameter_type):
    """Names of the sibling operation parameters this parameter type needs, if any."""
    return tuple(getattr(parameter_type, DEPENDENCY_ATTRIBUTE, ()) or ())


def resolution_order(parameters):
    """Order parameter specs so every dependency is converted before its dependents.

    Input order decides ties, so passing the contract's own parameter tuple makes the
    result independent of how a sentence template arranges its placeholders. Raises
    SpecError on a dependency cycle.
    """
    parameters = tuple(parameters)
    by_name = {parameter.name: parameter for parameter in parameters}
    order, state = [], {}

    def visit(parameter, trail):
        status = state.get(parameter.name)
        if status == 'done':
            return
        if status == 'active':
            raise SpecError('cyclic parameter dependency: '
                            f'{" -> ".join(trail + [parameter.name])}')
        state[parameter.name] = 'active'
        for name in dependencies_of(parameter.type):
            dependency = by_name.get(name)
            if dependency is not None:
                visit(dependency, trail + [parameter.name])
        state[parameter.name] = 'done'
        order.append(parameter)

    for parameter in parameters:
        visit(parameter, [])
    return tuple(order)


def convert_argument(parameter, text, profile, resolved):
    """Convert one matched text for `parameter`, passing it the siblings it declared.

    `resolved` maps already converted sibling parameter names to their values.
    """
    names = dependencies_of(parameter.type)
    if not names:
        return parameter.type.convert(text, profile)
    missing = [name for name in names if name not in resolved]
    if missing:
        raise SpecError(f'parameter {parameter.name!r} cannot be resolved without '
                        f'{", ".join(missing)} in the same operation call')
    return parameter.type.convert(text, profile,
                                  dependencies={name: resolved[name] for name in names})


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
