"""Deterministically compile TXT test cases and TOML mappings into Python.

Hexagonal Architecture CLI driver:
- Inbound: reads TXT specs via text_parser adapter
- Core: compiles cases via core.compiler, validates via core.profile & core.mapping
- Outbound: renders Python test suite via python_emitter adapter
"""
import argparse
import ast
import importlib
from pathlib import Path
import sys

from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.mapping import load_mapping
from tcg.core.model import SpecError
from tcg.core.profile import check_profile, load_profile


def read_specification(path):
    if path.suffix.lower() != '.txt':
        raise SpecError(f'{path.name}: test specification must be a .txt file')
    return read_text_spec(path)


def generate(spec, mapping, resources, output, registry, runner_module='tcg.runtime.runner'):
    profile = load_profile(resources)
    mappings = load_mapping(mapping, registry)
    tables = read_specification(spec)
    cases = compile_cases(tables, mappings, profile, spec.name)
    check_profile(profile, (step.contract for case in cases for step in case.all_steps()))
    source = render_python(cases, registry, runner_module)
    ast.parse(source)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(source, encoding='utf-8', newline='\n')
    temporary.replace(output)
    return cases


def load_registry(reference):
    module_name, separator, attribute = reference.partition(':')
    if not separator or not module_name or not attribute:
        raise ValueError('--registry must use module:attribute syntax')
    registry = getattr(importlib.import_module(module_name), attribute)
    if not isinstance(registry, dict) or not registry:
        raise ValueError(f'{reference}: registry must be a non-empty dict')
    return registry


def main():
    parser = argparse.ArgumentParser(description='Deterministic TXT + TOML -> Python test compiler')
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--mapping', required=True, type=Path)
    parser.add_argument('--resources', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--registry', default='operations:REGISTRY', help='Trusted Python registry as module:attribute (default: operations:REGISTRY)')
    parser.add_argument('--runner', default='tcg.runtime.runner', help='Runner module used by generated __main__ (default: tcg.runtime.runner)')
    args = parser.parse_args()
    try:
        registry = load_registry(args.registry)
        cases = generate(args.spec, args.mapping, args.resources, args.output, registry, args.runner)
    except (SpecError, OSError, ValueError, ImportError, AttributeError) as error:
        print(f'GENERATION FAILED: {error}', file=sys.stderr)
        return 2
    print(f'Generated {len(cases)} test case(s): {", ".join(case.id for case in cases)} -> {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
