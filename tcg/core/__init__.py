"""Core domain logic of the Test Case Generator (TCG).

Contains pure domain models, compiler, parameter types, contracts, and mappings.
Completely independent of outside frameworks, protocols, or I/O adapters.
"""
from .model import (
    BinaryCondition,
    BreakStatement,
    Loop,
    PHASES,
    SourceRef,
    SpecError,
    Step,
    TestCase,
    VariableRef,
)
from .compiler import compile_cases
from .contracts import ContractError, OperationContract, ParameterSpec, build_registry
from .mapping import Mapping, load_mapping, load_mappings, parse_mapping_document, resolve
from .parameters import (
    Boolean,
    Decimal,
    Quantity,
    Resource,
    String,
)
from .profile import ResourceProfile, check_profile, load_profile, parse_profile

__all__ = [
    'BinaryCondition',
    'BreakStatement',
    'Loop',
    'PHASES',
    'SourceRef',
    'SpecError',
    'Step',
    'TestCase',
    'VariableRef',
    'compile_cases',
    'ContractError',
    'OperationContract',
    'ParameterSpec',
    'build_registry',
    'Mapping',
    'load_mapping',
    'load_mappings',
    'parse_mapping_document',
    'resolve',
    'Boolean',
    'Decimal',
    'Quantity',
    'Resource',
    'String',
    'ResourceProfile',
    'check_profile',
    'load_profile',
    'parse_profile',
]

