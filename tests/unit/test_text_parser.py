"""Unit tests for TXT/Markdown specification parsing, sections, and syntax errors."""
from pathlib import Path
import tempfile
import unittest

from generate import generate
from tcg.adapters.inbound.text_parser import read_text_spec
from tcg.core.compiler import compile_cases
from tcg.core.model import SpecError
from tcg.adapters.outbound.python_emitter import render_python
from tests.common import BASE_SPEC, BaseTestCase, MAPPING, REGISTRY, RESOURCES, RUNNER


class TextParserUnitTests(BaseTestCase):

    def test_parser_syntax_errors_and_control_structures(self):
        valid = BASE_SPEC.read_text(encoding='utf-8')
        cases = (
            (valid.replace('40. Batteriespannung = 7000mV\n'
                           '50. Warte 1 s\n'
                           '60. Fehlerspeicher BCM1 lesen\n'
                           '70. Batteriespannung = 13.8V\n'
                           '80. Warte 500 ms\n', ''),
             'at least one numbered command'),
            (valid.replace('80. Warte 500 ms', '80: FOR (i;[1, 2, 3])'),
             'unclosed FOR loop'),
            (valid.replace('80. Warte 500 ms', '80: BREAK (i==3)'),
             'BREAK statement occurs outside of any FOR loop'),
            (valid.replace('80. Warte 500 ms', '80: FOR (i;[])\nEND FOR'),
             'FOR loop items must not be empty'),
        )
        with tempfile.TemporaryDirectory() as directory:
            for index, (content, message) in enumerate(cases):
                path = Path(directory) / f'bad_{index}.txt'
                path.write_text(content, encoding='utf-8')
                with self.subTest(message=message), self.assertRaisesRegex(SpecError, message):
                    sections = read_text_spec(path)
                    compile_cases(sections, self.mappings, self.profile, path.name)

    def test_empty_preconditions_cleanup_and_action_without_check_are_valid(self):
        text = '''
        Precondition
        Action
        10. Versorgung auf 13.5 V setzen
        Postcondition
        '''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'action_only.txt'
            path.write_text(text, encoding='utf-8')
            cases = compile_cases(read_text_spec(path), self.mappings, self.profile, path.name)
        self.assertEqual([(step.execution_id, step.phase) for step in cases[0].steps], [('S10', 'ACTION')])
        namespace = {'__name__': 'generated_test'}
        exec(compile(render_python(cases, REGISTRY, RUNNER), 'generated_test.py', 'exec'), namespace)
        self.assertEqual(namespace['RUNNERS']['TC_ACTION_ONLY'](self.bench()).result, 'PASS')

    def test_markdown_specification_compilation_and_execution(self):
        md_text = """# TESTFALL: TC_MARKDOWN_DEMO
**NAME:** Markdown Testfall Demo
**TESTZIEL:** Nachweis der vollständigen Markdown-Unterstützung

<!-- Markdown HTML Kommentar -->
---

## Precondition
* 10. Zündung an
* 20. Batteriespannung = 13.8V

```text
## Action
- 30. Fehlerspeicher BCM1 lesen
- 40. Warte 1 s
```

## Expected Result
- 30. Fehlerspeicher BCM1 ist leer

## Postcondition
- 50. Batteriespannung = 13.8V
- 60. Zündung aus
"""
        with tempfile.TemporaryDirectory() as directory:
            md_path = Path(directory) / 'test_spec.md'
            md_path.write_text(md_text, encoding='utf-8')
            out_path = Path(directory) / 'test_md.py'

            # 1. Compile directly from .md file
            cases = generate(md_path, MAPPING, RESOURCES, out_path, REGISTRY, RUNNER)
            self.assertEqual(cases[0].id, 'TC_MARKDOWN_DEMO')
            self.assertEqual(cases[0].name, 'Markdown Testfall Demo')
            self.assertTrue(out_path.exists())

            # 2. Execute generated code against bench
            ns = {}
            exec(compile(out_path.read_text(encoding='utf-8'), str(out_path), 'exec'), ns)
            bench = self.bench()
            res = ns['RUNNERS']['TC_MARKDOWN_DEMO'](bench)
            self.assertEqual(res.result, 'PASS')


if __name__ == '__main__':
    unittest.main()

