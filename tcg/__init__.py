"""Test Case Generator (TCG) - Hexagonal Architecture.

Layered structure:
- tcg.core: Pure domain model, compiler, contracts, mapping, parameters, profile
- tcg.ports: Driving and driven interfaces (BenchPort, SpecificationParserPort, CodeEmitterPort)
- tcg.adapters: Technology adapters (Inbound: text_parser; Outbound: python_emitter, dummy_bench)
- tcg.runtime: Test execution engine and logging (TestLog, runner)
"""
import sys

__version__ = '0.3.0'

# Ports
from .ports.bench import BenchPort
from .ports.emitter import CodeEmitterPort
from .ports.specification import SpecificationParserPort

# High-level domain exports
from .core.model import BreakStatement, Loop, SourceRef, SpecError, Step, TestCase, VariableRef
from .core.compiler import compile_cases
from .core.contracts import ContractError, OperationContract, ParameterSpec, build_registry
from .core.mapping import Mapping, load_mapping, load_mappings, parse_mapping_document, resolve
from .core.parameters import Boolean, Decimal, Quantity, Resource, String
from .core.profile import ResourceProfile, check_profile, load_profile, parse_profile

# Adapters
from .adapters.inbound.text_parser import TextSpecificationParser, parse_text_spec, read_text_spec
from .adapters.outbound.dummy_bench import DummyBench, load_config
from .adapters.outbound.python_emitter import PythonCodeEmitter, literal, render_python

# Runtime
from .runtime.runner import execute, run_main
from .runtime.test_log import CheckFailed, StepInfo, TestFailure, TestLog

# Module aliases for seamless backward compatibility
from . import core, ports, adapters, runtime
sys.modules.setdefault('tcg.compiler', core.compiler)
sys.modules.setdefault('tcg.model', core.model)
sys.modules.setdefault('tcg.parameters', core.parameters)
sys.modules.setdefault('tcg.contracts', core.contracts)
sys.modules.setdefault('tcg.mapping', core.mapping)
sys.modules.setdefault('tcg.profile', core.profile)
sys.modules.setdefault('tcg.bench', ports.bench)
sys.modules.setdefault('tcg.text_input', adapters.inbound.text_parser)
sys.modules.setdefault('tcg.render', adapters.outbound.python_emitter)
sys.modules.setdefault('tcg.dummy_bench', adapters.outbound.dummy_bench)
sys.modules.setdefault('tcg.demo_runner', runtime.runner)

__all__ = [
    '__version__',
    'core',
    'ports',
    'adapters',
    'runtime',
    # Domain
    'TestCase',
    'Step',
    'Loop',
    'BreakStatement',
    'VariableRef',
    'SourceRef',
    'SpecError',
    'compile_cases',
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
    # Ports
    'BenchPort',
    'CodeEmitterPort',
    'SpecificationParserPort',
    # Adapters
    'TextSpecificationParser',
    'read_text_spec',
    'parse_text_spec',
    'PythonCodeEmitter',
    'render_python',
    'literal',
    'DummyBench',
    'load_config',
    # Runtime
    'TestLog',
    'CheckFailed',
    'TestFailure',
    'StepInfo',
    'execute',
    'run_main',
]
