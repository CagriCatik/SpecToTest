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

IF_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?IF\s*\(\s*(.+?)\s*\)$', re.IGNORECASE)
ELSE_IF_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?ELSE\s+IF\s*\(\s*(.+?)\s*\)$', re.IGNORECASE)
ELSE_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?ELSE$', re.IGNORECASE)
END_IF = re.compile(r'^(?:([0-9]+)[.:]\s*)?END\s+IF$', re.IGNORECASE)

SWITCH_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?SWITCH\s*\(\s*([A-Za-z_]\w*)\s*\)$', re.IGNORECASE)
CASE_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?CASE\s*\(\s*(.+?)\s*\)$', re.IGNORECASE)
DEFAULT_CMD = re.compile(r'^(?:([0-9]+)[.:]\s*)?DEFAULT$', re.IGNORECASE)
END_SWITCH = re.compile(r'^(?:([0-9]+)[.:]\s*)?END\s+SWITCH$', re.IGNORECASE)

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


def _process_line_comments(line: str, in_block: bool, in_html: bool) -> tuple[str, bool, bool, str | None]:
    """Processes comments on a single line respecting string literals.

    Returns:
        tuple[str, bool, bool, str | None]:
            - stripped code line
            - updated in_block status
            - updated in_html status
            - unclosed comment token if opened on this line ('/*' or '<!--'), else None
    """
    if in_block:
        if '*/' in line:
            in_block = False
            line = line.partition('*/')[2]
        else:
            return '', True, False, None

    if in_html:
        if '-->' in line:
            in_html = False
            line = line.partition('-->')[2]
        else:
            return '', False, True, None

    res = []
    in_quote = False
    quote_char = None
    i = 0
    n = len(line)
    opened = None

    while i < n:
        c = line[i]
        if c in ('"', "'"):
            if not in_quote:
                in_quote = True
                quote_char = c
            elif quote_char == c:
                in_quote = False
                quote_char = None
            res.append(c)
            i += 1
            continue

        if not in_quote:
            if line[i:i+2] == '/*':
                end_idx = line.find('*/', i + 2)
                if end_idx != -1:
                    i = end_idx + 2
                    continue
                else:
                    in_block = True
                    opened = '/*'
                    break

            if line[i:i+4] == '<!--':
                end_idx = line.find('-->', i + 4)
                if end_idx != -1:
                    i = end_idx + 4
                    continue
                else:
                    in_html = True
                    opened = '<!--'
                    break

            if line[i:i+2] == '//':
                break

            if c == '#':
                # Check if this line is a markdown heading (# Precondition, # TESTFALL:, etc.)
                stripped_rest = line[i:].lstrip('#').strip()
                match_hdr = re.match(r'^\*{0,2}(TESTFALL|NAME|TESTZIEL)\*{0,2}:', stripped_rest, re.IGNORECASE)
                is_heading = bool(match_hdr) or bool(SECTION_HEADING.match(stripped_rest))
                if (i == 0 or not ''.join(res).strip('#').strip()) and is_heading:
                    res.append(c)
                    i += 1
                    continue
                else:
                    break

        res.append(c)
        i += 1

    return ''.join(res).strip(), in_block, in_html, opened


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


