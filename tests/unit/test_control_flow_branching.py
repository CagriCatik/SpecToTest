"""Unit tests for IF/ELSE and SWITCH/CASE control structures in specifications."""
import ast
import tempfile
from pathlib import Path
import unittest

from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.model import SpecError
from tests.common import BaseTestCase, REGISTRY, RUNNER


class ControlFlowBranchingTests(BaseTestCase):

    def _compile_and_run(self, spec_text: str):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "test_spec.md"
            path.write_text(spec_text, encoding="utf-8")
            sections = read_text_spec(path)
            cases = compile_cases(sections, self.mappings, self.profile, path.name)
            self.assertEqual(len(cases), 1)
            source = render_python(cases, REGISTRY, RUNNER)
            ast.parse(source)

            ns = {"__name__": "generated_test"}
            exec(compile(source, "generated_test.py", "exec"), ns)
            bench = self.bench()
            runner = ns["RUNNERS"][cases[0].id]
            result = runner(bench)
            return cases[0], source, result

    def test_if_elif_else_branching(self):
        spec = """# TESTFALL: TC_IF_BRANCHING
**NAME:** If Else Branching Test

## Action
10: FOR (val;[10, 20, 30])
11:   IF (val == 10)
12.     Versorgung auf 12 V setzen
13:   ELSE IF (val == 20)
14.     Versorgung auf 13.5 V setzen
15:   ELSE
16.     Versorgung auf 14.5 V setzen
17:   END IF
18: END FOR

## Expected Result
10. CAN-Signal CellTempMax ist 25 °C
"""
        case, source, result = self._compile_and_run(spec)
        self.assertEqual(result.result, "PASS")
        self.assertIn("if val == 10:", source)
        self.assertIn("elif val == 20:", source)
        self.assertIn("else:", source)

    def test_switch_case_default(self):
        spec = """# TESTFALL: TC_SWITCH_CASE
**NAME:** Switch Case Test

## Action
10: FOR (code;[1, 2, 99])
11:   SWITCH (code)
12:     CASE (1)
13.       Versorgung auf 11 V setzen
14:     CASE (2)
15.       Versorgung auf 12 V setzen
16:     DEFAULT
17.       Versorgung auf 13.8 V setzen
18:   END SWITCH
19: END FOR

## Expected Result
10. CAN-Signal CellTempMax ist 25 °C
"""
        case, source, result = self._compile_and_run(spec)
        self.assertEqual(result.result, "PASS")
        self.assertIn("match code:", source)
        self.assertIn("case 1:", source)
        self.assertIn("case 2:", source)
        self.assertIn("case _:", source)

    def test_nested_branching_and_break(self):
        spec = """# TESTFALL: TC_NESTED_BRANCHING
**NAME:** Nested Branching and Break Test

## Action
10: FOR (v;[1, 2, 3, 4])
11:   IF (v > 1)
12:     SWITCH (v)
13:       CASE (2)
14.         Versorgung auf 12 V setzen
15:       CASE (3)
16.         Versorgung auf 13 V setzen
17:         BREAK
18:       DEFAULT
19.         Versorgung auf 14 V setzen
20:     END SWITCH
21:   END IF
22: END FOR

## Expected Result
10. CAN-Signal CellTempMax ist 25 °C
"""
        case, source, result = self._compile_and_run(spec)
        self.assertEqual(result.result, "PASS")
        self.assertIn("if v > 1:", source)
        self.assertIn("match v:", source)
        self.assertIn("case 3:", source)
        self.assertIn("break", source)

    def test_branching_in_precondition_and_cleanup(self):
        spec = """# TESTFALL: TC_PRE_POST_BRANCHING
**NAME:** Branching in Precondition and Cleanup

## Precondition
10: FOR (init;[1])
11:   IF (init == 1)
12.     Zündung an
13:   END IF
14: END FOR

## Action
20. Batteriespannung = 12V

## Postcondition
30: FOR (term;[1])
31:   SWITCH (term)
32:     CASE (1)
33.       Zündung aus
34:     DEFAULT
35.       Versorgung auf 0 V setzen
36:   END SWITCH
37: END FOR
"""
        case, source, result = self._compile_and_run(spec)
        self.assertEqual(result.result, "PASS")
        self.assertIn("finally:", source)

    def test_parser_unclosed_if_error(self):
        spec = """# TESTFALL: TC_ERR_IF
**NAME:** Error Test

## Action
10: FOR (i;[1, 2])
11:   IF (i == 1)
12.     Versorgung auf 12 V setzen
13: END FOR
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "err.md"
            path.write_text(spec, encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "unclosed IF block before END FOR"):
                read_text_spec(path)

    def test_parser_unclosed_switch_error(self):
        spec = """# TESTFALL: TC_ERR_SW
