"""Deterministically compile text or Excel test cases into Python source."""
import argparse
import ast
import importlib
from pathlib import Path
import sys

from tcg.compiler import SPEC_SCHEMA, compile_cases
from tcg.excel_input import read_rows, read_tables
from tcg.mapping import MAPPING_COLUMNS, load_mappings
from tcg.model import SpecError
from tcg.profile import check_profile, load_profile
from tcg.render import render_python
from tcg.text_input import read_text_spec


def read_specification(path):
    suffix = path.suffix.lower()
    if suffix == '.txt':
        return read_text_spec(path)
    if suffix == '.xlsx':
        return read_tables(path, SPEC_SCHEMA, optional_empty=('Vorbedingungen', 'Nachbedingungen'))
    raise SpecError(f'{path.name}: unsupported specification format; use .txt or .xlsx')


def generate(spec, mapping, resources, output, registry, runner_module):
    profile = load_profile(resources)
    check_profile(profile, registry)
    mappings = load_mappings(read_rows(mapping, 'Mapping', MAPPING_COLUMNS), registry)
    tables = read_specification(spec)
    cases = compile_cases(tables, mappings, profile, spec.name)
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
    parser = argparse.ArgumentParser(description='Deterministic text/Excel -> Python test compiler')
    parser.add_argument('--spec', required=True, type=Path)
    parser.add_argument('--mapping', required=True, type=Path)
    parser.add_argument('--resources', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--registry', required=True, help='Trusted Python registry as module:attribute')
    parser.add_argument('--runner', required=True, help='Trusted runner module used by generated __main__')
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
