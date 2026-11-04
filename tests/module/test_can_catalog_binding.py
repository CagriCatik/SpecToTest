"""Regression tests for order-independent parameter binding and per-project CAN catalogs.

These tests pin two behaviours that previously depended on hidden process state:

1. A symbolic CAN state is resolved against the signal of the *same* operation call,
   regardless of the placeholder order in the sentence template and regardless of
   which sentence was compiled before.
2. The active project's signal catalog is the only source of symbolic states. There
   are no built-in demo states, no import-time database loads and no silent fallbacks.

Expected raw values are written literally in the tests; they are never computed with
the production converter.
"""

from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest

from operations.can_catalog import (
    CAN_CATALOG_KEY,
    UNCONFIGURED_CATALOG,
    load_can_signal_catalog,
)
from operations.registry import REGISTRY, build_operations_registry
from tcg.adapters.inbound.text_parser import parse_text_spec
from tcg.adapters.outbound.dummy_bench import VectorDummyBench, load_config
from tcg.adapters.outbound.python_emitter import render_python
from tcg.core.compiler import compile_cases
from tcg.core.mapping import load_mappings, parse_mapping_document
from tcg.core.parameters import dependencies_of
from tcg.core.model import SpecError, VariableRef
from tcg.core.profile import load_profile

ROOT = Path(__file__).resolve().parents[2]
RESOURCES = ROOT / 'inputs' / 'resources.json'
BENCH_CONFIG = ROOT / 'inputs' / 'demo_bench.json'

# Two signals whose symbolic states are deliberately inverted against each other.
# DoorContactStatus: Geschlossen=0, Offen=1
# InterlockStatus:   Offen=0,       Geschlossen=1
OPPOSED_DATABASE = {
    'database': 'OpposedStates',
    'messages': {
        'Body_01': {'id': '0x200', 'dlc': 8},
        'BMS_01_State': {'id': '0x300', 'dlc': 8},
        'Brake_01': {'id': '0x120', 'dlc': 8},
    },
    'signals': {
        'DoorContactStatus': {
            'message': 'Body_01', 'start_bit': 0, 'length': 1,
            'values': {'0': 'Geschlossen', '1': 'Offen'},
        },
        'InterlockStatus': {
            'message': 'BMS_01_State', 'start_bit': 10, 'length': 1,
            'values': {'0': 'Offen', '1': 'Geschlossen'},
        },
        'BMSState': {
            'message': 'BMS_01_State', 'start_bit': 0, 'length': 4,
            'values': {'0': 'Init', '1': 'Standby', '3': 'DriveReady'},
        },
        'VehicleSpeed': {
            'message': 'Brake_01', 'start_bit': 0, 'length': 16, 'unit': 'km/h',
        },
    },
}

# Signal first, then value -- the shipped sentence order.
SIGNAL_FIRST_MAPPING = """
[[mapping]]
id = "MAP_SET"
template = "CAN-Signal {signal} auf {wert} setzen"
operation = "set_can_signal"
parameters = { signal = "signal", wert = "value" }

[[mapping]]
id = "MAP_EXPECT"
template = "CAN-Signal {signal} ist {wert}"
operation = "expect_can_signal"
parameters = { signal = "signal", wert = "value" }
"""

# Value first, then signal -- an equally valid custom sentence order.
VALUE_FIRST_MAPPING = """
[[mapping]]
id = "MAP_SET_REVERSED"
template = "Wert {wert} an CAN-Signal {signal} setzen"
operation = "set_can_signal"
parameters = { wert = "value", signal = "signal" }

[[mapping]]
id = "MAP_EXPECT_REVERSED"
template = "Wert {wert} wird von CAN-Signal {signal} gemeldet"
operation = "expect_can_signal"
parameters = { wert = "value", signal = "signal" }
"""


