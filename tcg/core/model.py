"""Framework-independent domain model: test cases, steps, source references.

No input-file format, no hardware, no operation execution.
"""
from dataclasses import dataclass

PHASES = ('PRECONDITION', 'ACTION', 'EXPECTED', 'CLEANUP')


class SpecError(ValueError):
    """Invalid specification, mapping or profile. Blocks generation.

    `problems` lists every individual finding; str() joins them line by line.
    """

    def __init__(self, problems):
        self.problems = (problems,) if isinstance(problems, str) else tuple(problems)
        super().__init__('\n'.join(self.problems))


@dataclass(frozen=True)
class SourceRef:
    workbook: str  # source file name only, never an absolute path
    sheet: str  # semantic section
    row: int  # text line

    def __str__(self):
        return f'{self.workbook}:{self.row} [{self.sheet}]'


@dataclass(frozen=True)
class VariableRef:
    name: str

    def __str__(self):
        return self.name


@dataclass(frozen=True)
class BinaryCondition:
    left: str
    op: str
    right: object

    def render(self):
        val = repr(self.right) if isinstance(self.right, str) else str(self.right)
        return f'{self.left} {self.op} {val}'


@dataclass(frozen=True)
class BreakStatement:
    condition: BinaryCondition | None
    step_label: int | None
    source: SourceRef

    def render(self):
        if self.condition is not None:
            return f'if {self.condition.render()}:\n    break'
        return 'break'


@dataclass(frozen=True)
class Step:
    execution_id: str
    phase: str
    test_step: int | None
    step_name: str | None
    expectation_order: int | None
    contract: object  # tcg.core.contracts.OperationContract
    arguments: tuple  # ((parameter name, converted value), ...) in contract order
    mapping_id: str
    source: SourceRef
    description: str


@dataclass(frozen=True)
class Loop:
    variable: str
    items: tuple
    body: tuple  # tuple of Step | BreakStatement | Loop | IfBlock | SwitchBlock
    step_label: int | None
    source: SourceRef
    phase: str  # PRECONDITION, ACTION, CLEANUP


@dataclass(frozen=True)
class IfBranch:
    condition: BinaryCondition
    body: tuple
    step_label: int | None
    source: SourceRef


@dataclass(frozen=True)
class IfBlock:
    branches: tuple[IfBranch, ...]
    else_body: tuple
    step_label: int | None
    source: SourceRef
    phase: str  # PRECONDITION, ACTION, CLEANUP


@dataclass(frozen=True)
class SwitchCase:
    value: object
    body: tuple
    step_label: int | None
    source: SourceRef


@dataclass(frozen=True)
class SwitchBlock:
    expression: str
    cases: tuple[SwitchCase, ...]
    default_body: tuple
    step_label: int | None
    source: SourceRef
    phase: str  # PRECONDITION, ACTION, CLEANUP


@dataclass(frozen=True)
class TestCase:
    id: str
    name: str
    objective: str | None
    profile_id: str
    steps: tuple  # tuple of Step | Loop | IfBlock | SwitchBlock
    raw_spec: str | None = None

    def all_steps(self):
        """Yield all Step instances recursively (including inside loops, ifs and switches)."""
        def _collect(items):
            for item in items:
                if isinstance(item, Step):
                    yield item
                elif isinstance(item, Loop):
                    yield from _collect(item.body)
                elif isinstance(item, IfBlock):
                    for branch in item.branches:
                        yield from _collect(branch.body)
                    yield from _collect(item.else_body)
                elif isinstance(item, SwitchBlock):
                    for case in item.cases:
                        yield from _collect(case.body)
                    yield from _collect(item.default_body)
        yield from _collect(self.steps)


ExecutableTestCase = TestCase
