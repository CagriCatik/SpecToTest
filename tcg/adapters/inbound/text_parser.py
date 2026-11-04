"""Tolerant whitespace handling for the deterministic TXT test specification language."""
from decimal import Decimal
from pathlib import Path
import re

from tcg.core.model import BinaryCondition, SpecError, VariableRef
from tcg.ports.specification import SpecificationParserPort

SPEC_SECTIONS = ('Testfaelle', 'Vorbedingungen', 'Ablauf', 'Nachbedingungen', 'Erwartungen')

SECTION_MAP = {
    'precondition': 'Vorbedingungen',
    'preconditions': 'Vorbedingungen',
    'vorbedingungen': 'Vorbedingungen',
    'action': 'Ablauf',
    'actions': 'Ablauf',
    'ablauf': 'Ablauf',
    'testschritte': 'Ablauf',
    'postcondition': 'Nachbedingungen',
    'postconditions': 'Nachbedingungen',
    'nachbedingungen': 'Nachbedingungen',
    'expected result': 'Erwartungen',
    'expected results': 'Erwartungen',
    'expected': 'Erwartungen',
    'erwartetes ergebnis': 'Erwartungen',
    'erwartete ergebnisse': 'Erwartungen',
    'erwartungen': 'Erwartungen',
}

SECTION_HEADING = re.compile(
    r'^(preconditions?|vorbedingungen|actions?|ablauf|testschritte|postconditions?|nachbedingungen|'
    r'expected(?:\s+results?)?|erwartete(?:\s+ergebnisse?)?|erwartungen):?$',
    re.IGNORECASE,
)

FOR_LOOP = re.compile(r'^(?:([0-9]+)[.:]\s*)?FOR\s*\(\s*([A-Za-z_]\w*)\s*;\s*\[([^\]]*)\]\s*\)$', re.IGNORECASE)
END_FOR = re.compile(r'^(?:([0-9]+)[.:]\s*)?END\s+FOR$', re.IGNORECASE)
BREAK_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?BREAK(?:\s*\(\s*(.+?)\s*\))?$', re.IGNORECASE)
GENERAL_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?(.+)$')


def _error(source, line, message):
    name = Path(source).name if isinstance(source, (str, Path)) else str(source)
    raise SpecError(f'{name}:{line}: {message}')


def _strip_inline_comment(line):
    in_quote = False
    quote_char = None
    for idx, char in enumerate(line):
        if char in ('"', "'"):
            if not in_quote:
                in_quote = True
                quote_char = char
            elif quote_char == char:
                in_quote = False
        elif char == '#' and not in_quote:
            return line[:idx].rstrip()
    return line


def _parse_items(raw_items, path, line_number):
    items = []
    for part in raw_items.split(','):
        item_str = part.strip()
        if not item_str:
            continue
        if re.fullmatch(r'-?(?:0|[1-9][0-9]*)', item_str):
            items.append(int(item_str))
        elif re.fullmatch(r'-?(?:0|[1-9][0-9]*)\.[0-9]+', item_str):
            items.append(Decimal(item_str))
        elif (item_str.startswith('"') and item_str.endswith('"')) or (item_str.startswith("'") and item_str.endswith("'")):
            items.append(item_str[1:-1])
        else:
            items.append(item_str)
    if not items:
        _error(path, line_number, 'FOR loop items must not be empty')
    return tuple(items)


def _parse_condition(raw_cond, path, line_number):
    text = raw_cond.strip()
    match = re.fullmatch(r'([A-Za-z_]\w*)\s*(==|!=|<=|>=|<|>)\s*(.+)', text)
    if not match:
        _error(path, line_number, f'invalid BREAK condition {text!r}')
    left = match[1]
    op = match[2]
    right_str = match[3].strip()
    if re.fullmatch(r'-?(?:0|[1-9][0-9]*)', right_str):
        right = int(right_str)
    elif re.fullmatch(r'-?(?:0|[1-9][0-9]*)\.[0-9]+', right_str):
        right = Decimal(right_str)
    elif right_str in ('True', 'False'):
        right = (right_str == 'True')
    elif (right_str.startswith('"') and right_str.endswith('"')) or (right_str.startswith("'") and right_str.endswith("'")):
        right = right_str[1:-1]
    elif re.fullmatch(r'[A-Za-z_]\w*', right_str):
        right = VariableRef(right_str)
    else:
        _error(path, line_number, f'invalid literal or variable in condition: {right_str!r}')
    return BinaryCondition(left, op, right)