def spec_document(test_id, *commands, expectations=()):
    lines = [f'# TESTFALL: {test_id}', f'NAME: {test_id}', '', '## Ablauf']
    lines += [f'{10 * (index + 1)}. {command}' for index, command in enumerate(commands)]
    if expectations:
        lines += ['', '## Erwartungen']
        lines += [f'{10 * (index + 1)}. {text}' for index, text in enumerate(expectations)]
    return '\n'.join(lines) + '\n'


class CanCatalogFixture(unittest.TestCase):
    """Small, independent fixture: one resource profile, one catalog, one registry."""

    maxDiff = None

    def setUp(self):
        self.profile = load_profile(RESOURCES)
        self.catalog = load_can_signal_catalog(OPPOSED_DATABASE, name='opposed.json')
        self.registry = build_operations_registry(can_catalog=self.catalog)

    def mappings(self, toml_text, registry=None):
        return load_mappings(parse_mapping_document(toml_text), registry or self.registry)

    def arguments(self, mappings, command, test_id='TC_X'):
        """Compile a single command and return its operation arguments as a dict."""
        cases = compile_cases(parse_text_spec(spec_document(test_id, command)),
                              mappings, self.profile, f'{test_id}.md')
        steps = list(cases[0].all_steps())
        self.assertEqual(len(steps), 1, 'fixture expects exactly one compiled step')
        return dict(steps[0].arguments)


