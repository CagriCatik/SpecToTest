"""Recursive expectation indexing, validation and binding for test specifications."""
import keyword
from tcg.core.model import SpecError

RESERVED_VARIABLE_NAMES = frozenset({
    'bench', 'Decimal', 'runner', 'runners', 'TestResult', 'TestLog', 'CheckFailed',
    'self', 'args', 'kwargs', 'timing', 'diagnostic', 'ignition', 'supply', 'hmi', 'can', 'hil',
} | set(keyword.kwlist))


def collect_step_numbers(rows):
    """Recursively collect all explicit step numbers defined in a section's rows."""
    steps = set()
    for _, data in rows:
        item_type = data.get('type', 'command')
        s_num = data.get('Schritt')
        if s_num is not None:
            steps.add(s_num)
        if item_type == 'loop':
            steps.update(collect_step_numbers(data.get('body', [])))
    return steps


def index_action_tree(flow_rows, test_id, source_file):
    """Recursively index all step numbers in the action tree.

    Verifies that no duplicate step numbers exist in the action tree.
    Returns:
        dict: step_num -> dict with info ('line', 'type', 'data', 'path')
    """
    indexed = {}

    def _traverse(rows, path):
        for line, data in rows:
            item_type = data.get('type', 'command')
            s_num = data.get('Schritt')
            if s_num is not None:
                if s_num in indexed:
                    prev_line = indexed[s_num]['line']
                    raise SpecError(
                        f'{source_file}:{line} [Ablauf]: {test_id}: duplicate step number {s_num} '
                        f'in Action tree (first defined at line {prev_line})'
                    )
                indexed[s_num] = {'line': line, 'type': item_type, 'data': data, 'path': path}
            if item_type == 'loop':
                _traverse(data.get('body', []), path + (f"loop_{s_num or 'anon'}",))

    _traverse(flow_rows, ())
    return indexed


def validate_expectations(expected_rows, action_index, precond_steps, cleanup_steps, test_id, source_file):
    """Validate that every numbered expectation references a valid step in Action tree.

    Rejects:
    - Expected results referencing step numbers in Precondition.
    - Expected results referencing step numbers in Postcondition (Cleanup).
    - Expected results referencing unknown step numbers.
    """
    problems = []
    for line, data in expected_rows:
        s_num = data.get('Schritt')
        if s_num is not None:
            if s_num in precond_steps:
                problems.append(
                    f'{source_file}:{line} [Erwartungen]: {test_id}: expectation for step {s_num} '
                    f'references a Precondition step; expected results may only target Action steps'
                )
            elif s_num in cleanup_steps:
                problems.append(
                    f'{source_file}:{line} [Erwartungen]: {test_id}: expectation for step {s_num} '
                    f'references a Postcondition step; expected results may only target Action steps'
                )
            elif s_num not in action_index:
                problems.append(
                    f'{source_file}:{line} [Erwartungen]: {test_id}: expectation for step {s_num} '
                    f'has no matching target in Action tree (orphaned expected result)'
                )
            elif action_index[s_num]['type'] == 'break':
                problems.append(
                    f'{source_file}:{line} [Erwartungen]: {test_id}: expectation for step {s_num} '
                    f'references a BREAK statement; expected results may only target Action steps or loops'
                )
    if problems:
        raise SpecError(problems)


def check_loop_variable(var_name, line, section, source_file, parent_scope=()):
    """Validate that loop variable is valid, not reserved, and not shadowing an outer loop variable."""
    if var_name.startswith('_'):
        raise SpecError(
            f"{source_file}:{line} [{section}]: loop variable {var_name!r} is invalid; "
            f"specification variable names cannot start with an underscore ('_')"
        )
    if var_name in parent_scope:
        raise SpecError(
            f'{source_file}:{line} [{section}]: loop variable {var_name!r} shadows an outer loop variable; '
            f'shadowing is not permitted'
        )
    if var_name in RESERVED_VARIABLE_NAMES:
        raise SpecError(
            f'{source_file}:{line} [{section}]: loop variable {var_name!r} is a reserved identifier'
        )

