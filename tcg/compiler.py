"""Neutral specification tables -> validated test-case models."""
import re

from .mapping import resolve, single_line_text
from .model import PHASES, SourceRef, SpecError, Step, TestCase

SPEC_SCHEMA = {
    'Testfaelle': ('Test_ID', 'Name', 'Testziel'),
    'Vorbedingungen': ('Test_ID', 'Reihenfolge', 'Aktion'),
    'Testschritte': ('Test_ID', 'Schritt', 'Name', 'Aktion'),
    'Erwartungen': ('Test_ID', 'Schritt', 'Reihenfolge', 'Erwartung'),
    'Nachbedingungen': ('Test_ID', 'Reihenfolge', 'Aktion'),
}
TEST_ID = re.compile(r'TC_[A-Z0-9_]{1,60}')


def _positive_integer(value, where, field):
    if type(value) is not int or value <= 0:
        raise SpecError(f'{where}: {field} must be a positive integer, got {value!r}')
    return value


def _metadata(rows):
    cases, problems = [], []
    for row, data in rows:
        where = f'Testfaelle!{row}'
        try:
            test_id = single_line_text(data['Test_ID'], f'{where} Test_ID')
            if not TEST_ID.fullmatch(test_id):
                raise SpecError(f'{where}: Test_ID {test_id!r} must match {TEST_ID.pattern}')
            if any(item['id'] == test_id for item in cases):
                raise SpecError(f'{where}: duplicate Test_ID {test_id!r}')
            name = single_line_text(data['Name'], f'{where} Name')
            objective = single_line_text(data['Testziel'], f'{where} Testziel')
            cases.append({'id': test_id, 'name': name, 'objective': objective, 'row': row})
        except SpecError as error:
            problems.extend(error.problems)
    if problems:
        raise SpecError(problems)
    return cases


def _check_references(tables, known_ids):
    problems = []
    for sheet, rows in tables.items():
        if sheet == 'Testfaelle':
            continue
        for row, data in rows:
            if data['Test_ID'] not in known_ids:
                problems.append(f'{sheet}!{row}: unknown Test_ID {data["Test_ID"]!r}')
    if problems:
        raise SpecError(problems)


def _ordered(rows, sheet, test_id, order_field='Reihenfolge'):
    selected, seen, problems = [], {}, []
    for row, data in rows:
        if data['Test_ID'] != test_id:
            continue
        where = f'{sheet}!{row}'
        try:
            order = _positive_integer(data[order_field], where, order_field)
            if order in seen:
                raise SpecError(f'{where}: duplicate {order_field} {order} (also row {seen[order]})')
            seen[order] = row
            selected.append((order, row, data))
        except SpecError as error:
            problems.extend(error.problems)
    if problems:
        raise SpecError(problems)
    return sorted(selected)


def _compile_expression(execution_id, phase, test_step, step_name, expectation_order, text, row,
                        sheet, workbook, mappings, profile):
    source = SourceRef(workbook, sheet, row)
    where = str(source)
    text = single_line_text(text, f'{where} text')
    try:
        mapping, arguments = resolve(text, mappings, profile)
    except SpecError as error:
        raise SpecError([f'{where} ({execution_id}): {problem}' for problem in error.problems]) from None
    if phase not in mapping.contract.phases:
        allowed = ', '.join(item for item in PHASES if item in mapping.contract.phases)
        raise SpecError(f'{where} ({execution_id}): operation {mapping.contract.id} ({mapping.id}) '
                        f'is not allowed in {phase}; allowed: {allowed}')
    return Step(execution_id, phase, test_step, step_name, expectation_order, mapping.contract, arguments,
                mapping.id, source, text)


def _compile_case(metadata, tables, mappings, profile, workbook):
    test_id = metadata['id']
    preconditions = _ordered(tables['Vorbedingungen'], 'Vorbedingungen', test_id)
    actions = _ordered(tables['Testschritte'], 'Testschritte', test_id, 'Schritt')
    cleanups = _ordered(tables['Nachbedingungen'], 'Nachbedingungen', test_id)
    problems = []
    if not preconditions:
        problems.append(f'{test_id}: at least one explicit precondition is required')
    if not actions:
        problems.append(f'{test_id}: at least one test step is required')
    if not cleanups:
        problems.append(f'{test_id}: at least one explicit cleanup is required')

    expectations = {}
    for row, data in tables['Erwartungen']:
        if data['Test_ID'] != test_id:
            continue
        where = f'Erwartungen!{row}'
        try:
            step_number = _positive_integer(data['Schritt'], where, 'Schritt')
            order = _positive_integer(data['Reihenfolge'], where, 'Reihenfolge')
            expectations.setdefault(step_number, []).append((order, row, data))
        except SpecError as error:
            problems.extend(error.problems)
    action_numbers = {number for number, _, _ in actions}
    for step_number, entries in expectations.items():
        if step_number not in action_numbers:
            problems.append(f'{test_id}: expectations reference unknown test step {step_number}')
        seen = {}
        for order, row, _ in entries:
            if order in seen:
                problems.append(f'Erwartungen!{row}: duplicate Reihenfolge {order} for step {step_number} '
                                f'(also row {seen[order]})')
            seen[order] = row
    for step_number in action_numbers:
        if step_number not in expectations:
            problems.append(f'{test_id} step {step_number}: at least one explicit expectation is required')
    if problems:
        raise SpecError(problems)

    steps = []
    for order, row, data in preconditions:
        steps.append(_compile_expression(f'P{order}', 'PRECONDITION', None, None, None, data['Aktion'], row,
                                         'Vorbedingungen', workbook, mappings, profile))
    for step_number, row, data in actions:
        step_name = single_line_text(data['Name'], f'Testschritte!{row} Name')
        steps.append(_compile_expression(f'S{step_number}.A', 'ACTION', step_number, step_name, None, data['Aktion'], row,
                                         'Testschritte', workbook, mappings, profile))
        for order, expectation_row, expectation in sorted(expectations[step_number]):
            steps.append(_compile_expression(f'S{step_number}.E{order}', 'EXPECTED', step_number, step_name, order,
                                             expectation['Erwartung'], expectation_row, 'Erwartungen', workbook,
                                             mappings, profile))
    for order, row, data in cleanups:
        steps.append(_compile_expression(f'C{order}', 'CLEANUP', None, None, None, data['Aktion'], row,
                                         'Nachbedingungen', workbook, mappings, profile))
    return TestCase(test_id, metadata['name'], metadata['objective'], profile.profile_id, tuple(steps))


def compile_cases(tables, mappings, profile, workbook):
    """Validate every table and return cases in the order of the Testfaelle sheet."""
    missing = set(SPEC_SCHEMA) - set(tables)
    if missing:
        raise SpecError(f'missing specification tables: {", ".join(sorted(missing))}')
    metadata = _metadata(tables['Testfaelle'])
    _check_references(tables, {item['id'] for item in metadata})
    cases, problems = [], []
    for item in metadata:
        try:
            cases.append(_compile_case(item, tables, mappings, profile, workbook))
        except SpecError as error:
            problems.extend(error.problems)
    if problems:
        raise SpecError(problems)
    return tuple(cases)