def _field(line, prefix, path, line_number):
    if not line.startswith(prefix):
        _error(path, line_number, f'expected {prefix!r}')
    value = line[len(prefix):].strip()
    if not value:
        _error(path, line_number, f'{prefix[:-1]} must not be empty')
    return value


def parse_text_lines(raw_lines, source_name='test_spec.txt'):
    """Parse raw lines of specification text into structured sections."""
    source_path = Path(source_name)
    source_stem = source_path.stem
    source_file = source_path.name

    sections = {name: [] for name in SPEC_SECTIONS}
    case = None
    state = 'START'
    current_section = None
    loop_stack = []
    sequence = {'Vorbedingungen': 0, 'Nachbedingungen': 0}
    in_block_comment = False
    in_html_comment = False

    def add_metadata():
        if case and not case['stored']:
            sections['Testfaelle'].append((case['line'], {
                'Test_ID': case['id'],
                'Name': case['name'],
                'Testziel': case['objective'],
            }))
            case['stored'] = True

    def close_case(line_number):
        nonlocal case, current_section, loop_stack
        if case is None:
            return
        if loop_stack:
            _error(source_file, line_number, f'{case["id"]}: unclosed FOR loop')
        add_metadata()
        case = None
        current_section = None

    def ensure_case(line_number):
        nonlocal case, state
        if case is None:
            raw_stem = source_stem.upper()
            stem_id = re.sub(r'[^A-Z0-9_]', '_', raw_stem)
            case_id = stem_id if stem_id.startswith('TC_') else f'TC_{stem_id}'
            case = {'id': case_id, 'line': line_number, 'name': source_stem,
                    'objective': None, 'stored': False}
            add_metadata()
            state = 'SECTION_BODY'

    for line_number, raw in enumerate(raw_lines, 1):
        line = raw.strip()

        # Handle multi-line block comments /* ... */
        if in_block_comment:
            if '*/' in line:
                in_block_comment = False
                line = line.partition('*/')[2].strip()
            else:
                continue

        if line.startswith('/*'):
            if '*/' in line:
                line = line.partition('*/')[2].strip()
            else:
                in_block_comment = True
                continue

        # Handle multi-line HTML comments <!-- ... --> (Markdown)
        if in_html_comment:
            if '-->' in line:
                in_html_comment = False
                line = line.partition('-->')[2].strip()
            else:
                continue

        if line.startswith('<!--'):
            if '-->' in line:
                line = line.partition('-->')[2].strip()
            else:
                in_html_comment = True
                continue

        # Skip markdown code fence markers and thematic breaks
        if line.startswith('```') or line in ('---', '***', '___'):
            continue

        # Handle Markdown headings (# Precondition, ## Action, # TESTFALL: ...)
        is_md_heading = False
        if line.startswith('#'):
            candidate = line.lstrip('#').strip()
            match_cand = re.match(r'^\*{0,2}(TESTFALL|NAME|TESTZIEL)\*{0,2}:\*{0,2}\s*(.+)$', candidate, re.IGNORECASE)
            if match_cand:
                field = match_cand.group(1).upper()
                val = match_cand.group(2).strip().strip('*').strip()
                line = f'{field}: {val}'
                is_md_heading = True
            elif SECTION_HEADING.match(candidate):
                line = candidate
                is_md_heading = True

        if not is_md_heading:
            line = _strip_inline_comment(line)
            if not line or line.startswith('//'):
                continue

        # Handle Markdown list bullets: - or *
        if line.startswith(('- ', '* ')):
            line = line[2:].strip()

        # Normalize markdown bold on header metadata: **TESTFALL:** -> TESTFALL:
        match_hdr = re.match(r'^\*{0,2}(TESTFALL|NAME|TESTZIEL)\*{0,2}:\*{0,2}\s*(.+)$', line, re.IGNORECASE)
        if match_hdr:
            field = match_hdr.group(1).upper()
            val = match_hdr.group(2).strip().strip('*').strip()
            line = f'{field}: {val}'

        if line.startswith('TESTFALL:'):
            if case is not None:
                close_case(line_number)
            test_id = _field(line, 'TESTFALL:', source_file, line_number)
            case = {'id': test_id, 'line': line_number, 'name': None,
                    'objective': None, 'stored': False}
            sequence = {'Vorbedingungen': 0, 'Nachbedingungen': 0}
            loop_stack = []
            current_section = None
            state = 'NAME'
            continue

        if state == 'NAME':
            case['name'] = _field(line, 'NAME:', source_file, line_number)
            state = 'OPTIONAL_OBJECTIVE'
            continue

        if state == 'OPTIONAL_OBJECTIVE':
            if line.startswith('TESTZIEL:'):
                case['objective'] = _field(line, 'TESTZIEL:', source_file, line_number)
                state = 'EXPECTING_SECTION'
                continue
            state = 'EXPECTING_SECTION'

        match_section = SECTION_HEADING.match(line)
        if match_section:
            if loop_stack:
                _error(source_file, line_number, f'unclosed FOR loop before section {line!r}')
            ensure_case(line_number)
            sec_name = match_section.group(1).lower().rstrip(':')
            current_section = SECTION_MAP[sec_name]
            state = 'SECTION_BODY'
            continue

        if state in ('EXPECTING_SECTION', 'START'):
            ensure_case(line_number)

        if current_section is None:
            _error(source_file, line_number, f"unexpected content {line!r}; expected section heading (e.g. 'Precondition', 'Action', 'Postcondition')")

        # Parse FOR loop
        match_for = FOR_LOOP.match(line)
        if match_for:
            step_num = int(match_for[1]) if match_for[1] else None
            var_name = match_for[2]
            items = _parse_items(match_for[3], source_file, line_number)
            loop_data = {
                'Test_ID': case['id'],
                'Schritt': step_num,
                'type': 'loop',
                'variable': var_name,
                'items': items,
                'body': [],
            }
            target = loop_stack[-1] if loop_stack else sections[current_section]
            target.append((line_number, loop_data))
            loop_stack.append(loop_data['body'])
            continue

        # Parse END FOR
        match_end = END_FOR.match(line)
        if match_end:
            if not loop_stack:
                _error(source_file, line_number, 'unexpected END FOR without active FOR loop')
            loop_stack.pop()
            continue

        # Parse BREAK
        match_break = BREAK_CMD.match(line)
        if match_break:
            if not loop_stack:
                _error(source_file, line_number, 'BREAK statement occurs outside of any FOR loop')
            step_num = int(match_break[1]) if match_break[1] else None
            cond = _parse_condition(match_break[2], source_file, line_number) if match_break[2] else None
            break_data = {
                'Test_ID': case['id'],
                'Schritt': step_num,
                'type': 'break',
                'condition': cond,
            }
            loop_stack[-1].append((line_number, break_data))
            continue

        # Regular command
        match_cmd = GENERAL_CMD.match(line)
        if match_cmd:
            step_num = int(match_cmd[1]) if match_cmd[1] else None
            cmd_text = match_cmd[2].strip()
            cmd_data = {
                'Test_ID': case['id'],
                'Schritt': step_num,
                'Befehl': cmd_text,
                'type': 'command',
            }
            if current_section in sequence:
                sequence[current_section] += 1
                cmd_data['Reihenfolge'] = sequence[current_section]

            target = loop_stack[-1] if loop_stack else sections[current_section]
            target.append((line_number, cmd_data))
            continue

        _error(source_file, line_number, f'unrecognized specification statement: {line!r}')

    if case is None and not sections['Testfaelle']:
        raise SpecError(f'{source_file}: no test cases')
    close_case(len(raw_lines) or 1)
    return sections


def read_text_spec(path):
    """Parse one or more test cases supporting sections, loops and conditions from a file."""
    path = Path(path)
    try:
        raw_lines = path.read_text(encoding='utf-8-sig').splitlines()
    except UnicodeDecodeError as error:
        raise SpecError(f'{path.name}: must be UTF-8 text ({error})') from None
    except OSError as error:
        raise SpecError(f'{path.name}: cannot read specification ({error.strerror})') from None
    return parse_text_lines(raw_lines, source_name=path.name)


def parse_text_spec(text, name='test_spec.txt'):
    """Parse one or more test cases supporting sections, loops and conditions from a string."""
    return parse_text_lines(text.splitlines(), source_name=name)


class TextSpecificationParser(SpecificationParserPort):
    """Driving Adapter satisfying SpecificationParserPort for .txt specification files."""

    def parse_specification(self, path):
        from pathlib import Path
        return read_text_spec(Path(path))

