"""Strict, human-readable text adapter for test specifications.

The adapter only translates a small text grammar into the neutral tables consumed
by :mod:`tcg.compiler`. It knows nothing about operations or their parameters.
"""
import re

from .compiler import SPEC_SCHEMA
from .model import SpecError


NUMBERED = re.compile(r'([1-9][0-9]*)\. (.+)')
ACTION = re.compile(r' {2,}AKTION: (.+)')
EXPECTATION = re.compile(r' {2,}ERWARTUNG ([1-9][0-9]*): (.+)')
CONTROL = re.compile(r'(?:[0-9]+[.:] *)?(?:FOR|BREAK|END FOR)\b', re.IGNORECASE)


def _error(path, line, message):
    raise SpecError(f'{path.name}:{line}: {message}')


def _value(raw, prefix, path, line):
    if not raw.startswith(prefix):
        _error(path, line, f'expected {prefix!r}')
    value = raw[len(prefix):]
    if not value:
        _error(path, line, f'{prefix[:-2]} must not be empty')
    return value


def read_text_spec(path):
    """Read one or more strict test-case blocks from a UTF-8 text file.

    Returned tables use the same schema as the legacy Excel adapter, keeping the
    compiler, mapping resolution and renderer independent of the input format.
    """
    try:
        lines = path.read_text(encoding='utf-8-sig').splitlines()
    except UnicodeDecodeError as error:
        raise SpecError(f'{path.name}: must be UTF-8 text ({error})') from None

    tables = {name: [] for name in SPEC_SCHEMA}
    case = None
    state = 'TESTFALL'
    step = None

    def close_step(line):
        nonlocal step
        if step is None:
            return
        if step['action'] is None:
            _error(path, step['line'], f'test step {step["number"]} needs exactly one indented AKTION')
        tables['Testschritte'].append((step['action_line'], {
            'Test_ID': case['id'],
            'Schritt': step['number'],
            'Name': step['name'],
            'Aktion': step['action'],
        }))
        for order, expectation_line, text in step['expectations']:
            tables['Erwartungen'].append((expectation_line, {
                'Test_ID': case['id'],
                'Schritt': step['number'],
                'Reihenfolge': order,
                'Erwartung': text,
            }))
        step = None

    def close_case(line):
        nonlocal case
        if case is None:
            return
        close_step(line)
        if state != 'CLEANUP':
            _error(path, line, f'{case["id"]}: missing NACHBEDINGUNGEN section')
        case = None

    for line_number, raw in enumerate(lines, 1):
        if '\t' in raw:
            _error(path, line_number, 'tabs are forbidden; indent AKTION and ERWARTUNG with spaces')
        if raw != raw.rstrip():
            _error(path, line_number, 'trailing whitespace is not allowed')
        if not raw or raw.lstrip().startswith('#'):
            continue
        if CONTROL.match(raw.lstrip()):
            _error(path, line_number,
                   'FOR/BREAK control structures are not supported by this specification language')

        if raw.startswith('TESTFALL: '):
            if case is not None:
                close_case(line_number)
            test_id = _value(raw, 'TESTFALL: ', path, line_number)
            case = {'id': test_id, 'line': line_number, 'name': None, 'objective': None}
            state = 'NAME'
            continue

        if case is None:
            _error(path, line_number, "expected 'TESTFALL: TC_...'")

        if state == 'NAME':
            case['name'] = _value(raw, 'NAME: ', path, line_number)
            state = 'OBJECTIVE'
            continue
        if state == 'OBJECTIVE':
            case['objective'] = _value(raw, 'TESTZIEL: ', path, line_number)
            tables['Testfaelle'].append((case['line'], {
                'Test_ID': case['id'], 'Name': case['name'], 'Testziel': case['objective'],
            }))
            state = 'PRE_HEADING'
            continue
        if state == 'PRE_HEADING':
            if raw != 'VORBEDINGUNGEN:':
                _error(path, line_number, "expected 'VORBEDINGUNGEN:'")
            state = 'PRECONDITIONS'
            continue
        if state == 'PRECONDITIONS':
            if raw == 'TESTSCHRITTE:':
                state = 'STEPS'
                continue
            match = NUMBERED.fullmatch(raw)
            if not match:
                _error(path, line_number,
                       "expected '<Nummer>. <Aktion>' or 'TESTSCHRITTE:' in VORBEDINGUNGEN")
            tables['Vorbedingungen'].append((line_number, {
                'Test_ID': case['id'], 'Reihenfolge': int(match[1]), 'Aktion': match[2],
            }))
            continue
        if state == 'STEPS':
            if raw == 'NACHBEDINGUNGEN:':
                close_step(line_number)
                state = 'CLEANUP'
                continue
            action = ACTION.fullmatch(raw)
            if action:
                if step is None:
                    _error(path, line_number, 'AKTION must belong to a numbered test step')
                if step['action'] is not None:
                    _error(path, line_number, f'test step {step["number"]} has more than one AKTION')
                if step['expectations']:
                    _error(path, line_number, 'AKTION must appear before ERWARTUNG')
                step['action'] = action[1]
                step['action_line'] = line_number
                continue
            expectation = EXPECTATION.fullmatch(raw)
            if expectation:
                if step is None:
                    _error(path, line_number, 'ERWARTUNG must belong to a numbered test step')
                if step['action'] is None:
                    _error(path, line_number, 'ERWARTUNG must appear after AKTION')
                step['expectations'].append((int(expectation[1]), line_number, expectation[2]))
                continue
            numbered = NUMBERED.fullmatch(raw)
            if numbered:
                close_step(line_number)
                step = {'number': int(numbered[1]), 'name': numbered[2], 'line': line_number,
                        'action': None, 'action_line': None, 'expectations': []}
                continue
            _error(path, line_number,
                   "expected a numbered step, indented AKTION/ERWARTUNG, or 'NACHBEDINGUNGEN:'")
        if state == 'CLEANUP':
            match = NUMBERED.fullmatch(raw)
            if not match:
                _error(path, line_number, "expected '<Nummer>. <Aktion>' in NACHBEDINGUNGEN")
            tables['Nachbedingungen'].append((line_number, {
                'Test_ID': case['id'], 'Reihenfolge': int(match[1]), 'Aktion': match[2],
            }))
            continue

        _error(path, line_number, f'unexpected content in parser state {state}')

    if case is None and not tables['Testfaelle']:
        raise SpecError(f'{path.name}: no test cases')
    close_case(len(lines) or 1)
    return tables
