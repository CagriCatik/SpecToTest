"""Generic explicit operation contracts and signature verification."""
from dataclasses import dataclass, replace
import importlib
import inspect
import re

from .model import PHASES, SpecError
from .parameters import dependencies_of, resolution_order


def capability_problems(names, where):
    # Imported lazily so the generic core does not depend on the communication
    # package at import time.
    from tcg.comm.capabilities import capability_problems as check
    return check(names, where)


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
    #: Test bench capabilities this operation needs (see tcg.comm.capabilities).
    #: Declared here so the requirement travels with the contract and can be checked
    #: at the bench adapter boundary before a test runs.
    capabilities: frozenset = frozenset()

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
    module_name = getattr(function, '__module__', None)
    function_name = getattr(function, '__name__', None)
    qualified_name = getattr(function, '__qualname__', None)
    if (not isinstance(module_name, str) or module_name == '__main__' or
            not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module_name)):
        problems.append(f'function module {module_name!r} is not importable by generated code')
    elif not isinstance(function_name, str) or not re.fullmatch(r'[A-Za-z_]\w*', function_name):
        problems.append(f'function name {function_name!r} is not importable by generated code')
    elif qualified_name != function_name:
        problems.append('registered function must be defined at module level')
    else:
        try:
            module = importlib.import_module(module_name)
        except Exception as error:
            problems.append(f'cannot import function module {module_name!r}: {error}')
        else:
            if getattr(module, function_name, None) is not function:
                problems.append(f'{module_name}.{function_name} does not reference the registered function')
    names = [parameter.name for parameter in contract.parameters]
    if len(names) != len(set(names)) or 'bench' in names:
        problems.append(f'duplicate or reserved parameter names {names}')
    problems.extend(dependency_problems(contract))
    problems.extend(capability_problems(contract.capabilities, 'capabilities'))
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


def dependency_problems(contract):
    """Check that every declared parameter dependency names a resolvable sibling."""
    problems, names = [], {parameter.name for parameter in contract.parameters}
    for parameter in contract.parameters:
        for dependency in dependencies_of(parameter.type):
            if dependency == parameter.name:
                problems.append(f'parameter {parameter.name!r} depends on itself')
            elif dependency not in names:
                problems.append(f'parameter {parameter.name!r} depends on unknown '
                                f'parameter {dependency!r}')
    if not problems:
        try:
            resolution_order(contract.parameters)
        except SpecError as error:
            problems.extend(error.problems)
    return problems


def bind_registry(registry, project_data):
    """Return a copy of `registry` whose parameter types are bound to the active project.

    A parameter type that needs project configuration implements
    `bind(project_data)` and returns a new, immutable instance; every other type is
    reused unchanged. The input registry is never mutated, so two projects loaded in
    one process cannot influence one another.
    """
    bound = {}
    for operation_id, contract in registry.items():
        parameters = tuple(
            replace(parameter, type=parameter.type.bind(project_data))
            if hasattr(parameter.type, 'bind') else parameter
            for parameter in contract.parameters
        )
        bound[operation_id] = (contract if parameters == contract.parameters
                               else replace(contract, parameters=parameters))
    return bound


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
