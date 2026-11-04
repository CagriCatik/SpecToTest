"""Unit tests for variable scoping, identifier rules, and recursive expectation binding."""
from pathlib import Path
import tempfile
import unittest

from tcg.adapters.inbound.text_parser import parse_text_spec, read_text_spec
from tcg.core.compiler import compile_cases
from tcg.core.model import SpecError
from tests.common import BaseTestCase


class ScopingAndExpectationsUnitTests(BaseTestCase):

    def test_variable_scoping_rejects_undefined_variable(self):
        spec_text = '''
        Precondition
        Action
        10. Batteriespannung = 7000mV
        20. Warte undefined_var
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'bad_scope.txt'
            path.write_text(spec_text, encoding='utf-8')
            sections = read_text_spec(path)
            with self.assertRaisesRegex(SpecError, "variable 'undefined_var' is undefined"):
                compile_cases(sections, self.mappings, self.profile, path.name)

    def test_spec_language_reference_validation(self):
        # 1. Reject duplicate step numbers in Action tree
        bad_dup = """
        Action
        10. Zündung an
        10. Warte 1 s
        """
        with self.assertRaisesRegex(SpecError, "duplicate step number 10 in Action tree"):
            compile_cases(parse_text_spec(bad_dup, 'dup.txt'), self.mappings, self.profile, 'dup.txt')

        # 2. Reject orphaned expected results
        bad_orphan = """
        Action
        10. Zündung an
        Expected Result
        99. Zündung an
        """
        with self.assertRaisesRegex(SpecError, "has no matching target in Action tree"):
            compile_cases(parse_text_spec(bad_orphan, 'orphan.txt'), self.mappings, self.profile, 'orphan.txt')

        # 3. Reject expected result targeting Preconditions
        bad_pre = """
        Precondition
        10. Zündung an
        Action
        20. Warte 1 s
        Expected Result
        10. Zündung an
        """
        with self.assertRaisesRegex(SpecError, "references a Precondition step"):
            compile_cases(parse_text_spec(bad_pre, 'pre.txt'), self.mappings, self.profile, 'pre.txt')

        # 4. Reject expected result targeting Postconditions
        bad_post = """
        Action
        10. Warte 1 s
        Postcondition
        20. Zündung aus
        Expected Result
        20. Zündung aus
        """
        with self.assertRaisesRegex(SpecError, "references a Postcondition step"):
            compile_cases(parse_text_spec(bad_post, 'post.txt'), self.mappings, self.profile, 'post.txt')

        # 5. Reject loop variable shadowing
        bad_shadow = """
        Action
        10. FOR (I; [1, 2])
            20. FOR (I; [3, 4])
                30. Warte 1 s
            END FOR
        END FOR
        """
        with self.assertRaisesRegex(SpecError, "shadows an outer loop variable"):
            compile_cases(parse_text_spec(bad_shadow, 'shadow.txt'), self.mappings, self.profile, 'shadow.txt')

        # 6. Reject reserved loop variable names
        bad_reserved = """
        Action
        10. FOR (bench; [1, 2])
            20. Warte 1 s
        END FOR
        """
        with self.assertRaisesRegex(SpecError, "is a reserved identifier"):
            compile_cases(parse_text_spec(bad_reserved, 'reserved.txt'), self.mappings, self.profile, 'reserved.txt')

    def test_recursive_expectation_binding_loop_and_unnumbered(self):
        spec_text = """
        Action
        10: FOR (v; [10, 20])
            20: Parameter GAIN auf v schreiben
        END FOR
        30: Warte 1 s
        Expected Result
        20: Parameter GAIN ist v
        10: Fehlerspeicher BCM1 ist leer
        Fehlerspeicher BCM1 ist leer
        """
        cases = compile_cases(parse_text_spec(spec_text, 'loop_exp.txt'), self.mappings, self.profile, 'loop_exp.txt')
        loop_node = cases[0].steps[0]
        self.assertEqual(type(loop_node).__name__, 'Loop')
        self.assertEqual(len(loop_node.body), 2)
        self.assertEqual(loop_node.body[0].phase, 'ACTION')
        self.assertEqual(loop_node.body[0].test_step, 20)
        self.assertEqual(loop_node.body[1].phase, 'EXPECTED')
        self.assertEqual(loop_node.body[1].test_step, 20)

        # Loop-level check (step 10) is placed after loop_node
        self.assertEqual(cases[0].steps[1].phase, 'EXPECTED')
        self.assertEqual(cases[0].steps[1].test_step, 10)

        # Action 30
        self.assertEqual(cases[0].steps[2].phase, 'ACTION')
        self.assertEqual(cases[0].steps[2].test_step, 30)

        # Unnumbered expected check placed after all actions
        self.assertEqual(cases[0].steps[3].phase, 'EXPECTED')
        self.assertIsNone(cases[0].steps[3].test_step)


if __name__ == '__main__':
    unittest.main()

