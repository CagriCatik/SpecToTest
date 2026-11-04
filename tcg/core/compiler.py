"""Neutral parsed specification -> validated test-case models."""
import re

from .expectations import (
    check_loop_variable,
    collect_step_numbers,
    index_action_tree,
    validate_expectations,
)
from .mapping import resolve, single_line_text
from .parameters import convert_argument
from .model import (
    BreakStatement,
    Loop,
    PHASES,
    SourceRef,
    SpecError,
    Step,
    TestCase,
    VariableRef,
)

SPEC_SECTIONS = ('Testfaelle', 'Vorbedingungen', 'Ablauf', 'Nachbedingungen', 'Erwartungen')
TEST_ID = re.compile(r'TC_[A-Z0-9_]{1,60}')
FLOW_PHASES = frozenset({'ACTION', 'EXPECTED'})


def _metadata(rows):
    cases, problems, identifiers = [], [], {}
    for line, data in rows:
        where = f'Testfaelle!{line}'
        try:
            test_id = single_line_text(data['Test_ID'], f'{where} Test_ID')
            if not TEST_ID.fullmatch(test_id):
                raise SpecError(f'{where}: Test_ID {test_id!r} must match {TEST_ID.pattern}')
            if test_id in identifiers:
                raise SpecError(f'{where}: duplicate Test_ID {test_id!r} (first at line {identifiers[test_id]})')
            identifiers[test_id] = line
            name = single_line_text(data['Name'], f'{where} Name')
            objective = data['Testziel']
            if objective is not None:
                objective = single_line_text(objective, f'{where} Testziel')
            cases.append({'id': test_id, 'name': name, 'objective': objective, 'line': line,
                          'raw_spec': data.get('raw_spec')})
        except SpecError as error:
            problems.extend(error.problems)
    if problems:
        raise SpecError(problems)
    return cases


def _check_references(sections, known_ids):
    problems = []
    for section, rows in sections.items():
        if section == 'Testfaelle':
            continue
        for line, data in rows:
            if data['Test_ID'] not in known_ids:
                problems.append(f'{section}!{line}: unknown Test_ID {data["Test_ID"]!r}')
    if problems:
        raise SpecError(problems)


def _make_id(prefix, used_ids):
    candidate = prefix
    if candidate not in used_ids:
        used_ids.add(candidate)
        return candidate
    idx = 2
    while f'{prefix}_{idx}' in used_ids:
        idx += 1
    candidate = f'{prefix}_{idx}'
    used_ids.add(candidate)
    return candidate


def _unresolved_identifier_hint(parameter, name):
    """Let a parameter type explain an identifier that is neither a value nor a variable."""
    if parameter is None:
        return ''
    describe = getattr(parameter.type, 'describe_unresolved_identifier', None)
    hint = describe(name) if callable(describe) else None
    return f'; {hint}' if hint else ''


