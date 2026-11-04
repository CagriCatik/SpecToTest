"""Outbound Adapter: Emits executable Python test scripts from compiled test case models."""
from decimal import Decimal
import re
from typing import Sequence

from tcg import __version__
from tcg.core.contracts import OperationContract
from tcg.core.model import (
    BreakStatement,
    ExecutableTestCase,
    IfBlock,
    Loop,
    PHASES,
    Step,
    SwitchBlock,
    VariableRef,
)
from tcg.ports.emitter import CodeEmitterPort


def literal(value):
    if value is None:
        return 'None'
    if type(value) is bool:
        return 'True' if value else 'False'
    if type(value) is int:
        return str(value)
    if type(value) is Decimal and value.is_finite():
        return f"Decimal('{_decimal_text(value)}')"
    if isinstance(value, str):
        # str subclasses (e.g. a resource's adapter address) render as plain strings.
        return repr(str(value))
    if isinstance(value, VariableRef):
        return value.name
    raise ValueError(f'unsupported literal {value!r}')


def _decimal_text(value):
    """Render the exact coefficient without consulting the global Decimal context."""
    text = format(value, 'f')
    if '.' in text:
        text = text.rstrip('0').rstrip('.')
    return '0' if text in {'', '-0'} else text


def function_name(case):
    return f'run_{case.id.lower()}'


def _check_cases(cases, registry):
    identifiers = set()
    for case in cases:
        if case.id in identifiers:
            raise ValueError(f'duplicate case {case.id}')
        identifiers.add(case.id)
        if not re.fullmatch(r'TC_[A-Z0-9_]{1,60}', case.id):
            raise ValueError(f'invalid case id {case.id!r}')
        all_steps = tuple(case.all_steps())
        if not all_steps:
            raise ValueError(f'{case.id}: no steps')
        for step in all_steps:
            contract = registry.get(getattr(step.contract, 'id', None))
            if contract is not step.contract:
                raise ValueError(f'{case.id} {step.execution_id}: operation outside registry')
            if step.phase not in PHASES or step.phase not in contract.phases:
                raise ValueError(f'{case.id} {step.execution_id}: invalid phase')
            if tuple(name for name, _ in step.arguments) != tuple(parameter.name for parameter in contract.parameters):
                raise ValueError(f'{case.id} {step.execution_id}: arguments do not match contract')


def _call(step, alias):
    arguments = ''.join(f', {name}={literal(value)}' for name, value in step.arguments)
    return f'{alias}.{step.contract.function.__name__}(bench{arguments})'


def _render_statement(stmt, aliases, indent='    '):
    lines = []
    if isinstance(stmt, Step):
        step_lbl = f'{stmt.test_step}. ' if stmt.test_step is not None else ''
        lines.append(f'{indent}# {step_lbl}{stmt.description}')
        lines.append(f'{indent}{_call(stmt, aliases[stmt.contract.function.__module__])}')
    elif isinstance(stmt, Loop):
        items_rendered = '[' + ', '.join(literal(x) for x in stmt.items) + ']'
        step_lbl = f'{stmt.step_label}: ' if stmt.step_label is not None else ''
        lines.append(f'{indent}# {step_lbl}FOR ({stmt.variable};{items_rendered})')
        lines.append(f'{indent}for {stmt.variable} in {items_rendered}:')
        body_indent = indent + '    '
        for body_item in stmt.body:
            lines.extend(_render_statement(body_item, aliases, indent=body_indent))
    elif isinstance(stmt, BreakStatement):
        b_lbl = f'{stmt.step_label}: ' if stmt.step_label is not None else ''
        if stmt.condition is not None:
            lines.append(f'{indent}# {b_lbl}BREAK ({stmt.condition.render()})')
            lines.append(f'{indent}if {stmt.condition.render()}:')
            lines.append(f'{indent}    break')
        else:
            lines.append(f'{indent}# {b_lbl}BREAK')
            lines.append(f'{indent}break')
    elif isinstance(stmt, IfBlock):
        for idx, branch in enumerate(stmt.branches):
            b_lbl = f'{branch.step_label}: ' if branch.step_label is not None else ''
            kw = 'if' if idx == 0 else 'elif'
            lines.append(f'{indent}# {b_lbl}{kw.upper()} ({branch.condition.render()})')
            lines.append(f'{indent}{kw} {branch.condition.render()}:')
            b_indent = indent + '    '
            if not branch.body:
                lines.append(f'{b_indent}pass')
            else:
                for item in branch.body:
                    lines.extend(_render_statement(item, aliases, indent=b_indent))
        if stmt.else_body:
            lines.append(f'{indent}# ELSE')
            lines.append(f'{indent}else:')
            b_indent = indent + '    '
            for item in stmt.else_body:
                lines.extend(_render_statement(item, aliases, indent=b_indent))
    elif isinstance(stmt, SwitchBlock):
        step_lbl = f'{stmt.step_label}: ' if stmt.step_label is not None else ''
        lines.append(f'{indent}# {step_lbl}SWITCH ({stmt.expression})')
        lines.append(f'{indent}match {stmt.expression}:')
        case_indent = indent + '    '
        body_indent = indent + '        '
        for case in stmt.cases:
            c_lbl = f'{case.step_label}: ' if case.step_label is not None else ''
            val_rendered = repr(case.value) if isinstance(case.value, str) else str(case.value)
            lines.append(f'{case_indent}# {c_lbl}CASE ({val_rendered})')
            lines.append(f'{case_indent}case {val_rendered}:')
            if not case.body:
                lines.append(f'{body_indent}pass')
            else:
                for item in case.body:
                    lines.extend(_render_statement(item, aliases, indent=body_indent))
        if stmt.default_body:
            lines.append(f'{case_indent}# DEFAULT')
            lines.append(f'{case_indent}case _:')
            for item in stmt.default_body:
                lines.extend(_render_statement(item, aliases, indent=body_indent))
    return lines


