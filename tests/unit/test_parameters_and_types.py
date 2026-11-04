"""Unit tests for parameter parsing, units, types, and literal rendering."""
import ast
from decimal import Decimal, localcontext
from pathlib import Path
import tempfile
import unittest

from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.python_emitter import literal, render_python
from tcg.core.compiler import compile_cases
from tests.common import BASE_SPEC, BaseTestCase, REGISTRY, RUNNER


class ParameterAndTypeUnitTests(BaseTestCase):

    def test_units_with_and_without_whitespace(self):
        spec_text = '''
        Precondition
        Action
        10. Batteriespannung = 7000mV
        20. Batteriespannung = 13.8V
        30. Batteriespannung = 12 V
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'units.txt'
            path.write_text(spec_text, encoding='utf-8')
            cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
            steps = cases[0].steps
            self.assertEqual(steps[0].arguments, (('value', Decimal('7')),))
            self.assertEqual(steps[1].arguments, (('value', Decimal('13.8')),))
            self.assertEqual(steps[2].arguments, (('value', Decimal('12')),))

    def test_decimal_rendering_is_independent_of_global_context(self):
        value = Decimal('123456789.123456789000')
        with localcontext() as context:
            context.prec = 6
            low_precision = literal(value)
        with localcontext() as context:
            context.prec = 28
            high_precision = literal(value)
        self.assertEqual(low_precision, high_precision)
        self.assertEqual(low_precision, "Decimal('123456789.123456789')")

    def test_python_like_text_remains_a_literal(self):
        spec_text = '''
        Precondition
        Action
        10. Bildschirm SETTINGS auswählen
        20. Anzeige zeigt "__import__(\\"os\\").system(\\"never\\")"
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'py_literal.txt'
            path.write_text(spec_text, encoding='utf-8')
            cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
            source = render_python(cases, REGISTRY, RUNNER)
            ast.parse(source)
            self.assertIn('__import__', source)
            self.assertNotIn('system("never")\n', source)

    def test_outer_whitespace_tabs_and_crlf_do_not_change_output(self):
        original_cases = compile_cases(read_text_spec(BASE_SPEC), self.mappings, self.profile, BASE_SPEC.name)
        lines = BASE_SPEC.read_text(encoding='utf-8').splitlines()
        tolerant = '\r\n'.join(f'\t{line}\t' if line else '\t  ' for line in lines) + '\r\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / BASE_SPEC.name
            path.write_bytes(tolerant.encode('utf-8'))
            tolerant_cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
        self.assertEqual(render_python(original_cases, REGISTRY, RUNNER),
                         render_python(tolerant_cases, REGISTRY, RUNNER))


if __name__ == '__main__':
    unittest.main()