def _compile_command(execution_id, requested_phase, test_step, text, line, section,
                     source_file, mappings, profile, scope=(),
                     raw_loop_vars=None, converted_loop_vars=None):
    source = SourceRef(source_file, section, line)
    where = str(source)
    text = single_line_text(text, f'{where} text')
    try:
        mapping, arguments = resolve(text, mappings, profile)
    except SpecError as error:
        raise SpecError([f'{where} ({execution_id}): {problem}' for problem in error.problems]) from None

    # Verify that any VariableRef used in arguments is defined in the current scope
    # and validate all its possible values against the parameter contract!
    raw_loop_vars = raw_loop_vars or {}
    converted_loop_vars = converted_loop_vars if converted_loop_vars is not None else {}
    resolved = dict(arguments)
    for param_name, param_val in arguments:
        if isinstance(param_val, VariableRef):
            var_name = param_val.name
            matching_param = next((p for p in mapping.contract.parameters if p.name == param_name), None)
            if var_name not in scope:
                hint = _unresolved_identifier_hint(matching_param, var_name)
                raise SpecError(f'{where} ({execution_id}): variable {var_name!r} is undefined; '
                                f'in scope: {sorted(scope)}{hint}')
            if var_name in raw_loop_vars:
                if matching_param is not None:
                    converted_items = []
                    # Always validate the original raw items so dimensions/units are preserved!
                    for val in raw_loop_vars[var_name]:
                        val_str = str(val)
                        try:
                            conv = convert_argument(matching_param, val_str, profile, resolved)
                            converted_items.append(conv)
                        except SpecError as err:
                            raise SpecError(
                                f'{where} ({execution_id}): loop variable {var_name!r} value {val!r} '
                                f'is invalid for parameter {param_name!r}: {err}'
                            ) from None
                    # Verify that multiple operations using this variable in the loop are mutually compatible
                    if var_name in converted_loop_vars:
                        if converted_loop_vars[var_name] != converted_items:
                            raise SpecError(
                                f'{where} ({execution_id}): loop variable {var_name!r} has conflicting '
                                f'parameter types or conversions across operations in the loop'
                            )
                    else:
                        converted_loop_vars[var_name] = converted_items

    if requested_phase is None:
        phases = mapping.contract.phases & FLOW_PHASES
        if len(phases) != 1:
            allowed = ', '.join(sorted(mapping.contract.phases))
            raise SpecError(f'{where} ({execution_id}): operation {mapping.contract.id} must allow exactly one '
                            f'of ACTION or EXPECTED for ABLAUF; contract allows: {allowed}')
        phase = next(iter(phases))
    else:
        phase = requested_phase
        if phase not in mapping.contract.phases:
            allowed = ', '.join(item for item in PHASES if item in mapping.contract.phases)
            raise SpecError(f'{where} ({execution_id}): operation {mapping.contract.id} ({mapping.id}) '
                            f'is not allowed in {phase}; allowed: {allowed}')

    return Step(execution_id, phase, test_step, None, None, mapping.contract, arguments,
                mapping.id, source, text)


def _compile_loop(data, line, section, phase, source_file, mappings, profile, used_ids,
                  parent_scope=(), parent_raw_vars=None, parent_conv_vars=None):
    var = data['variable']
    check_loop_variable(var, line, section, source_file, parent_scope)
    scope = set(parent_scope) | {var}
    raw_vars = dict(parent_raw_vars or {})
    raw_vars[var] = list(data['items'])
    conv_vars = parent_conv_vars if parent_conv_vars is not None else {}
    body_conv_vars = dict(conv_vars)
    source = SourceRef(source_file, section, line)
    body_steps = []
    for body_line, body_item in data['body']:
        item_type = body_item.get('type', 'command')
        step_label = body_item.get('Schritt')
        if item_type == 'command':
            prefix = f"{'P' if phase == 'PRECONDITION' else 'C' if phase == 'CLEANUP' else 'S'}{step_label or len(body_steps)+1}"
            exec_id = _make_id(prefix, used_ids)
            step = _compile_command(exec_id, phase, step_label, body_item['Befehl'], body_line,
                                   section, source_file, mappings, profile, scope=scope,
                                   raw_loop_vars=raw_vars, converted_loop_vars=body_conv_vars)
            body_steps.append(step)
        elif item_type == 'break':
            cond = body_item.get('condition')
            if cond is not None:
                if cond.left not in scope:
                    raise SpecError(f'{source_file}:{body_line} [{section}]: variable {cond.left!r} in BREAK condition is undefined; in scope: {sorted(scope)}')
                if isinstance(cond.right, VariableRef) and cond.right.name not in scope:
                    raise SpecError(f'{source_file}:{body_line} [{section}]: variable {cond.right.name!r} on right-hand side of BREAK condition is undefined; in scope: {sorted(scope)}')
            body_steps.append(BreakStatement(condition=cond, step_label=step_label,
                                             source=SourceRef(source_file, section, body_line)))
        elif item_type == 'loop':
            nested = _compile_loop(body_item, body_line, section, phase, source_file, mappings, profile, used_ids,
                                   parent_scope=scope, parent_raw_vars=raw_vars, parent_conv_vars=body_conv_vars)
            body_steps.append(nested)
    if parent_raw_vars:
        conv_vars.update({k: v for k, v in body_conv_vars.items() if k in parent_raw_vars})
    loop_items = tuple(body_conv_vars.get(var, raw_vars.get(var, data['items'])))
    return Loop(variable=var, items=loop_items, body=tuple(body_steps),
                step_label=data.get('Schritt'), source=source, phase=phase)


