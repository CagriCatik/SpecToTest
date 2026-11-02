"""Generic explicit operation contracts and signature verification."""
from dataclasses import dataclass
import inspect
import re

from .model import PHASES


class ContractError(Exception):
    """A developer-defined operation contract and its implementation disagree."""


class _Required:
    def __repr__(self):
        return 'REQUIRED'


REQUIRED = _Required()


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    type: object
    default: object = REQUIRED

    @property
    def required(self):
        return self.default is REQUIRED


@dataclass(frozen=True)
class OperationContract:
    id: str
    function: object
    parameters: tuple
    phases: frozenset

    def parameter(self, name):
        return next((parameter for parameter in self.parameters if parameter.name == name), None)


def signature_problems(contract):
    problems, function = [], contract.function
    if not callable(function):
        return ['registered function is not callable']
    if not re.fullmatch(r'[a-z][a-z0-9_]*', contract.id):
        problems.append(f'invalid operation id {contract.id!r}')
    if not contract.phases or not set(contract.phases) <= set(PHASES):
        problems.append(f'invalid phases {sorted(contract.phases)}')
    names = [parameter.name for parameter in contract.parameters]
    if len(names) != len(set(names)) or 'bench' in names:
        problems.append(f'duplicate or reserved parameter names {names}')
    parameters = list(inspect.signature(function).parameters.values())
    first = parameters[0] if parameters else None
    if first is None or first.name != 'bench' or first.default is not inspect.Parameter.empty or first.kind not in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
        problems.append('first parameter must be positional `bench` without a default')
    actual = {parameter.name: parameter for parameter in parameters[1:]}
    for parameter in parameters[1:]:
        if parameter.kind is not inspect.Parameter.KEYWORD_ONLY:
            problems.append(f'parameter {parameter.name!r} must be keyword-only')
    for missing in sorted(set(names) - set(actual)):
        problems.append(f'contract parameter {missing!r} missing in function signature')
    for extra in sorted(set(actual) - set(names)):
        problems.append(f'function parameter {extra!r} not declared in contract')
    for spec in contract.parameters:
        parameter = actual.get(spec.name)
        if parameter is None:
            continue
        if spec.required and parameter.default is not inspect.Parameter.empty:
            problems.append(f'required parameter {spec.name!r} has a function default')
        if not spec.required and (parameter.default is inspect.Parameter.empty or parameter.default != spec.default or type(parameter.default) is not type(spec.default)):
            problems.append(f'optional parameter {spec.name!r} default differs from contract')
    return problems


def build_registry(contracts):
    registry, problems = {}, []
    for contract in contracts:
        if contract.id in registry:
            problems.append(f'{contract.id}: duplicate operation id')
        registry[contract.id] = contract
        problems.extend(f'{contract.id}: {problem}' for problem in signature_problems(contract))
    if problems:
        raise ContractError('\n'.join(problems))
    return registry