class TestOpposedEnumResolution(CanCatalogFixture):
    """C1: opposed enum assignments resolve per signal, for actions and expectations."""

    def test_action_resolves_state_against_its_own_signal(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assertEqual(
            self.arguments(mappings, 'CAN-Signal DoorContactStatus auf Geschlossen setzen'),
            {'signal': 'DoorContactStatus', 'value': Decimal('0')})
        self.assertEqual(
            self.arguments(mappings, 'CAN-Signal InterlockStatus auf Geschlossen setzen'),
            {'signal': 'InterlockStatus', 'value': Decimal('1')})

    def test_expectation_resolves_state_against_its_own_signal(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assertEqual(
            self.arguments(mappings, 'CAN-Signal DoorContactStatus ist Offen'),
            {'signal': 'DoorContactStatus', 'value': Decimal('1')})
        self.assertEqual(
            self.arguments(mappings, 'CAN-Signal InterlockStatus ist Offen'),
            {'signal': 'InterlockStatus', 'value': Decimal('0')})

    def test_both_signals_in_one_specification(self):
        """Two calls in one test case must not influence each other."""
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        document = spec_document(
            'TC_BOTH',
            'CAN-Signal InterlockStatus auf Geschlossen setzen',
            'CAN-Signal DoorContactStatus auf Geschlossen setzen',
            'CAN-Signal InterlockStatus auf Offen setzen',
        )
        cases = compile_cases(parse_text_spec(document), mappings, self.profile, 'both.md')
        values = [dict(step.arguments) for step in cases[0].all_steps()]
        self.assertEqual(values, [
            {'signal': 'InterlockStatus', 'value': Decimal('1')},
            {'signal': 'DoorContactStatus', 'value': Decimal('0')},
            {'signal': 'InterlockStatus', 'value': Decimal('0')},
        ])


class TestPlaceholderOrderIndependence(CanCatalogFixture):
    """C2: a value-before-signal template resolves exactly like signal-before-value."""

    def test_reversed_template_resolves_value_against_its_own_signal(self):
        mappings = self.mappings(VALUE_FIRST_MAPPING)
        self.assertEqual(
            self.arguments(mappings, 'Wert Geschlossen an CAN-Signal DoorContactStatus setzen'),
            {'signal': 'DoorContactStatus', 'value': Decimal('0')})
        self.assertEqual(
            self.arguments(mappings, 'Wert Geschlossen an CAN-Signal InterlockStatus setzen'),
            {'signal': 'InterlockStatus', 'value': Decimal('1')})

    def test_reversed_template_is_immune_to_previously_compiled_signal(self):
        """The documented counterexample: compiling InterlockStatus first must not leak."""
        mappings = self.mappings(VALUE_FIRST_MAPPING)
        target = 'Wert Geschlossen an CAN-Signal DoorContactStatus setzen'

        # Cold: nothing compiled before.
        cold = self.arguments(mappings, target, test_id='TC_COLD')

        # Warm: the opposed signal was compiled immediately before, in the same process.
        self.arguments(mappings, 'Wert Geschlossen an CAN-Signal InterlockStatus setzen',
                       test_id='TC_WARM_PRE')
        warm = self.arguments(mappings, target, test_id='TC_WARM')

        self.assertEqual(cold, {'signal': 'DoorContactStatus', 'value': Decimal('0')})
        self.assertEqual(warm, cold, 'value conversion must not depend on the previous sentence')

    def test_both_placeholder_orders_agree(self):
        """Semantically identical sentences in either order yield identical arguments."""
        forward = self.mappings(SIGNAL_FIRST_MAPPING)
        reversed_ = self.mappings(VALUE_FIRST_MAPPING)
        for signal, state, expected in (
            ('DoorContactStatus', 'Geschlossen', Decimal('0')),
            ('DoorContactStatus', 'Offen', Decimal('1')),
            ('InterlockStatus', 'Geschlossen', Decimal('1')),
            ('InterlockStatus', 'Offen', Decimal('0')),
        ):
            with self.subTest(signal=signal, state=state):
                a = self.arguments(forward, f'CAN-Signal {signal} auf {state} setzen')
                b = self.arguments(reversed_, f'Wert {state} an CAN-Signal {signal} setzen')
                self.assertEqual(a, {'signal': signal, 'value': expected})
                self.assertEqual(a, b)

    def test_reversed_expectation_template(self):
        mappings = self.mappings(VALUE_FIRST_MAPPING)
        self.assertEqual(
            self.arguments(mappings, 'Wert Geschlossen wird von CAN-Signal InterlockStatus gemeldet'),
            {'signal': 'InterlockStatus', 'value': Decimal('1')})


class TestCompilationIndependence(CanCatalogFixture):
    """C3: compiling specifications in different orders yields identical arguments."""

    def test_permuted_compilation_order_is_irrelevant(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING + VALUE_FIRST_MAPPING)
        commands = [
            'CAN-Signal DoorContactStatus auf Geschlossen setzen',
            'Wert Geschlossen an CAN-Signal InterlockStatus setzen',
            'CAN-Signal InterlockStatus auf Offen setzen',
            'Wert Offen an CAN-Signal DoorContactStatus setzen',
        ]

        def compile_all(order):
            return {command: self.arguments(mappings, command, test_id=f'TC_P{index}')
                    for index, command in enumerate(order)}

        forward = compile_all(commands)
        backward = compile_all(list(reversed(commands)))
        interleaved = compile_all([commands[2], commands[0], commands[3], commands[1]])

        self.assertEqual(forward, backward)
        self.assertEqual(forward, interleaved)
        self.assertEqual(forward[commands[0]], {'signal': 'DoorContactStatus', 'value': Decimal('0')})
        self.assertEqual(forward[commands[1]], {'signal': 'InterlockStatus', 'value': Decimal('1')})

    def test_fresh_registry_produces_the_same_arguments(self):
        """A second, independently built registry must agree with the first."""
        other = build_operations_registry(
            can_catalog=load_can_signal_catalog(OPPOSED_DATABASE, name='opposed.json'))
        command = 'Wert Geschlossen an CAN-Signal DoorContactStatus setzen'
        first = self.arguments(self.mappings(VALUE_FIRST_MAPPING), command, test_id='TC_R1')
        second = self.arguments(self.mappings(VALUE_FIRST_MAPPING, registry=other),
                                command, test_id='TC_R2')
        self.assertEqual(first, second)


class TestIncompatibleStateRejection(CanCatalogFixture):
    """C4: a state declared for another signal is rejected, in ACTION and EXPECTED."""

    def assert_rejected(self, mappings, command, signal, state, allowed=()):
        with self.assertRaises(SpecError) as caught:
            self.arguments(mappings, command, test_id='TC_REJECT')
        message = str(caught.exception)
        self.assertIn(repr(state), message)
        self.assertIn(repr(signal), message)
        for option in allowed:
            self.assertIn(option, message)

    def test_continuous_signal_rejects_symbolic_state_in_action(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assert_rejected(mappings, 'CAN-Signal VehicleSpeed auf DriveReady setzen',
                             'VehicleSpeed', 'DriveReady')

    def test_continuous_signal_rejects_symbolic_state_in_expectation(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assert_rejected(mappings, 'CAN-Signal VehicleSpeed ist DriveReady',
                             'VehicleSpeed', 'DriveReady')

    def test_enum_signal_rejects_foreign_state_in_action(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assert_rejected(mappings, 'CAN-Signal BMSState auf Geschlossen setzen',
                             'BMSState', 'Geschlossen', allowed=('Standby', 'DriveReady'))

    def test_enum_signal_rejects_foreign_state_in_expectation(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assert_rejected(mappings, 'CAN-Signal BMSState ist Geschlossen',
                             'BMSState', 'Geschlossen', allowed=('Standby', 'DriveReady'))

    def test_reversed_template_also_rejects_incompatible_state(self):
        mappings = self.mappings(VALUE_FIRST_MAPPING)
        self.assert_rejected(mappings, 'Wert DriveReady an CAN-Signal VehicleSpeed setzen',
                             'VehicleSpeed', 'DriveReady')

    def test_own_state_of_the_signal_is_accepted(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assertEqual(self.arguments(mappings, 'CAN-Signal BMSState auf DriveReady setzen'),
                         {'signal': 'BMSState', 'value': Decimal('3')})


class TestProjectIsolation(CanCatalogFixture):
    """C5: switching projects must not carry symbolic states or values across."""

    PROJECT_A = {
        'database': 'ProjectA',
        'messages': {'M': {'id': '0x100', 'dlc': 8}},
        'signals': {'DoorContactStatus': {'message': 'M', 'start_bit': 0, 'length': 2,
                                          'values': {'0': 'Geschlossen', '1': 'Offen'}},
                    'ProjectAOnly': {'message': 'M', 'start_bit': 4, 'length': 2,
                                     'values': {'7': 'NurA'}}},
    }
    PROJECT_B = {
        'database': 'ProjectB',
        'messages': {'M': {'id': '0x100', 'dlc': 8}},
        'signals': {'DoorContactStatus': {'message': 'M', 'start_bit': 0, 'length': 2,
                                          'values': {'2': 'Geschlossen', '3': 'Offen'}}},
    }

    def registry_for(self, database, name):
        return build_operations_registry(
            can_catalog=load_can_signal_catalog(database, name=name))

    def test_same_state_name_has_different_values_per_project(self):
        command = 'CAN-Signal DoorContactStatus auf Geschlossen setzen'
        registry_a = self.registry_for(self.PROJECT_A, 'a.json')
        registry_b = self.registry_for(self.PROJECT_B, 'b.json')

        value_a = self.arguments(self.mappings(SIGNAL_FIRST_MAPPING, registry=registry_a),
                                 command, test_id='TC_A')
        value_b = self.arguments(self.mappings(SIGNAL_FIRST_MAPPING, registry=registry_b),
                                 command, test_id='TC_B')
        # Recompile A after B to prove B did not overwrite shared state.
        value_a_again = self.arguments(self.mappings(SIGNAL_FIRST_MAPPING, registry=registry_a),
                                       command, test_id='TC_A2')

        self.assertEqual(value_a, {'signal': 'DoorContactStatus', 'value': Decimal('0')})
        self.assertEqual(value_b, {'signal': 'DoorContactStatus', 'value': Decimal('2')})
        self.assertEqual(value_a_again, value_a)

    def test_states_of_the_other_project_are_unknown(self):
        registry_b = self.registry_for(self.PROJECT_B, 'b.json')
        self.registry_for(self.PROJECT_A, 'a.json')  # loaded first, must not leak into B
        mappings = self.mappings(SIGNAL_FIRST_MAPPING, registry=registry_b)
        with self.assertRaises(SpecError) as caught:
            self.arguments(mappings, 'CAN-Signal DoorContactStatus auf NurA setzen',
                           test_id='TC_LEAK')
        self.assertIn('NurA', str(caught.exception))


class TestCatalogAuthority(CanCatalogFixture):
    """C6: only the declared states of the active catalog are accepted."""

    RENAMED = {
        'database': 'Renamed',
        'messages': {'Body_01': {'id': '0x200', 'dlc': 8}},
        'signals': {'DoorContactStatus': {'message': 'Body_01', 'start_bit': 0, 'length': 1,
                                          'values': {'0': 'Zu', '1': 'Auf'}}},
    }

    def setUp(self):
        super().setUp()
        self.renamed_registry = build_operations_registry(
            can_catalog=load_can_signal_catalog(self.RENAMED, name='renamed.json'))
        self.renamed_mappings = self.mappings(SIGNAL_FIRST_MAPPING,
                                              registry=self.renamed_registry)

    def test_declared_states_are_accepted(self):
        self.assertEqual(self.arguments(self.renamed_mappings,
                                        'CAN-Signal DoorContactStatus auf Zu setzen'),
                         {'signal': 'DoorContactStatus', 'value': Decimal('0')})
        self.assertEqual(self.arguments(self.renamed_mappings,
                                        'CAN-Signal DoorContactStatus auf Auf setzen'),
                         {'signal': 'DoorContactStatus', 'value': Decimal('1')})

    def test_removed_demo_states_are_rejected(self):
        """Geschlossen/Offen are gone from the catalog, so they must not resolve."""
        for removed in ('Geschlossen', 'Offen'):
            with self.subTest(state=removed):
                with self.assertRaises(SpecError) as caught:
                    self.arguments(self.renamed_mappings,
                                   f'CAN-Signal DoorContactStatus auf {removed} setzen',
                                   test_id=f'TC_GONE_{removed}')
                message = str(caught.exception)
                self.assertIn(removed, message)
                self.assertNotIn("value=Decimal", message)

    def test_no_builtin_states_without_a_catalog(self):
        """An unconfigured catalog knows no symbolic state at all."""
        bare = build_operations_registry(can_catalog=None)
        mappings = self.mappings(SIGNAL_FIRST_MAPPING, registry=bare)
        with self.assertRaises(SpecError) as caught:
            self.arguments(mappings, 'CAN-Signal DoorContactStatus auf Geschlossen setzen',
                           test_id='TC_NODB')
        self.assertIn('Geschlossen', str(caught.exception))

    def test_default_registry_carries_no_catalog(self):
        """Importing the registry must not adopt any project database."""
        value_type = REGISTRY['set_can_signal'].parameter('value').type
        self.assertIs(value_type.catalog, UNCONFIGURED_CATALOG)
        self.assertFalse(UNCONFIGURED_CATALOG.configured)
        self.assertEqual(UNCONFIGURED_CATALOG.signal_names(), ())

    def test_building_a_registry_does_not_mutate_the_default(self):
        before = REGISTRY['set_can_signal'].parameter('value').type.catalog
        build_operations_registry(can_catalog=self.catalog)
        after = REGISTRY['set_can_signal'].parameter('value').type.catalog
        self.assertIs(before, after)
        self.assertIs(after, UNCONFIGURED_CATALOG)


class TestCatalogValidation(unittest.TestCase):
    """C7: missing, corrupt, duplicated and ambiguous catalog data fail visibly."""

    def catalog_from_text(self, text, name='db.json'):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / name
            path.write_text(text, encoding='utf-8')
            return load_can_signal_catalog(path)

    def test_missing_file(self):
        with self.assertRaises(SpecError) as caught:
            load_can_signal_catalog(Path('/nonexistent/never_there_signals.json'))
        self.assertIn('never_there_signals.json', str(caught.exception))

    def test_corrupt_json(self):
        with self.assertRaises(SpecError) as caught:
            self.catalog_from_text('{ this is not valid json }', name='broken.json')
        message = str(caught.exception)
        self.assertIn('broken.json', message)
        self.assertIn('JSON', message)

    def test_duplicate_json_keys_are_rejected_before_overwriting(self):
        text = '{"signals": {"S": {"values": {"0": "Auf", "0": "Zu"}}}}'
        with self.assertRaises(SpecError) as caught:
            self.catalog_from_text(text, name='dup.json')
        message = str(caught.exception)
        self.assertIn('dup.json', message)
        self.assertIn('0', message)

    def test_duplicate_signal_keys_are_rejected(self):
        text = ('{"signals": {"S": {"values": {"0": "Auf"}},'
                ' "S": {"values": {"1": "Zu"}}}}')
        with self.assertRaises(SpecError) as caught:
            self.catalog_from_text(text, name='dupsig.json')
        self.assertIn('S', str(caught.exception))

    def test_missing_signals_key(self):
        with self.assertRaises(SpecError) as caught:
            load_can_signal_catalog({'database': 'NoSignals'}, name='nosig.json')
        self.assertIn('signals', str(caught.exception))

    def test_non_finite_enum_value(self):
        for raw in ('NaN', 'Infinity', '-Infinity'):
            with self.subTest(raw=raw):
                with self.assertRaises(SpecError) as caught:
                    load_can_signal_catalog(
                        {'signals': {'S': {'values': {raw: 'Zustand'}}}}, name='nan.json')
                self.assertIn(raw, str(caught.exception))

    def test_non_numeric_enum_value(self):
        with self.assertRaises(SpecError) as caught:
            load_can_signal_catalog(
                {'signals': {'S': {'values': {'zwei': 'Zustand'}}}}, name='text.json')
        self.assertIn('zwei', str(caught.exception))

    def test_ambiguous_state_names_after_normalisation(self):
        """Space and underscore are equated, so a contradicting pair must fail loudly."""
        with self.assertRaises(SpecError) as caught:
            load_can_signal_catalog(
                {'signals': {'S': {'values': {'0': 'Drive Ready', '1': 'Drive_Ready'}}}},
                name='ambig.json')
        message = str(caught.exception)
        self.assertIn('S', message)
        self.assertIn('Drive', message)

    def test_case_insensitive_collision_is_rejected(self):
        with self.assertRaises(SpecError) as caught:
            load_can_signal_catalog(
                {'signals': {'S': {'values': {'0': 'Offen', '1': 'offen'}}}}, name='case.json')
        self.assertIn('Offen', str(caught.exception))

    def test_identical_state_repeated_with_the_same_value_is_allowed(self):
        catalog = load_can_signal_catalog(
            {'signals': {'S': {'values': {'0': 'Offen'}, 'unit': ''}}}, name='ok.json')
        self.assertEqual(catalog.resolve_state('S', 'Offen'), Decimal('0'))
        self.assertEqual(catalog.resolve_state('S', 'offen'), Decimal('0'))

    def test_values_must_be_an_object(self):
        with self.assertRaises(SpecError) as caught:
            load_can_signal_catalog({'signals': {'S': {'values': ['Offen']}}}, name='list.json')
        self.assertIn('S', str(caught.exception))

    def test_state_name_must_be_a_non_empty_string(self):
        for bad in ('', 1, None):
            with self.subTest(bad=bad):
                with self.assertRaises(SpecError):
                    load_can_signal_catalog({'signals': {'S': {'values': {'0': bad}}}},
                                            name='badname.json')

    def test_error_message_names_file_signal_and_state(self):
        with self.assertRaises(SpecError) as caught:
            load_can_signal_catalog(
                {'signals': {'DoorContactStatus': {'values': {'NaN': 'Geschlossen'}}}},
                name='report.json')
        message = str(caught.exception)
        self.assertIn('report.json', message)
        self.assertIn('DoorContactStatus', message)
        self.assertIn('Geschlossen', message)


class TestMappingContractValidation(CanCatalogFixture):
    """A custom sentence that omits the signal placeholder cannot resolve states."""

    def test_value_without_signal_is_refused_at_mapping_load(self):
        broken = """
[[mapping]]
id = "MAP_NO_SIGNAL"
template = "Setze Wert {wert}"
operation = "set_can_signal"
parameters = { wert = "value" }
"""
        with self.assertRaises(SpecError) as caught:
            self.mappings(broken)
        self.assertIn('signal', str(caught.exception))


class TestPreservedBehaviour(CanCatalogFixture):
    """C8: numeric values, units, loops and non-CAN operations keep working."""

    def test_plain_numeric_can_value(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assertEqual(self.arguments(mappings, 'CAN-Signal VehicleSpeed auf 80 setzen'),
                         {'signal': 'VehicleSpeed', 'value': Decimal('80')})

    def test_unit_conversion_is_preserved(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assertEqual(self.arguments(mappings, 'CAN-Signal VehicleSpeed auf 80 km/h setzen'),
                         {'signal': 'VehicleSpeed', 'value': Decimal('80')})

    def test_numeric_value_on_an_enum_signal_stays_numeric(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        self.assertEqual(self.arguments(mappings, 'CAN-Signal DoorContactStatus auf 1 setzen'),
                         {'signal': 'DoorContactStatus', 'value': Decimal('1')})

    def test_loop_variable_over_numeric_can_values(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        document = (
            '# TESTFALL: TC_LOOP\n'
            'NAME: Loop\n'
            '\n'
            '## Ablauf\n'
            '10: FOR (spd;[60, 80])\n'
            '20. CAN-Signal VehicleSpeed auf spd setzen\n'
            '30: END FOR\n'
        )
        cases = compile_cases(parse_text_spec(document), mappings, self.profile, 'loop.md')
        loop = cases[0].steps[0]
        self.assertEqual(loop.variable, 'spd')
        self.assertEqual(list(loop.items), [Decimal('60'), Decimal('80')])

    def test_loop_variable_with_symbolic_state_is_rejected(self):
        """A loop over states of the wrong signal must not silently pass."""
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        document = (
            '# TESTFALL: TC_LOOP_BAD\n'
            'NAME: Loop bad\n'
            '\n'
            '## Ablauf\n'
            '10: FOR (state;[DriveReady])\n'
            '20. CAN-Signal VehicleSpeed auf state setzen\n'
            '30: END FOR\n'
        )
        with self.assertRaises(SpecError) as caught:
            compile_cases(parse_text_spec(document), mappings, self.profile, 'loopbad.md')
        self.assertIn('DriveReady', str(caught.exception))

    def test_undefined_variable_is_still_reported(self):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        with self.assertRaises(SpecError) as caught:
            self.arguments(mappings, 'CAN-Signal VehicleSpeed auf unbekannt setzen',
                           test_id='TC_UNDEF')
        self.assertIn('unbekannt', str(caught.exception))

    def test_tolerance_is_a_plain_numeric_parameter(self):
        """A tolerance is a magnitude, never a symbolic signal state."""
        tolerance = self.registry['expect_can_signal_tolerance'].parameter('tolerance')
        self.assertEqual(dependencies_of(tolerance.type), ())
        self.assertFalse(hasattr(tolerance.type, 'catalog'))
        self.assertEqual(tolerance.type.convert('2', self.profile), Decimal('2'))
        # A state name is never a tolerance: it stays an identifier the compiler must
        # resolve as a loop variable, and can never become a signal's raw value.
        self.assertEqual(tolerance.type.convert('Geschlossen', self.profile),
                         VariableRef('Geschlossen'))
        with self.assertRaises(SpecError):
            tolerance.type.convert('-1', self.profile)

    def test_symbolic_tolerance_is_rejected_when_compiled(self):
        mappings = self.mappings("""
[[mapping]]
id = "MAP_TOL2"
template = "CAN-Signal {signal} ist {wert} ± {toleranz}"
operation = "expect_can_signal_tolerance"
parameters = { signal = "signal", wert = "value", toleranz = "tolerance" }
""")
        with self.assertRaises(SpecError) as caught:
            self.arguments(mappings, 'CAN-Signal InterlockStatus ist Geschlossen ± Offen',
                           test_id='TC_TOLSYM')
        self.assertIn('Offen', str(caught.exception))

    def test_tolerance_mapping_from_the_shipped_project_still_compiles(self):
        mappings = self.mappings("""
[[mapping]]
id = "MAP_TOL"
template = "CAN-Signal {signal} ist {wert} ± {toleranz}"
operation = "expect_can_signal_tolerance"
parameters = { signal = "signal", wert = "value", toleranz = "tolerance" }
""")
        self.assertEqual(
            self.arguments(mappings, 'CAN-Signal VehicleSpeed ist 80 ± 2'),
            {'signal': 'VehicleSpeed', 'value': Decimal('80'), 'tolerance': Decimal('2')})


class TestGeneratedTestExecution(CanCatalogFixture):
    """C9: run a generated test and assert the raw value actually written to the bench."""

    def generate_and_run(self, command, expectation):
        mappings = self.mappings(SIGNAL_FIRST_MAPPING)
        document = spec_document('TC_EXEC', command, expectations=(expectation,))
        cases = compile_cases(parse_text_spec(document), mappings, self.profile, 'exec.md')
        source = render_python(cases, self.registry, 'tcg.runtime.runner')
        namespace = {'__name__': 'generated_can_test'}
        exec(compile(source, 'generated_can_test.py', 'exec'), namespace)

        bench = VectorDummyBench(load_config(BENCH_CONFIG, self.profile))
        runners = namespace['RUNNERS']
        self.assertEqual(list(runners), ['TC_EXEC'])
        result = runners['TC_EXEC'](bench)
        return result, bench

    def test_raw_value_written_to_the_bench_is_the_catalogued_value(self):
        result, bench = self.generate_and_run(
            'CAN-Signal DoorContactStatus auf Geschlossen setzen',
            'CAN-Signal DoorContactStatus ist Geschlossen')
        self.assertEqual(result.result, 'PASS')
        # PASS alone is not proof: action and expectation could share one wrong conversion.
        self.assertEqual(bench.can_signals['DoorContactStatus'], Decimal('0'))

    def test_opposed_signal_writes_the_opposite_raw_value(self):
        result, bench = self.generate_and_run(
            'CAN-Signal InterlockStatus auf Geschlossen setzen',
            'CAN-Signal InterlockStatus ist Geschlossen')
        self.assertEqual(result.result, 'PASS')
        self.assertEqual(bench.can_signals['InterlockStatus'], Decimal('1'))

    def test_generated_source_embeds_the_catalogued_raw_value(self):
        mappings = self.mappings(VALUE_FIRST_MAPPING)
        document = spec_document(
            'TC_SRC', 'Wert Geschlossen an CAN-Signal DoorContactStatus setzen')
        cases = compile_cases(parse_text_spec(document), mappings, self.profile, 'src.md')
        source = render_python(cases, self.registry, 'tcg.runtime.runner')
        self.assertIn("signal='DoorContactStatus'", source)
        self.assertIn("value=Decimal('0')", source)


if __name__ == '__main__':
    unittest.main()