def _compile_flow_sequence(flow_items, section, phase, source_file, mappings, profile, used_ids,
                           expected_by_step, parent_scope=(), parent_raw_vars=None, parent_conv_vars=None):
    compiled_nodes = []
    raw_vars = dict(parent_raw_vars or {})
    conv_vars = parent_conv_vars if parent_conv_vars is not None else {}
    for line, data in flow_items:
        item_type = data.get('type', 'command')
        step_num = data.get('Schritt')
        if item_type == 'command':
            if step_num in expected_by_step:
                exec_id = _make_id(f'S{step_num}.A' if step_num is not None else f'S{len(compiled_nodes)+1}.A', used_ids)
                action_step = _compile_command(exec_id, 'ACTION', step_num, data['Befehl'], line,
                                               section, source_file, mappings, profile, scope=parent_scope,
                                               raw_loop_vars=raw_vars, converted_loop_vars=conv_vars)
                compiled_nodes.append(action_step)
                for exp_line, exp_data in expected_by_step[step_num]:
                    exp_exec_id = _make_id(f'S{step_num}.E' if step_num is not None else f'S{len(compiled_nodes)+1}.E', used_ids)
                    exp_step = _compile_command(exp_exec_id, 'EXPECTED', step_num, exp_data['Befehl'], exp_line,
                                                'Erwartungen', source_file, mappings, profile, scope=parent_scope,
                                                raw_loop_vars=raw_vars, converted_loop_vars=conv_vars)
                    compiled_nodes.append(exp_step)
                del expected_by_step[step_num]
            else:
                exec_id = _make_id(f'S{step_num}' if step_num is not None else f'S{len(compiled_nodes)+1}', used_ids)
                action_step = _compile_command(exec_id, None, step_num, data['Befehl'], line,
                                               section, source_file, mappings, profile, scope=parent_scope,
                                               raw_loop_vars=raw_vars, converted_loop_vars=conv_vars)
                compiled_nodes.append(action_step)

        elif item_type == 'break':
            cond = data.get('condition')
            if cond is not None:
                if cond.left not in parent_scope:
                    raise SpecError(f'{source_file}:{line} [{section}]: variable {cond.left!r} in BREAK condition is undefined; in scope: {sorted(parent_scope)}')
                if isinstance(cond.right, VariableRef) and cond.right.name not in parent_scope:
                    raise SpecError(f'{source_file}:{line} [{section}]: variable {cond.right.name!r} on right-hand side of BREAK condition is undefined; in scope: {sorted(parent_scope)}')
            compiled_nodes.append(BreakStatement(condition=cond, step_label=step_num,
                                                 source=SourceRef(source_file, section, line)))

        elif item_type == 'loop':
            var = data['variable']
            check_loop_variable(var, line, section, source_file, parent_scope)
            loop_scope = set(parent_scope) | {var}
            body_raw_vars = dict(raw_vars)
            body_raw_vars[var] = list(data['items'])
            body_conv_vars = dict(conv_vars)
            source = SourceRef(source_file, section, line)
            body_nodes = _compile_flow_sequence(data['body'], section, phase, source_file, mappings,
                                                profile, used_ids, expected_by_step, parent_scope=loop_scope,
                                                parent_raw_vars=body_raw_vars, parent_conv_vars=body_conv_vars)
            conv_vars.update({k: v for k, v in body_conv_vars.items() if k in raw_vars})
            loop_items = tuple(body_conv_vars.get(var, body_raw_vars.get(var, data['items'])))
            loop_node = Loop(variable=var, items=loop_items,
                             body=tuple(body_nodes), step_label=step_num, source=source, phase=phase)
            compiled_nodes.append(loop_node)
            if step_num in expected_by_step:
                for exp_line, exp_data in expected_by_step[step_num]:
                    exp_exec_id = _make_id(f'S{step_num}.E' if step_num is not None else f'S{len(compiled_nodes)+1}.E', used_ids)
                    exp_step = _compile_command(exp_exec_id, 'EXPECTED', step_num, exp_data['Befehl'], exp_line,
                                                'Erwartungen', source_file, mappings, profile, scope=parent_scope,
                                                raw_loop_vars=raw_vars, converted_loop_vars=conv_vars)
                    compiled_nodes.append(exp_step)
                del expected_by_step[step_num]

    return compiled_nodes