**NAME:** Error Test

## Action
10: FOR (i;[1, 2])
11:   SWITCH (i)
12:     CASE (1)
13.       Versorgung auf 12 V setzen
14: END FOR
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "err.md"
            path.write_text(spec, encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "unclosed SWITCH block before END FOR"):
                read_text_spec(path)

    def test_unexpected_end_if_and_end_switch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p1 = Path(tmp_dir) / "p1.md"
            p1.write_text("# TESTFALL: TC_T1\n**NAME:** N\n## Action\n10: END IF\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "unexpected END IF without active IF block"):
                read_text_spec(p1)

            p2 = Path(tmp_dir) / "p2.md"
            p2.write_text("# TESTFALL: TC_T2\n**NAME:** N\n## Action\n10: END SWITCH\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "unexpected END SWITCH without active SWITCH block"):
                read_text_spec(p2)

    def test_invalid_else_and_default_ordering(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # ELSE without IF
            p = Path(tmp_dir) / "t1.md"
            p.write_text("# TESTFALL: TC_T1\n**NAME:** N\n## Action\n10: ELSE\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "ELSE without active IF block"):
                read_text_spec(p)

            # Multiple ELSE
            p = Path(tmp_dir) / "t2.md"
            p.write_text("# TESTFALL: TC_T2\n**NAME:** N\n## Action\n10: IF (x == 1)\n11: ELSE\n12: ELSE\n13: END IF\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "multiple ELSE branches in same IF block"):
                read_text_spec(p)

            # ELSE IF after ELSE
            p = Path(tmp_dir) / "t3.md"
            p.write_text("# TESTFALL: TC_T3\n**NAME:** N\n## Action\n10: IF (x == 1)\n11: ELSE\n12: ELSE IF (x == 2)\n13: END IF\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "ELSE IF after ELSE is not allowed"):
                read_text_spec(p)

            # CASE outside SWITCH
            p = Path(tmp_dir) / "t4.md"
            p.write_text("# TESTFALL: TC_T4\n**NAME:** N\n## Action\n10: CASE (1)\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "CASE statement outside of SWITCH block"):
                read_text_spec(p)

            # CASE after DEFAULT
            p = Path(tmp_dir) / "t5.md"
            p.write_text("# TESTFALL: TC_T5\n**NAME:** N\n## Action\n10: SWITCH (x)\n11: DEFAULT\n12: CASE (1)\n13: END SWITCH\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "CASE after DEFAULT is not allowed"):
                read_text_spec(p)

            # Multiple DEFAULT
            p = Path(tmp_dir) / "t6.md"
            p.write_text("# TESTFALL: TC_T6\n**NAME:** N\n## Action\n10: SWITCH (x)\n11: DEFAULT\n12: DEFAULT\n13: END SWITCH\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "multiple DEFAULT branches in same SWITCH block"):
                read_text_spec(p)

            # Command directly in SWITCH
            p = Path(tmp_dir) / "t7.md"
            p.write_text("# TESTFALL: TC_T7\n**NAME:** N\n## Action\n10: SWITCH (x)\n11. Versorgung auf 12 V setzen\n12: END SWITCH\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "must be placed inside a branch"):
                read_text_spec(p)

    def test_scoping_undefined_variable_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Undefined variable in IF
            p = Path(tmp_dir) / "s1.md"
            p.write_text("# TESTFALL: TC_S1\n**NAME:** N\n## Action\n10: IF (undeclared_var == 5)\n11. Versorgung auf 12 V setzen\n12: END IF\n", encoding="utf-8")
            sections = read_text_spec(p)
            with self.assertRaisesRegex(SpecError, "variable 'undeclared_var' in IF condition is undefined"):
                compile_cases(sections, self.mappings, self.profile, p.name)

            # Undefined variable in SWITCH
            p = Path(tmp_dir) / "s2.md"
            p.write_text("# TESTFALL: TC_S2\n**NAME:** N\n## Action\n10: SWITCH (undeclared_var)\n11: CASE (1)\n12. Versorgung auf 12 V setzen\n13: END SWITCH\n", encoding="utf-8")
            sections = read_text_spec(p)
            with self.assertRaisesRegex(SpecError, "variable 'undeclared_var' in SWITCH is undefined"):
                compile_cases(sections, self.mappings, self.profile, p.name)

    def test_while_loop_execution_and_break(self):
        spec = """# TESTFALL: TC_WHILE_LOOP
**NAME:** While Loop Test
**ANFORDERUNG:** REQ_WHILE_001

## Action
10: FOR (step;[1])
11:   WHILE (step <= 1)
12.     Versorgung auf 12 V setzen
13:     BREAK (step == 1)
14:   END WHILE
15: END FOR

## Expected Result
10. CAN-Signal CellTempMax ist 25 °C
"""
        case, source, result = self._compile_and_run(spec)
        self.assertEqual(result.result, "PASS")
        self.assertEqual(case.requirement, "REQ_WHILE_001")
        self.assertIn("while step <= 1:", source)
        self.assertIn("if step == 1:", source)
        self.assertIn("break", source)

    def test_compound_conditions_and_or_parens(self):
        spec = """# TESTFALL: TC_COMPOUND_COND
**NAME:** Compound Condition Test
**REQUIREMENT:** REQ_LOGIC_002

## Action
10: FOR (v;[10, 25, 99])
11:   IF ((v >= 10 AND v <= 20) OR v == 99)
12.     Versorgung auf 12 V setzen
13:   ELSE IF (v > 20 && v < 30)
14.     Versorgung auf 13.5 V setzen
15:   ELSE
16.     Versorgung auf 14 V setzen
17:   END IF
18: END FOR

## Expected Result
10. CAN-Signal CellTempMax ist 25 °C
"""
        case, source, result = self._compile_and_run(spec)
        self.assertEqual(result.result, "PASS")
        self.assertEqual(case.requirement, "REQ_LOGIC_002")
        self.assertIn("if ((v >= 10 and v <= 20) or v == 99):", source)
        self.assertIn("elif (v > 20 and v < 30):", source)

    def test_parser_unclosed_while_error(self):
        spec = """# TESTFALL: TC_ERR_WHILE
**NAME:** Error While
## Action
10: FOR (i;[1, 2])
11:   WHILE (i < 2)
12.     Versorgung auf 12 V setzen
13: END FOR
"""
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / "err_while.md"
            path.write_text(spec, encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "unclosed WHILE block before END FOR"):
                read_text_spec(path)

    def test_unexpected_end_while(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            p = Path(tmp_dir) / "p.md"
            p.write_text("# TESTFALL: TC_W1\n**NAME:** N\n## Action\n10: END WHILE\n", encoding="utf-8")
            with self.assertRaisesRegex(SpecError, "unexpected END WHILE without active WHILE loop"):
                read_text_spec(p)

    def test_while_and_compound_scoping_errors(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            # Undefined variable in WHILE condition
            p1 = Path(tmp_dir) / "w1.md"
            p1.write_text("# TESTFALL: TC_W1\n**NAME:** N\n## Action\n10: WHILE (undef_var < 5)\n11. Versorgung auf 12 V setzen\n12: END WHILE\n", encoding="utf-8")
            sections = read_text_spec(p1)
            with self.assertRaisesRegex(SpecError, "variable 'undef_var' in WHILE condition is undefined"):
                compile_cases(sections, self.mappings, self.profile, p1.name)

            # Undefined variable in Compound condition
            p2 = Path(tmp_dir) / "w2.md"
            p2.write_text("# TESTFALL: TC_W2\n**NAME:** N\n## Action\n10: FOR (v;[1])\n11: IF (v == 1 AND missing_var > 0)\n12. Versorgung auf 12 V setzen\n13: END IF\n14: END FOR\n", encoding="utf-8")
            sections = read_text_spec(p2)
            with self.assertRaisesRegex(SpecError, "variable 'missing_var' in IF condition is undefined"):
                compile_cases(sections, self.mappings, self.profile, p2.name)


if __name__ == "__main__":
    unittest.main()
