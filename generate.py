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
from tcg.core.translation_logger import (
    log_batch_header,
    log_batch_summary,
    log_compiled_case,
    log_spec_file_start,
    setup_translation_logger,
)


def read_specification(path):
    if path.suffix.lower() not in ('.txt', '.md'):
        raise SpecError(f'{path.name}: test specification must be a .txt or .md file')
    return read_text_spec(path)


def generate(spec, mapping, resources, output, registry, runner_module='tcg.runtime.runner', logger=None):
    spec = Path(spec)
    resources = Path(resources)
    output = Path(output)
    mapping_paths = [Path(mapping)] if isinstance(mapping, (str, Path)) else [Path(m) for m in mapping]

    profile = load_profile(resources)
    mappings = load_mapping(mapping_paths, registry)
    tables = read_specification(spec)
    cases = compile_cases(tables, mappings, profile, spec.name)
    check_profile(profile, (step.contract for case in cases for step in case.all_steps()))
    source = render_python(cases, registry, runner_module)
    ast.parse(source)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    temporary.write_text(source, encoding='utf-8', newline='\n')
    temporary.replace(output)

    if logger:
        for case in cases:
            log_compiled_case(logger, case, output, source)

    return cases


def derive_output_filename(spec_file: Path) -> str:
    name = spec_file.stem
    if name.startswith('tc_'):
        parts = name.split('_')
        num = parts[1]
        return f'test_tc{num}.py'
    return f'test_{name}.py'


def generate_batch(spec_dir: Path, mapping, resources, output_dir: Path, registry,
                   runner_module='tcg.runtime.runner', format_filter=None, log_dir='logs', logger=None):
    import time
    start_time = time.perf_counter()
    output_dir = Path(output_dir)
    exts = ('.md', '.txt') if not format_filter else (f'.{format_filter.lstrip(".")}',)
    all_files = [p for p in spec_dir.rglob('*') if p.is_file() and p.suffix.lower() in exts]

    unique_specs = {}
    for f in sorted(all_files):
        rel_parts = f.relative_to(spec_dir).parts
        # Skip format mirror directories when scanning parent to prevent duplicate compilation
        if len(rel_parts) > 1 and rel_parts[0] in ('md', 'txt'):
            continue
        rel_dir = f.relative_to(spec_dir).parent
        key = f.stem
        # Prefer categorized subdirectories over root, and prefer .md over .txt
        if key in unique_specs:
            existing_rel_dir, existing_path = unique_specs[key]
            if existing_rel_dir == Path('.') and rel_dir != Path('.'):
                unique_specs[key] = (rel_dir, f)
            elif existing_rel_dir == rel_dir and f.suffix.lower() == '.md':
                unique_specs[key] = (rel_dir, f)
        else:
            unique_specs[key] = (rel_dir, f)

    created_logger = False
    log_file_path = None
    if logger is None and log_dir:
        logger, log_file_path = setup_translation_logger(log_dir=log_dir)
        created_logger = True

    if logger:
        log_batch_header(logger, spec_dir, len(unique_specs), output_dir)

    compiled_cases = []
    total_steps = 0
    for stem, (rel_dir, spec_path) in sorted(unique_specs.items(), key=lambda x: str(x[1][1])):
        out_filename = derive_output_filename(spec_path)
        out_file = output_dir / rel_dir / out_filename
        if logger:
            log_spec_file_start(logger, spec_path, str(rel_dir))
        cases = generate(spec_path, mapping, resources, out_file, registry, runner_module, logger=logger)
        compiled_cases.extend(cases)
        for c in cases:
            total_steps += len(list(c.all_steps()))
        if rel_dir != Path('.'):
            flat_file = output_dir / out_filename
            flat_file.write_text(out_file.read_text(encoding='utf-8'), encoding='utf-8')
        print(f"Generated {len(cases)} test case(s): {', '.join(c.id for c in cases)} -> {out_file}")

    duration = time.perf_counter() - start_time
    if logger and log_file_path:
        log_batch_summary(logger, len(unique_specs), len(compiled_cases), total_steps, duration, log_file_path)
        print(f"📝 Übersetzungs-Log gespeichert unter:  {log_file_path.resolve()}")
        print(f"📌 Aktueller Shortcut (Latest):        {(Path(log_dir) / 'latest_translation.log').resolve()}")

    return compiled_cases


def load_registry(reference):
    module_name, separator, attribute = reference.partition(':')
    if not separator or not module_name or not attribute:
        raise ValueError('--registry must use module:attribute syntax')
    registry = getattr(importlib.import_module(module_name), attribute)
    if not isinstance(registry, dict) or not registry:
        raise ValueError(f'{reference}: registry must be a non-empty dict')
    return registry


def main():
    parser = argparse.ArgumentParser(description='Deterministic TXT/MD + TOML -> Python test compiler')
    parser.add_argument('--spec', required=True, type=Path, help='Spec file or directory containing spec files')
    parser.add_argument('--mapping', required=True, action='append', type=Path)
    parser.add_argument('--resources', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path, help='Output Python file or directory')
    parser.add_argument('--format', choices=('md', 'txt', 'all'), default='all',
                        help='Filter specification format when scanning directories (default: all)')
    parser.add_argument('--log-dir', default='logs', help='Directory for translation logs (default: logs)')
    parser.add_argument('--registry', default='operations:REGISTRY', help='Trusted Python registry as module:attribute (default: operations:REGISTRY)')
    parser.add_argument('--runner', default='tcg.runtime.runner', help='Runner module used by generated __main__ (default: tcg.runtime.runner)')
    args = parser.parse_args()
    try:
        registry = load_registry(args.registry)
        if args.spec.is_dir():
            fmt = None if args.format == 'all' else args.format
            cases = generate_batch(args.spec, args.mapping, args.resources, args.output, registry, args.runner, fmt, log_dir=args.log_dir)
            print(f'Batch complete: Generated {len(cases)} total test cases into {args.output}')
        else:
            logger, log_file = setup_translation_logger(log_dir=args.log_dir)
            cases = generate(args.spec, args.mapping, args.resources, args.output, registry, args.runner, logger=logger)
            print(f'Generated {len(cases)} test case(s): {", ".join(case.id for case in cases)} -> {args.output}')
            print(f'📝 Übersetzungs-Log: {log_file.resolve()}')
    except (SpecError, OSError, ValueError, ImportError, AttributeError) as error:
        print(f'GENERATION FAILED: {error}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