def _compile_case(metadata, sections, mappings, profile, source_file):
    test_id = metadata['id']
    used_ids = set()
    steps = []

    # 1. Preconditions
    precond_rows = [row for row in sections['Vorbedingungen'] if row[1]['Test_ID'] == test_id]
    precond_steps = collect_step_numbers(precond_rows)
    for line, data in precond_rows:
        if data.get('type') == 'loop':
            steps.append(_compile_loop(data, line, 'Vorbedingungen', 'PRECONDITION', source_file, mappings, profile, used_ids))
        else:
            step_num = data.get('Schritt') if data.get('Schritt') is not None else data.get('Reihenfolge')
            exec_id = _make_id(f'P{step_num}', used_ids)
            steps.append(_compile_command(exec_id, 'PRECONDITION', data.get('Schritt'), data['Befehl'], line,
                                         'Vorbedingungen', source_file, mappings, profile))

    # 2. Flow & Expected
    flow_rows = [row for row in sections['Ablauf'] if row[1]['Test_ID'] == test_id]
    if not flow_rows:
        raise SpecError(f'{test_id}: at least one numbered command in ABLAUF is required')

    action_index = index_action_tree(flow_rows, test_id, source_file)

    cleanup_rows = [row for row in sections['Nachbedingungen'] if row[1]['Test_ID'] == test_id]
    cleanup_steps = collect_step_numbers(cleanup_rows)

    expected_rows = [row for row in sections.get('Erwartungen', []) if row[1]['Test_ID'] == test_id]
    validate_expectations(expected_rows, action_index, precond_steps, cleanup_steps, test_id, source_file)

    expected_by_step = {}
    unassociated_expected = []
    for exp_line, exp_data in expected_rows:
        s_num = exp_data.get('Schritt')
        if s_num is not None:
            expected_by_step.setdefault(s_num, []).append((exp_line, exp_data))
        else:
            unassociated_expected.append((exp_line, exp_data))

    action_and_exp_nodes = _compile_flow_sequence(flow_rows, 'Ablauf', 'ACTION', source_file,
                                                  mappings, profile, used_ids, expected_by_step)
    steps.extend(action_and_exp_nodes)

    if expected_by_step:
        unconsumed = []
        for s_num, exp_list in sorted(expected_by_step.items()):
            for e_line, _ in exp_list:
                unconsumed.append(f'step {s_num} (line {e_line})')
        raise SpecError(
            f'{source_file} [Erwartungen]: {test_id}: {len(unconsumed)} expected result(s) were not bound to any action: {", ".join(unconsumed)}'
        )

    for exp_line, exp_data in unassociated_expected:
        exp_exec_id = _make_id(f'S{len(steps)+1}.E', used_ids)
        exp_step = _compile_command(exp_exec_id, 'EXPECTED', None, exp_data['Befehl'], exp_line,
                                    'Erwartungen', source_file, mappings, profile, scope=())
        steps.append(exp_step)

    # 3. Postconditions (Cleanup)
    for line, data in cleanup_rows:
        if data.get('type') == 'loop':
            steps.append(_compile_loop(data, line, 'Nachbedingungen', 'CLEANUP', source_file, mappings, profile, used_ids))
        else:
            step_num = data.get('Schritt') if data.get('Schritt') is not None else data.get('Reihenfolge')
            exec_id = _make_id(f'C{step_num}', used_ids)
            steps.append(_compile_command(exec_id, 'CLEANUP', data.get('Schritt'), data['Befehl'], line,
                                         'Nachbedingungen', source_file, mappings, profile))

    return TestCase(test_id, metadata['name'], metadata['objective'], profile.profile_id,
                    tuple(steps), raw_spec=metadata.get('raw_spec'))


def compile_cases(sections, mappings, profile, source_file):
    """Validate all sections and return cases in specification order."""
    sections = dict(sections)
    sections.setdefault('Erwartungen', [])
    missing = set(SPEC_SECTIONS) - set(sections)
    extra = set(sections) - set(SPEC_SECTIONS)
    if missing or extra:
        raise SpecError(f'invalid specification sections: missing={sorted(missing)}, extra={sorted(extra)}')
    metadata = _metadata(sections['Testfaelle'])
    _check_references(sections, {item['id'] for item in metadata})
    cases, problems = [], []
    for item in metadata:
        try:
            cases.append(_compile_case(item, sections, mappings, profile, source_file))
        except SpecError as error:
            problems.extend(error.problems)
    if problems:
        raise SpecError(problems)
    return tuple(cases)
