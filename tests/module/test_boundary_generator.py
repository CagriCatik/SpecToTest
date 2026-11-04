"""Module tests for automated boundary value specification generation."""
import ast
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.generators.boundaries import BoundaryTestConfig, generate_boundary_spec, generate_boundary_suite
from tests.common import BaseTestCase, REGISTRY, ROOT, RUNNER


class BoundaryGeneratorModuleTests(BaseTestCase):

    def test_automated_boundary_value_test_generator(self):
        with tempfile.TemporaryDirectory() as directory:
            with open(ROOT / 'inputs/can_signals.json', 'r', encoding='utf-8') as f:
                can_db = json.load(f)['signals']

            out_files = generate_boundary_suite(
                variable_definitions=can_db,
                target_variables=['PackSOC', 'CellTempMax'],
                set_template="CAN-Signal {name} auf {val}{unit} setzen",
                check_template="CAN-Signal {name} ist {val}{unit}",
                preconditions=["Zündung an", "CAN-Signal Clamp15Status auf 1 setzen"],
                postconditions=["CAN-Signal Clamp15Status auf 0 setzen", "Zündung aus"],
                output_dir=directory,
            )
            self.assertEqual(len(out_files), 2)
            for spec_file in out_files:
                sections = read_text_spec(spec_file)
                cases = compile_cases(sections, self.mappings, self.profile, spec_file.name)
                self.assertEqual(len(cases), 1)
                source = render_python(cases, REGISTRY, RUNNER)
                ast.parse(source)

                ns = {'__name__': 'generated_test'}
                exec(compile(source, 'generated_test.py', 'exec'), ns)
                res = list(ns['RUNNERS'].values())[0](self.bench())
                self.assertEqual(res.result, 'PASS')

    def test_parameter_boundary_generation_with_generic_templates(self):
        cfg = BoundaryTestConfig(
            name='GAIN',
            min_val=Decimal('0'),
            max_val=Decimal('100'),
            nominal_val=Decimal('50'),
            set_template="Parameter {name} auf {val} schreiben",
            check_template="Parameter {name} ist {val}",
            preconditions=("Zündung an",),
            postconditions=("Zündung aus",),
        )
        spec = generate_boundary_spec(cfg)
        self.assertIn("Parameter GAIN auf 0 schreiben", spec)
        self.assertIn("Parameter GAIN auf 50 schreiben", spec)
        self.assertIn("Parameter GAIN auf 100 schreiben", spec)
        self.assertIn("Parameter GAIN ist 100", spec)


if __name__ == '__main__':
    unittest.main()

