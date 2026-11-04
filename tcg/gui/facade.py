"""Unified Application Facade bridging core compiler and PySide6 GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

from tcg.adapters.inbound.text_parser import parse_text_lines
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.mapping import load_mappings
from tcg.core.model import Loop, SpecError, Step, TestCase
from tcg.core.profile import ResourceProfile


@dataclass
class CompilationError:
    """A structured compilation or parsing error with line information."""
    line: int | None
    message: str
    section: str | None = None
    raw_text: str = ''


@dataclass
class StepInspectionInfo:
    """Detailed inspection info for a single specification step."""
    line: int
    step_number: int | None
    phase: str
    mapping_id: str
    template: str
    operation_name: str
    operation_doc: str
    arguments: dict[str, Any]
    rendered_call: str
    is_expectation: bool
    attached_to_step: int | None


@dataclass
class CompilationResult:
    """Result of compiling a specification."""
    success: bool
    source_name: str
    cases: list[TestCase] = field(default_factory=list)
    python_code: str = ''
    errors: list[CompilationError] = field(default_factory=list)
    steps_by_line: dict[int, StepInspectionInfo] = field(default_factory=dict)
    summary: str = ''


@dataclass
class MappingImpact:
    """Usage impact analysis of a sentence mapping across the project."""
    mapping_id: str
    total_usages: int = 0
    affected_cases: set[str] = field(default_factory=set)
    affected_files: set[str] = field(default_factory=set)
    occurrences: list[tuple[str, int]] = field(default_factory=list)  # (file_name, line_number)


class CompilationFacade:
    """Shared application service for specs inspection, compilation, and impact analysis."""

    @staticmethod
    def list_spec_files(specs_dir: Path | str) -> list[Path]:
        """Find all valid .md and .txt specification files in specs_dir."""
        p = Path(specs_dir)
        if not p.is_dir():
            return []
        
        all_files = [f for f in p.rglob('*') if f.is_file() and f.suffix.lower() in ('.md', '.txt')]
        unique_specs: dict[tuple[Path, str], Path] = {}

        for f in sorted(all_files):
            rel_parts = f.relative_to(p).parts
            if len(rel_parts) > 1 and rel_parts[0] in ('md', 'txt'):
                continue
            rel_dir = f.relative_to(p).parent
            key = (rel_dir, f.stem)
            if key in unique_specs:
                existing = unique_specs[key]
                if f.suffix.lower() == '.md' and existing.suffix.lower() == '.txt':
                    unique_specs[key] = f
            else:
                unique_specs[key] = f

        return sorted(unique_specs.values())

    @classmethod
    def compile_text(
        cls,
        text: str,
        source_name: str,
        registry: dict[str, Any],
        mapping_dicts: list[dict[str, Any]],
        profile: ResourceProfile,
    ) -> CompilationResult:
        """Compile a specification string in memory using the core compiler."""
        raw_lines = text.splitlines()

        # 1. Parse into section tables
        try:
            sections = parse_text_lines(raw_lines, source_name=source_name)
        except SpecError as e:
            return cls._build_parse_error_result(source_name, e.problems, raw_lines)
        except Exception as e:
            return CompilationResult(
                success=False,
                source_name=source_name,
                errors=[CompilationError(line=1, message=str(e))],
                summary=f"Parser-Fehler: {e}",
            )

        # 2. Compile mappings
        try:
            compiled_mappings = load_mappings(mapping_dicts, registry, source='GUI_Facade')
        except SpecError as e:
            return CompilationResult(
                success=False,
                source_name=source_name,
                errors=[CompilationError(line=None, message=p) for p in e.problems],
                summary="Mapping-Fehler verhindern die Übersetzung.",
            )

        # 3. Compile cases
        try:
            cases = compile_cases(sections, compiled_mappings, profile, source_file=source_name)
        except SpecError as e:
            return cls._build_compile_error_result(source_name, e.problems, raw_lines)
        except Exception as e:
            return CompilationResult(
                success=False,
                source_name=source_name,
                errors=[CompilationError(line=None, message=str(e))],
                summary=f"Compiler-Fehler: {e}",
            )

        # 4. Render Python source
        try:
            python_source = render_python(cases, registry, runner_module='tcg.runtime.runner')
        except Exception as e:
            python_source = f"# Fehler beim Erzeugen des Python-Codes: {e}"

        # 5. Extract line-by-line inspection info
        steps_by_line: dict[int, StepInspectionInfo] = {}
        mapping_templates = {m['id']: m.get('template', '') for m in mapping_dicts}

        for case in cases:
            for step in case.all_steps():
                line = step.source.row
                doc = (step.contract.function.__doc__ or '').strip() if step.contract and hasattr(step.contract, 'function') else ''
                args_dict = dict(step.arguments)
                args_str = ", ".join(f"{k}={v!r}" for k, v in args_dict.items())
                call_code = f"{step.contract.id}(bench, {args_str})" if args_str else f"{step.contract.id}(bench)"

                info = StepInspectionInfo(
                    line=line,
                    step_number=step.test_step,
                    phase=step.phase,
                    mapping_id=step.mapping_id,
                    template=mapping_templates.get(step.mapping_id, ''),
                    operation_name=step.contract.id,
                    operation_doc=doc,
                    arguments=args_dict,
                    rendered_call=call_code,
                    is_expectation=(step.phase == 'EXPECTED'),
                    attached_to_step=step.test_step if step.phase == 'EXPECTED' else None,
                )
                steps_by_line[line] = info

        return CompilationResult(
            success=True,
            source_name=source_name,
            cases=list(cases),
            python_code=python_source,
            errors=[],
            steps_by_line=steps_by_line,
            summary=f"Erfolgreich übersetzt: {len(cases)} Testfall/Testfälle, {len(steps_by_line)} Schritte.",
        )

    @classmethod
    def analyze_impact(
        cls,
        specs_files: list[Path],
        registry: dict[str, Any],
        mapping_dicts: list[dict[str, Any]],
        profile: ResourceProfile,
    ) -> dict[str, MappingImpact]:
        """Analyze how many times each mapping is used across all project specification files."""
        impacts: dict[str, MappingImpact] = {
            m['id']: MappingImpact(mapping_id=m['id']) for m in mapping_dicts
        }

        try:
            compiled_mappings = load_mappings(mapping_dicts, registry, source='GUI_Impact')
        except Exception:
            return impacts

        for path in specs_files:
            try:
                text = path.read_text(encoding='utf-8-sig')
                sections = parse_text_lines(text.splitlines(), source_name=path.name)
                cases = compile_cases(sections, compiled_mappings, profile, source_file=path.name)
                for case in cases:
                    for step in case.all_steps():
                        m_id = step.mapping_id
                        if m_id not in impacts:
                            impacts[m_id] = MappingImpact(mapping_id=m_id)
                        imp = impacts[m_id]
                        imp.total_usages += 1
                        imp.affected_cases.add(case.id)
                        imp.affected_files.add(path.name)
                        imp.occurrences.append((path.name, step.source.row))
            except Exception:
                # If a specific spec file fails, continue analyzing the rest
                continue

        return impacts

    @staticmethod
    def _build_parse_error_result(source_name: str, problems: tuple[str, ...], lines: list[str]) -> CompilationResult:
        errors = []
        for prob in problems:
            line_match = re.search(r':(\d+):\s*(.*)', prob)
            if line_match:
                ln = int(line_match.group(1))
                msg = line_match.group(2)
                raw = lines[ln - 1] if 0 < ln <= len(lines) else ''
                errors.append(CompilationError(line=ln, message=msg, raw_text=raw))
            else:
                errors.append(CompilationError(line=None, message=prob))
        return CompilationResult(
            success=False,
            source_name=source_name,
            errors=errors,
            summary=f"Parser-Fehler in {source_name}: {len(errors)} Problem(e) gefunden.",
        )

    @staticmethod
    def _build_compile_error_result(source_name: str, problems: tuple[str, ...], lines: list[str]) -> CompilationResult:
        errors = []
        for prob in problems:
            # Pattern: source_file:line [Section] (ID): message
            match = re.search(r':(\d+)\s+\[([^\]]+)\](?:\s*\([^)]+\))?:\s*(.*)', prob)
            if match:
                ln = int(match.group(1))
                sec = match.group(2)
                msg = match.group(3)
                raw = lines[ln - 1] if 0 < ln <= len(lines) else ''
                errors.append(CompilationError(line=ln, message=msg, section=sec, raw_text=raw))
            else:
                errors.append(CompilationError(line=None, message=prob))
        return CompilationResult(
            success=False,
            source_name=source_name,
            errors=errors,
            summary=f"Compiler-Fehler in {source_name}: {len(errors)} Problem(e) gefunden.",
        )