def _render_cleanup_statement(stmt, aliases, indent='        '):
    lines = []
    if isinstance(stmt, Step):
        step_lbl = f'{stmt.test_step}. ' if stmt.test_step is not None else ''
        lines.append(f'{indent}# {step_lbl}{stmt.description}')
        lines.append(f'{indent}try:')
        lines.append(f'{indent}    {_call(stmt, aliases[stmt.contract.function.__module__])}')
        lines.append(f'{indent}except Exception as _cln_err:')
        lines.append(f'{indent}    cleanup_errors.append(_cln_err)')
    elif isinstance(stmt, Loop):
        items_rendered = '[' + ', '.join(literal(x) for x in stmt.items) + ']'
        step_lbl = f'{stmt.step_label}: ' if stmt.step_label is not None else ''
        lines.append(f'{indent}# {step_lbl}FOR ({stmt.variable};{items_rendered})')
        lines.append(f'{indent}try:')
        lines.append(f'{indent}    for {stmt.variable} in {items_rendered}:')
        body_indent = indent + '        '
        for body_item in stmt.body:
            lines.extend(_render_cleanup_statement(body_item, aliases, indent=body_indent))
        lines.append(f'{indent}except Exception as _cln_err:')
        lines.append(f'{indent}    cleanup_errors.append(_cln_err)')
    elif isinstance(stmt, BreakStatement):
        b_lbl = f'{stmt.step_label}: ' if stmt.step_label is not None else ''
        if stmt.condition is not None:
            lines.append(f'{indent}# {b_lbl}BREAK ({stmt.condition.render()})')
            lines.append(f'{indent}if {stmt.condition.render()}:')
            lines.append(f'{indent}    break')
        else:
            lines.append(f'{indent}# {b_lbl}BREAK')
            lines.append(f'{indent}break')
    elif isinstance(stmt, IfBlock):
        lines.append(f'{indent}try:')
        sub_indent = indent + '    '
        for idx, branch in enumerate(stmt.branches):
            b_lbl = f'{branch.step_label}: ' if branch.step_label is not None else ''
            kw = 'if' if idx == 0 else 'elif'
            lines.append(f'{sub_indent}# {b_lbl}{kw.upper()} ({branch.condition.render()})')
            lines.append(f'{sub_indent}{kw} {branch.condition.render()}:')
            b_indent = sub_indent + '    '
            if not branch.body:
                lines.append(f'{b_indent}pass')
            else:
                for item in branch.body:
                    lines.extend(_render_cleanup_statement(item, aliases, indent=b_indent))
        if stmt.else_body:
            lines.append(f'{sub_indent}# ELSE')
            lines.append(f'{sub_indent}else:')
            b_indent = sub_indent + '    '
            for item in stmt.else_body:
                lines.extend(_render_cleanup_statement(item, aliases, indent=b_indent))
        lines.append(f'{indent}except Exception as _cln_err:')
        lines.append(f'{indent}    cleanup_errors.append(_cln_err)')
    elif isinstance(stmt, SwitchBlock):
        lines.append(f'{indent}try:')
        sub_indent = indent + '    '
        step_lbl = f'{stmt.step_label}: ' if stmt.step_label is not None else ''
        lines.append(f'{sub_indent}# {step_lbl}SWITCH ({stmt.expression})')
        lines.append(f'{sub_indent}match {stmt.expression}:')
        case_indent = sub_indent + '    '
        body_indent = sub_indent + '        '
        for case in stmt.cases:
            c_lbl = f'{case.step_label}: ' if case.step_label is not None else ''
            val_rendered = repr(case.value) if isinstance(case.value, str) else str(case.value)
            lines.append(f'{case_indent}# {c_lbl}CASE ({val_rendered})')
            lines.append(f'{case_indent}case {val_rendered}:')
            if not case.body:
                lines.append(f'{body_indent}pass')
            else:
                for item in case.body:
                    lines.extend(_render_cleanup_statement(item, aliases, indent=body_indent))
        if stmt.default_body:
            lines.append(f'{case_indent}# DEFAULT')
            lines.append(f'{case_indent}case _:')
            for item in stmt.default_body:
                lines.extend(_render_cleanup_statement(item, aliases, indent=body_indent))
        lines.append(f'{indent}except Exception as _cln_err:')
        lines.append(f'{indent}    cleanup_errors.append(_cln_err)')
    return lines


