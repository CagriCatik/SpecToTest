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
    sheet: str  # semantic section (or legacy Excel sheet)
    row: int  # text line (or legacy Excel row)

    def __str__(self):
        if self.workbook.lower().endswith('.txt'):
            return f'{self.workbook}:{self.row} [{self.sheet}]'
        return f'{self.workbook}:{self.sheet}!{self.row}'


@dataclass(frozen=True)
class Step:
    execution_id: str
    phase: str
    test_step: int | None
    step_name: str | None
    expectation_order: int | None
    contract: object  # tcg.contracts.OperationContract
    arguments: tuple  # ((parameter name, converted value), ...) in contract order
    mapping_id: str
    source: SourceRef
    description: str


@dataclass(frozen=True)
class TestCase:
    id: str
    name: str
    objective: str
    profile_id: str
    steps: tuple  # tuple[Step, ...] in specification order