def _parse_case_value(raw_val):
    text = raw_val.strip()
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        return text[1:-1]
    if text in ('True', 'False'):
        return text == 'True'
    if re.fullmatch(r'-?(?:0|[1-9][0-9]*)', text):
        return int(text)
    if re.fullmatch(r'-?(?:0|[1-9][0-9]*)\.[0-9]+', text):
        return Decimal(text)
    return text


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
    block_stack = []
    sequence = {'Vorbedingungen': 0, 'Nachbedingungen': 0}
    in_block_comment = False
    in_html_comment = False
    block_comment_start_line = None
    html_comment_start_line = None

    def current_target(line_no):
        if not block_stack:
            return sections[current_section]
        entry = block_stack[-1]
        if entry['active_body'] is None:
            _error(source_file, line_no, f"statements inside {entry['type'].upper()} must be placed inside a branch (e.g. CASE/DEFAULT)")
        return entry['active_body']

    def add_metadata():
        if case and not case['stored']:
            sections['Testfaelle'].append((case['line'], {
                'Test_ID': case['id'],
                'Name': case['name'],
                'Testziel': case['objective'],
            }))
            case['stored'] = True

    def close_case(line_number):
        nonlocal case, current_section, block_stack
        if case is None:
            return
        if block_stack:
            top = block_stack[-1]['type']
            name = "FOR loop" if top == "loop" else f"{top.upper()} block"
            _error(source_file, line_number, f'{case["id"]}: unclosed {name}')
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

        # Handle block and line comments
        line, in_block_comment, in_html_comment, opened_comment = _process_line_comments(
            line, in_block_comment, in_html_comment
        )
        if opened_comment == '/*':
            block_comment_start_line = line_number
        elif opened_comment == '<!--':
            html_comment_start_line = line_number

        if not line:
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
            block_stack = []
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
            if block_stack:
                top = block_stack[-1]['type']
                name = "FOR loop" if top == "loop" else f"{top.upper()} block"
                _error(source_file, line_number, f'unclosed {name} before section {line!r}')
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
            loop_body = []
            loop_data = {
                'Test_ID': case['id'],
                'Schritt': step_num,
                'type': 'loop',
                'variable': var_name,
                'items': items,
                'body': loop_body,
            }
            current_target(line_number).append((line_number, loop_data))
            block_stack.append({'type': 'loop', 'data': loop_data, 'active_body': loop_body})
            continue

        # Parse END FOR
        match_end = END_FOR.match(line)
        if match_end:
            if not block_stack:
                _error(source_file, line_number, 'unexpected END FOR without active FOR loop')
            if block_stack[-1]['type'] != 'loop':
                _error(source_file, line_number, f"unclosed {block_stack[-1]['type'].upper()} block before END FOR")
            block_stack.pop()
            continue

        # Parse IF
        match_if = IF_CMD.match(line)
        if match_if:
            step_num = int(match_if[1]) if match_if[1] else None
            cond = _parse_condition(match_if[2], source_file, line_number)
            branch_body = []
            if_data = {
                'Test_ID': case['id'],
                'Schritt': step_num,
                'type': 'if',
                'branches': [(step_num, cond, branch_body)],
                'else_body': [],
                'has_else': False,
            }
            current_target(line_number).append((line_number, if_data))
            block_stack.append({'type': 'if', 'data': if_data, 'active_body': branch_body})
            continue

        # Parse ELSE IF
        match_elif = ELSE_IF_CMD.match(line)
        if match_elif:
            if not block_stack or block_stack[-1]['type'] != 'if':
                _error(source_file, line_number, 'ELSE IF without active IF block')
            if block_stack[-1]['data']['has_else']:
                _error(source_file, line_number, 'ELSE IF after ELSE is not allowed')
            step_num = int(match_elif[1]) if match_elif[1] else None
            cond = _parse_condition(match_elif[2], source_file, line_number)
            branch_body = []
            block_stack[-1]['data']['branches'].append((step_num, cond, branch_body))
            block_stack[-1]['active_body'] = branch_body
            continue

        # Parse ELSE
        match_else = ELSE_CMD.match(line)
        if match_else:
            if not block_stack or block_stack[-1]['type'] != 'if':
                _error(source_file, line_number, 'ELSE without active IF block')
            if block_stack[-1]['data']['has_else']:
                _error(source_file, line_number, 'multiple ELSE branches in same IF block')
            block_stack[-1]['data']['has_else'] = True
            block_stack[-1]['active_body'] = block_stack[-1]['data']['else_body']
            continue

        # Parse END IF
        match_end_if = END_IF.match(line)
        if match_end_if:
            if not block_stack:
                _error(source_file, line_number, 'unexpected END IF without active IF block')
            if block_stack[-1]['type'] != 'if':
                _error(source_file, line_number, f"unclosed {block_stack[-1]['type'].upper()} block before END IF")
            block_stack.pop()
            continue

        # Parse SWITCH
        match_sw = SWITCH_CMD.match(line)
        if match_sw:
            step_num = int(match_sw[1]) if match_sw[1] else None
            expr = match_sw[2].strip()
            switch_data = {
                'Test_ID': case['id'],
                'Schritt': step_num,
                'type': 'switch',
                'expression': expr,
                'cases': [],
                'default_body': [],
                'has_default': False,
            }
            current_target(line_number).append((line_number, switch_data))
            block_stack.append({'type': 'switch', 'data': switch_data, 'active_body': None})
            continue

        # Parse CASE
        match_case = CASE_CMD.match(line)
        if match_case:
            if not block_stack or block_stack[-1]['type'] != 'switch':
                _error(source_file, line_number, 'CASE statement outside of SWITCH block')
            if block_stack[-1]['data']['has_default']:
                _error(source_file, line_number, 'CASE after DEFAULT is not allowed')
            step_num = int(match_case[1]) if match_case[1] else None
            case_val = _parse_case_value(match_case[2])
            case_body = []
            block_stack[-1]['data']['cases'].append((step_num, case_val, case_body))
            block_stack[-1]['active_body'] = case_body
            continue

        # Parse DEFAULT
        match_def = DEFAULT_CMD.match(line)
        if match_def:
            if not block_stack or block_stack[-1]['type'] != 'switch':
                _error(source_file, line_number, 'DEFAULT statement outside of SWITCH block')
            if block_stack[-1]['data']['has_default']:
                _error(source_file, line_number, 'multiple DEFAULT branches in same SWITCH block')
            block_stack[-1]['data']['has_default'] = True
            block_stack[-1]['active_body'] = block_stack[-1]['data']['default_body']
            continue

        # Parse END SWITCH
        match_end_sw = END_SWITCH.match(line)
        if match_end_sw:
            if not block_stack:
                _error(source_file, line_number, 'unexpected END SWITCH without active SWITCH block')
            if block_stack[-1]['type'] != 'switch':
                _error(source_file, line_number, f"unclosed {block_stack[-1]['type'].upper()} block before END SWITCH")
            block_stack.pop()
            continue

        # Parse BREAK
        match_break = BREAK_CMD.match(line)
        if match_break:
            has_loop = any(b['type'] == 'loop' for b in block_stack)
            if not has_loop:
                _error(source_file, line_number, 'BREAK statement occurs outside of any FOR loop')
            step_num = int(match_break[1]) if match_break[1] else None
            cond = _parse_condition(match_break[2], source_file, line_number) if match_break[2] else None
            break_data = {
                'Test_ID': case['id'],
                'Schritt': step_num,
                'type': 'break',
                'condition': cond,
            }
            current_target(line_number).append((line_number, break_data))
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

            current_target(line_number).append((line_number, cmd_data))
            continue

        _error(source_file, line_number, f'unrecognized specification statement: {line!r}')

    if in_block_comment:
        _error(source_file, block_comment_start_line or (len(raw_lines) or 1), "unclosed block comment '/*'")
    if in_html_comment:
        _error(source_file, html_comment_start_line or (len(raw_lines) or 1), "unclosed HTML comment '<!--'")

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