def _format_spec_docstring(case):
    if case.raw_spec and case.raw_spec.strip():
        return case.raw_spec.strip()
    lines = []
    preconds = [s for s in case.steps if getattr(s, 'phase', None) == 'PRECONDITION']
    if preconds:
        lines.append('Precondition')
        for s in preconds:
            if isinstance(s, Step):
                num = f'{s.test_step}. ' if s.test_step is not None else ''
                lines.append(f'{num}{s.description}')
            elif isinstance(s, Loop):
                num = f'{s.step_label}: ' if s.step_label is not None else ''
                items = ', '.join(literal(x) for x in s.items)
                lines.append(f'{num}FOR ({s.variable};[{items}])')
        lines.append('')
    actions = [s for s in case.steps if getattr(s, 'phase', None) in ('ACTION', 'EXPECTED')]
    if actions:
        lines.append('Action')
        for s in actions:
            if isinstance(s, Step):
                num = f'{s.test_step}. ' if s.test_step is not None else ''
                lines.append(f'{num}{s.description}')
            elif isinstance(s, Loop):
                num = f'{s.step_label}: ' if s.step_label is not None else ''
                items = ', '.join(literal(x) for x in s.items)
                lines.append(f'{num}FOR ({s.variable};[{items}])')
        lines.append('')
    cleanups = [s for s in case.steps if getattr(s, 'phase', None) == 'CLEANUP']
    if cleanups:
        lines.append('Postcondition')
        for s in cleanups:
            if isinstance(s, Step):
                num = f'{s.test_step}. ' if s.test_step is not None else ''
                lines.append(f'{num}{s.description}')
            elif isinstance(s, Loop):
                num = f'{s.step_label}: ' if s.step_label is not None else ''
                items = ', '.join(literal(x) for x in s.items)
                lines.append(f'{num}FOR ({s.variable};[{items}])')
                for b in s.body:
                    if isinstance(b, Step):
                        b_num = f'{b.test_step}. ' if b.test_step is not None else ''
                        lines.append(f'  {b_num}{b.description}')
                    elif isinstance(b, BreakStatement):
                        b_num = f'{b.step_label}: ' if b.step_label is not None else ''
                        cond = f' ({b.condition.render()})' if b.condition else ''
                        lines.append(f'  {b_num}BREAK{cond}')
                lines.append('END FOR')
    return '\n'.join(lines).strip()


def _collect_case_variable_names(cases):
    vars_found = {'bench'}
    def _visit(items):
        for item in items:
            if isinstance(item, Loop):
                vars_found.add(item.variable)
                _visit(item.body)
            elif isinstance(item, IfBlock):
                for branch in item.branches:
                    _visit(branch.body)
                _visit(item.else_body)
            elif isinstance(item, SwitchBlock):
                vars_found.add(item.expression)
                for c in item.cases:
                    _visit(c.body)
                _visit(item.default_body)
    for case in cases:
        _visit(case.steps)
    return vars_found


def _module_alias(module_name, used_names):
    short = module_name.split('.')[-1]
    candidate = f'_op_{short}'
    if candidate not in used_names and candidate.isidentifier():
        used_names.add(candidate)
        return candidate
    idx = 2
    while f'{candidate}_{idx}' in used_names:
        idx += 1
    alias = f'{candidate}_{idx}'
    used_names.add(alias)
    return alias


def render_python(cases, registry, runner_module='tcg.runtime.runner'):
    cases = tuple(cases)
    _check_cases(cases, registry)
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', runner_module):
        raise ValueError(f'invalid runner module {runner_module!r}')
    modules = sorted({step.contract.function.__module__ for case in cases for step in case.all_steps()})
    used_names = _collect_case_variable_names(cases)
    aliases = {module: _module_alias(module, used_names) for module in modules}
    lines = [
        f'# Generated by tcg {__version__}. Do not edit; change the specification and regenerate.',
        'from decimal import Decimal',
        'from tcg.runtime import TestResult',
    ]
    lines += [f'import {module} as {aliases[module]}' for module in modules]
    lines.append('')
    for case in cases:
        spec_text = _format_spec_docstring(case)
        lines.append(f'def {function_name(case)}(bench):')
        if spec_text:
            lines.append('    """Original Test Specification:')
            lines.append('    ' + '=' * 72)
            for spec_line in spec_text.splitlines():
                lines.append(f'    {spec_line}')
            lines.append('    ' + '=' * 72)
            lines.append('    """')

        preconds = [s for s in case.steps if getattr(s, 'phase', None) == 'PRECONDITION']
        actions = [s for s in case.steps if getattr(s, 'phase', None) in ('ACTION', 'EXPECTED')]
        cleanups = [s for s in case.steps if getattr(s, 'phase', None) == 'CLEANUP']

        if cleanups:
            lines.append('    cleanup_errors = []')
            lines.append('    try:')
            if preconds:
                lines.append('        # --- Precondition ---')
                for s in preconds:
                    lines.extend(_render_statement(s, aliases, indent='        '))
                if actions:
                    lines.append('')
            if actions:
                lines.append('        # --- Action & Expected Result ---')
                for s in actions:
                    lines.extend(_render_statement(s, aliases, indent='        '))
            elif not preconds:
                lines.append('        pass')
            lines.append('    finally:')
            lines.append('        # --- Postcondition (Cleanup) ---')
            for s in cleanups:
                lines.extend(_render_cleanup_statement(s, aliases, indent='        '))
            lines.append('        if cleanup_errors:')
            lines.append('            if len(cleanup_errors) == 1:')
            lines.append('                raise cleanup_errors[0]')
            lines.append('            raise ExceptionGroup("Multiple errors during cleanup", cleanup_errors)')
        else:
            if preconds:
                lines.append('    # --- Precondition ---')
                for s in preconds:
                    lines.extend(_render_statement(s, aliases, indent='    '))
                if actions:
                    lines.append('')
            if actions:
                lines.append('    # --- Action & Expected Result ---')
                for s in actions:
                    lines.extend(_render_statement(s, aliases, indent='    '))
            elif not preconds:
                lines.append('    pass')

        lines.append(f'    return TestResult({literal(case.id)}, "PASS")')
        lines.append('')

    lines += ['RUNNERS = {']
    lines += [f'    {literal(case.id)}: {function_name(case)},' for case in cases]
    lines += ['}', '']

    # Test bench capabilities each case needs. A loaded communication description
    # says nothing about what the bench can do, so the requirement travels with the
    # generated test and is checked at the adapter boundary before the test runs.
    capabilities = {case.id: sorted({
        name for step in case.all_steps()
        for name in (getattr(step.contract, 'capabilities', ()) or ())
    }) for case in cases}
    if any(capabilities.values()):
        lines += ['REQUIRED_CAPABILITIES = {']
        lines += [f'    {literal(case.id)}: {tuple(capabilities[case.id])!r},'
                  for case in cases if capabilities[case.id]]
        lines += ['}', '']

    lines += [
        "if __name__ == '__main__':",
        f'    from {runner_module} import run_main',
        '    raise SystemExit(run_main(RUNNERS))',
        '',
    ]
    return '\n'.join(lines)


class PythonCodeEmitter(CodeEmitterPort):
    """Driven Adapter implementing CodeEmitterPort for Python test script output."""

    def emit(
        self,
        cases: Sequence[ExecutableTestCase],
        registry: dict[str, OperationContract],
        runner_module: str = 'tcg.runtime.runner',
    ) -> str:
        return render_python(cases, registry, runner_module)
