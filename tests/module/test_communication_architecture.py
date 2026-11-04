"""Acceptance tests for the multi-technology communication architecture.

Covers the agreed criteria: several networks side by side, ambiguous short
references, resource-specific enum values, project isolation, physical versus raw
values, bench capabilities, unsupported import constructs, and that existing CAN
specifications keep working.

Every expected value is written literally; none is computed with the production
converter. All execution evidence here comes from the in-memory simulation bench --
it is explicitly **not** evidence of real CAN/LIN/Ethernet integration.
"""

from decimal import Decimal
from pathlib import Path
import tempfile
import unittest

from operations.registry import REGISTRY, build_operations_registry
from tcg.adapters.inbound.text_parser import parse_text_spec
from tcg.adapters.outbound.dummy_bench import (
    CanOnlyDummyBench,
    VectorDummyBench,
    load_config,
)
from tcg.adapters.outbound.python_emitter import render_python
from tcg.comm.capabilities import (
    bench_capabilities,
    capability_report,
    check_bench_capabilities,
    required_capabilities,
)
from dataclasses import replace

from tcg.comm.catalog import DescriptionConfig, load_catalog, migrate_can_database
from tcg.comm.model import ObjectKind, Technology
from tcg.core.compiler import compile_cases
from tcg.core.mapping import load_mappings, parse_mapping_document
from tcg.core.model import SpecError
from tcg.core.profile import load_profile

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / 'tests' / 'fixtures' / 'comm'
RESOURCES = ROOT / 'inputs' / 'resources.json'
BENCH_CONFIG = FIXTURES / 'multi_bus_bench.json'

POWERTRAIN = DescriptionConfig(path=str(FIXTURES / 'powertrain_can.json'),
                               network='PowertrainCAN', technology='can')
CHASSIS = DescriptionConfig(path=str(FIXTURES / 'chassis_can.json'),
                            network='ChassisCAN', technology='can',
                            adapter_naming='prefixed')
BODY_LIN = DescriptionConfig(path=str(FIXTURES / 'body_lin.ldf'), network='BodyLIN')
BACKBONE = DescriptionConfig(path=str(FIXTURES / 'services.arxml'),
                             network='BackboneEth')

MAPPING = """
[[mapping]]
id = "MAP_CAN_SET"
template = "CAN-Signal {signal} auf {wert} setzen"
operation = "set_can_signal"
parameters = { signal = "signal", wert = "value" }

[[mapping]]
id = "MAP_CAN_SET_RAW"
template = "CAN-Signal {signal} auf Rohwert {wert} setzen"
operation = "set_can_signal_raw"
parameters = { signal = "signal", wert = "value" }

[[mapping]]
id = "MAP_CAN_EXPECT"
template = "CAN-Signal {signal} ist {wert}"
operation = "expect_can_signal"
parameters = { signal = "signal", wert = "value" }

[[mapping]]
id = "MAP_LIN_SET"
template = "LIN-Signal {signal} auf {wert} setzen"
operation = "set_lin_signal"
parameters = { signal = "signal", wert = "value" }

[[mapping]]
id = "MAP_LIN_SET_RAW"
template = "LIN-Signal {signal} auf Rohwert {wert} setzen"
operation = "set_lin_signal_raw"
parameters = { signal = "signal", wert = "value" }

[[mapping]]
id = "MAP_LIN_SCHEDULE"
template = "LIN-Schedule {schedule} aktivieren"
operation = "set_lin_schedule"
parameters = { schedule = "schedule" }

[[mapping]]
id = "MAP_LIN_SCHEDULE_CHECK"
template = "LIN-Schedule ist {schedule}"
operation = "expect_lin_schedule"
parameters = { schedule = "schedule" }

[[mapping]]
id = "MAP_ETH_CALL"
template = "Service-Methode {method} aufrufen"
operation = "call_service_method"
parameters = { method = "method" }

[[mapping]]
id = "MAP_ETH_SUBSCRIBE"
template = "Service-Event {event} abonnieren"
operation = "subscribe_event"
parameters = { event = "event" }

[[mapping]]
id = "MAP_ETH_EVENT_CHECK"
template = "Service-Event {event} wurde empfangen"
operation = "expect_event_received"
parameters = { event = "event" }
"""


def spec(test_id, *commands, expectations=()):
    """Build a specification; expectations bind to the LAST action step."""
    lines = [f'# TESTFALL: {test_id}', f'NAME: {test_id}', '', '## Ablauf']
    lines += [f'{10 * (i + 1)}. {c}' for i, c in enumerate(commands)]
    if expectations:
        last = 10 * len(commands)
        lines += ['', '## Erwartungen']
        lines += [f'{last}. {e}' for e in expectations]
    return '\n'.join(lines) + '\n'


class CommFixture(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        self.profile = load_profile(RESOURCES)

    def catalog(self, *descriptions, aliases=None):
        return load_catalog(descriptions, aliases=aliases)

    def registry_for(self, *descriptions, aliases=None):
        return build_operations_registry(
            catalog=self.catalog(*descriptions, aliases=aliases))

    def mappings(self, registry, toml_text=MAPPING):
        return load_mappings(parse_mapping_document(toml_text), registry)

    def arguments(self, registry, command, test_id='TC_X'):
        maps = self.mappings(registry)
        cases = compile_cases(parse_text_spec(spec(test_id, command)), maps,
                              self.profile, f'{test_id}.md')
        steps = list(cases[0].all_steps())
        self.assertEqual(len(steps), 1)
        return dict(steps[0].arguments)


class TestSeparateNetworks(CommFixture):
    """Signals of the same name in two networks stay separate."""

    def test_catalog_holds_both_networks(self):
        catalog = self.catalog(POWERTRAIN, CHASSIS)
        self.assertEqual(catalog.networks(), ('ChassisCAN', 'PowertrainCAN'))
        speeds = [r for r in catalog.resources
                  if r.name == 'VehicleSpeed' and r.kind is ObjectKind.SIGNAL]
        self.assertEqual(len(speeds), 2)
        self.assertEqual({r.qualified_name for r in speeds},
                         {'PowertrainCAN::Drive_01::VehicleSpeed',
                          'ChassisCAN::Chassis_01::VehicleSpeed'})

    def test_qualified_references_resolve_to_their_own_network(self):
        catalog = self.catalog(POWERTRAIN, CHASSIS)
        powertrain = catalog.find('PowertrainCAN::VehicleSpeed')
        chassis = catalog.find('ChassisCAN::VehicleSpeed')
        self.assertEqual(powertrain.network, 'PowertrainCAN')
        self.assertEqual(chassis.network, 'ChassisCAN')
        self.assertEqual(powertrain.encoding.factor, Decimal('1'))
        self.assertEqual(chassis.encoding.factor, Decimal('0.01'))

    def test_network_unique_names_stay_unqualified(self):
        catalog = self.catalog(POWERTRAIN, CHASSIS)
        self.assertEqual(catalog.find('PowertrainOnly').network, 'PowertrainCAN')
        self.assertEqual(catalog.find('ChassisOnly').network, 'ChassisCAN')

    def test_single_network_uses_plain_adapter_addresses(self):
        """A one-network project addresses the bench exactly as before."""
        catalog = self.catalog(POWERTRAIN)
        self.assertEqual(catalog.adapter_address(catalog.find('VehicleSpeed')),
                         'VehicleSpeed')

    def test_same_name_in_different_technologies_stays_separate(self):
        catalog = self.catalog(POWERTRAIN, BODY_LIN)
        can_speed = catalog.find('VehicleSpeed', technology=Technology.CAN)
        lin_speed = catalog.find('VehicleSpeed', technology=Technology.LIN)
        self.assertEqual(can_speed.network, 'PowertrainCAN')
        self.assertEqual(lin_speed.network, 'BodyLIN')


class TestStableAdapterAddressing(CommFixture):
    """Adding a second network must never change an existing adapter address.

    The address a resource is written to on the bench follows from its own
    description and that description's naming policy -- never from what else happens
    to be loaded. A second network can therefore only leave addresses untouched or
    fail loudly with a collision.
    """

    def addresses(self, *descriptions):
        catalog = self.catalog(*descriptions)
        return {resource.qualified_name: catalog.adapter_address(resource)
                for resource in catalog.resources}

    def test_adding_a_second_network_leaves_addresses_untouched(self):
        before = self.addresses(POWERTRAIN)
        after = self.addresses(POWERTRAIN, CHASSIS)
        for reference, address in before.items():
            with self.subTest(resource=reference):
                self.assertEqual(after[reference], address,
                                 'adding a network changed an existing address')

    def test_adding_lin_and_ethernet_leaves_can_addresses_untouched(self):
        before = self.addresses(POWERTRAIN)
        after = self.addresses(POWERTRAIN, BODY_LIN, BACKBONE)
        for reference, address in before.items():
            with self.subTest(resource=reference):
                self.assertEqual(after[reference], address)

    def test_compiled_calls_are_unchanged_by_a_second_network(self):
        """The decisive check: the generated bench call must not move."""
        command = 'CAN-Signal PowertrainCAN::VehicleSpeed auf 80 setzen'
        alone = self.arguments(self.registry_for(POWERTRAIN), command, test_id='TC_S1')
        together = self.arguments(self.registry_for(POWERTRAIN, CHASSIS, BODY_LIN),
                                  command, test_id='TC_S2')
        self.assertEqual(alone, together)
        self.assertEqual(alone['signal'], 'VehicleSpeed')

    def test_colliding_addresses_fail_loudly_instead_of_renaming(self):
        colliding = replace(CHASSIS, adapter_naming='local')
        with self.assertRaises(SpecError) as caught:
            self.catalog(POWERTRAIN, colliding)
        message = str(caught.exception)
        self.assertIn('Adapteradresse', message)
        self.assertIn('VehicleSpeed', message)
        self.assertIn('adapter_naming', message)

    def test_naming_policies_produce_stable_distinct_addresses(self):
        for policy, expected in (('local', 'VehicleSpeed'),
                                 ('prefixed', 'ChassisCAN_VehicleSpeed'),
                                 ('qualified', 'ChassisCAN::Chassis_01::VehicleSpeed')):
            with self.subTest(policy=policy):
                catalog = self.catalog(replace(CHASSIS, adapter_naming=policy))
                resource = catalog.find('ChassisCAN::VehicleSpeed')
                self.assertEqual(catalog.adapter_address(resource), expected)

    def test_explicit_adapter_name_overrides_the_policy(self):
        """The three levels stay separate: resource, project alias, adapter address."""
        configured = replace(CHASSIS, adapter_naming='prefixed',
                             adapter_names={'VehicleSpeed': 'XCP::Speed_kmh'})
        catalog = self.catalog(configured)
        resource = catalog.find('ChassisCAN::VehicleSpeed')
        self.assertEqual(resource.qualified_name, 'ChassisCAN::Chassis_01::VehicleSpeed')
        self.assertEqual(catalog.adapter_address(resource), 'XCP::Speed_kmh')

    def test_explicit_adapter_name_reaches_the_generated_call(self):
        configured = replace(CHASSIS, adapter_naming='prefixed',
                             adapter_names={'DoorContactStatus': 'bench_door_raw'})
        registry = build_operations_registry(catalog=self.catalog(configured))
        arguments = self.arguments(
            registry, 'CAN-Signal DoorContactStatus auf Geschlossen setzen',
            test_id='TC_ADDR')
        self.assertEqual(arguments['signal'], 'bench_door_raw')
        # The value is still resolved from the resource, not from the address.
        self.assertEqual(arguments['value'], Decimal('5'))

    def test_project_alias_is_a_specification_name_not_an_address(self):
        catalog = self.catalog(POWERTRAIN, aliases={'Fahrzeugtempo': 'PowertrainCAN::VehicleSpeed'})
        resource = catalog.find('Fahrzeugtempo')
        self.assertEqual(resource.qualified_name, 'PowertrainCAN::Drive_01::VehicleSpeed')
        self.assertEqual(catalog.adapter_address(resource), 'VehicleSpeed')


class TestAmbiguousReferences(CommFixture):
    """An ambiguous short reference is refused, with the alternatives named."""

    def test_ambiguous_short_reference_is_rejected(self):
        catalog = self.catalog(POWERTRAIN, CHASSIS)
        with self.assertRaises(SpecError) as caught:
            catalog.find('VehicleSpeed')
        message = str(caught.exception)
        self.assertIn('mehrdeutig', message)
        self.assertIn('PowertrainCAN::Drive_01::VehicleSpeed', message)
        self.assertIn('ChassisCAN::Chassis_01::VehicleSpeed', message)

    def test_ambiguous_reference_is_rejected_while_compiling(self):
        registry = self.registry_for(POWERTRAIN, CHASSIS)
        with self.assertRaises(SpecError) as caught:
            self.arguments(registry, 'CAN-Signal VehicleSpeed auf 80 setzen')
        self.assertIn('mehrdeutig', str(caught.exception))

    def test_qualified_reference_compiles(self):
        registry = self.registry_for(POWERTRAIN, CHASSIS)
        self.assertEqual(
            self.arguments(registry, 'CAN-Signal PowertrainCAN::VehicleSpeed auf 80 setzen'),
            {'signal': 'VehicleSpeed', 'value': Decimal('80')})

    def test_alias_resolves_an_ambiguous_name(self):
        registry = build_operations_registry(catalog=self.catalog(
            POWERTRAIN, CHASSIS, aliases={'Tempo': 'ChassisCAN::VehicleSpeed'}))
        self.assertEqual(
            self.arguments(registry, 'CAN-Signal Tempo auf 80 setzen'),
            {'signal': 'ChassisCAN_VehicleSpeed', 'value': Decimal('80')})

    def test_alias_to_an_unknown_resource_is_rejected(self):
        with self.assertRaises(SpecError) as caught:
            self.catalog(POWERTRAIN, aliases={'Tempo': 'Nirgendwo::Signal'})
        self.assertIn('Tempo', str(caught.exception))

    def test_alias_to_an_ambiguous_target_is_rejected(self):
        with self.assertRaises(SpecError) as caught:
            self.catalog(POWERTRAIN, CHASSIS, aliases={'Tempo': 'VehicleSpeed'})
        self.assertIn('mehrdeutig', str(caught.exception))

    def test_unknown_reference_names_near_matches(self):
        catalog = self.catalog(POWERTRAIN)
        with self.assertRaises(SpecError) as caught:
            catalog.find('ChassisCAN::VehicleSpeed')
        self.assertIn('PowertrainCAN::Drive_01::VehicleSpeed', str(caught.exception))


class TestResourceSpecificEnums(CommFixture):
    """Enum values are resolved per resource, not per name."""

    def test_same_state_name_differs_per_network(self):
        registry = self.registry_for(POWERTRAIN, CHASSIS)
        powertrain = self.arguments(
            registry, 'CAN-Signal PowertrainCAN::DoorContactStatus auf Geschlossen setzen',
            test_id='TC_P')
        chassis = self.arguments(
            registry, 'CAN-Signal ChassisCAN::DoorContactStatus auf Geschlossen setzen',
            test_id='TC_C')
        self.assertEqual(powertrain['value'], Decimal('0'))
        self.assertEqual(chassis['value'], Decimal('5'))

    def test_same_state_name_differs_across_technologies(self):
        registry = self.registry_for(POWERTRAIN, BODY_LIN)
        can = self.arguments(registry,
                             'CAN-Signal DoorContactStatus auf Offen setzen', test_id='TC_CAN')
        lin = self.arguments(registry,
                             'LIN-Signal DoorState auf Offen setzen', test_id='TC_LIN')
        self.assertEqual(can['value'], Decimal('1'))
        self.assertEqual(lin['value'], Decimal('1'))
        self.assertEqual(can['signal'], 'DoorContactStatus')
        self.assertEqual(lin['signal'], 'DoorState')

    def test_state_of_another_resource_is_rejected(self):
        registry = self.registry_for(POWERTRAIN, BODY_LIN)
        with self.assertRaises(SpecError) as caught:
            self.arguments(registry, 'CAN-Signal VehicleSpeed auf Geschlossen setzen')
        self.assertIn('Geschlossen', str(caught.exception))
        self.assertIn('nicht gültig', str(caught.exception))


class TestObjectKinds(CommFixture):
    """An Ethernet service is never usable as a CAN signal."""

    def test_service_method_cannot_be_used_as_a_can_signal(self):
        registry = self.registry_for(POWERTRAIN, BACKBONE)
        with self.assertRaises(SpecError) as caught:
            self.arguments(registry, 'CAN-Signal OpenDoor auf 1 setzen')
        message = str(caught.exception)
        self.assertIn('OpenDoor', message)

    def test_can_signal_cannot_be_called_as_a_method(self):
        registry = self.registry_for(POWERTRAIN, BACKBONE)
        with self.assertRaises(SpecError) as caught:
            self.arguments(registry, 'Service-Methode VehicleSpeed aufrufen')
        self.assertIn('VehicleSpeed', str(caught.exception))

    def test_schedule_is_not_a_frame(self):
        registry = self.registry_for(BODY_LIN)
        self.assertEqual(self.arguments(registry, 'LIN-Schedule NormalTable aktivieren'),
                         {'schedule': 'NormalTable'})
        with self.assertRaises(SpecError):
            self.arguments(registry, 'LIN-Schedule DoorFrame aktivieren', test_id='TC_F')

    def test_kinds_are_distinguished_in_the_catalog(self):
        catalog = self.catalog(BACKBONE)
        kinds = {r.kind for r in catalog.resources}
        self.assertEqual(kinds, {ObjectKind.SERVICE, ObjectKind.METHOD,
                                 ObjectKind.EVENT, ObjectKind.FIELD})


class TestPhysicalVersusRaw(CommFixture):
    """Scaling is applied exactly once, and only where the operation says so."""

    def test_physical_value_is_taken_as_written(self):
        registry = self.registry_for(POWERTRAIN)
        self.assertEqual(
            self.arguments(registry, 'CAN-Signal PowertrainOnly auf 12 V setzen')['value'],
            Decimal('12'))

    def test_raw_value_is_taken_as_written(self):
        registry = self.registry_for(POWERTRAIN)
        self.assertEqual(
            self.arguments(registry, 'CAN-Signal PowertrainOnly auf Rohwert 120 setzen')['value'],
            Decimal('120'))

    def test_encoding_converts_between_the_two_exactly_once(self):
        catalog = self.catalog(POWERTRAIN)
        encoding = catalog.find('PowertrainOnly').encoding
        self.assertEqual(encoding.factor, Decimal('0.1'))
        self.assertEqual(encoding.raw_to_physical(Decimal('120')), Decimal('12.0'))
        self.assertEqual(encoding.physical_to_raw(Decimal('12')), Decimal('120'))

    def test_offset_is_applied_once(self):
        """BodyLIN::MirrorPosition uses factor 0.5 and offset -10."""
        catalog = self.catalog(BODY_LIN)
        encoding = catalog.find('BodyLIN::MirrorPosition').encoding
        self.assertEqual(encoding.factor, Decimal('0.5'))
        self.assertEqual(encoding.offset, Decimal('-10'))
        self.assertEqual(encoding.raw_to_physical(Decimal('100')), Decimal('40.0'))
        self.assertEqual(encoding.physical_to_raw(Decimal('40')), Decimal('100'))

    def test_symbolic_state_is_scaled_for_physical_operations(self):
        """A state is declared raw; a PHYSICAL operation scales it exactly once."""
        catalog = self.catalog(BODY_LIN)
        door = catalog.find('BodyLIN::DoorState')
        self.assertEqual(door.encoding.state_raw('Offen'), Decimal('1'))
        # DoorState is unscaled, so raw and physical coincide: no double scaling.
        self.assertEqual(door.encoding.state_physical('Offen'), Decimal('1'))

    def test_raw_and_physical_operations_are_separate_contracts(self):
        physical = REGISTRY['set_can_signal'].parameter('value').type
        raw = REGISTRY['set_can_signal_raw'].parameter('value').type
        self.assertEqual(physical.semantics, 'physical')
        self.assertEqual(raw.semantics, 'raw')


class TestProjectIsolation(CommFixture):
    """Switching projects leaves no resources of the previous one behind."""

    def test_two_registries_do_not_share_resources(self):
        powertrain_registry = self.registry_for(POWERTRAIN)
        chassis_registry = self.registry_for(CHASSIS)

        powertrain_value = self.arguments(
            powertrain_registry, 'CAN-Signal DoorContactStatus auf Geschlossen setzen',
            test_id='TC_A')['value']
        chassis_value = self.arguments(
            chassis_registry, 'CAN-Signal DoorContactStatus auf Geschlossen setzen',
            test_id='TC_B')['value']
        powertrain_again = self.arguments(
            powertrain_registry, 'CAN-Signal DoorContactStatus auf Geschlossen setzen',
            test_id='TC_A2')['value']

        self.assertEqual(powertrain_value, Decimal('0'))
        self.assertEqual(chassis_value, Decimal('5'))
        self.assertEqual(powertrain_again, Decimal('0'))

    def test_resources_of_the_other_project_are_unknown(self):
        registry = self.registry_for(CHASSIS)
        with self.assertRaises(SpecError) as caught:
            self.arguments(registry, 'CAN-Signal PowertrainOnly auf 1 setzen')
        self.assertIn('PowertrainOnly', str(caught.exception))

    def test_importing_the_registry_adopts_no_project(self):
        self.assertFalse(REGISTRY['set_can_signal'].parameter('signal').type.catalog.configured)
        self.registry_for(POWERTRAIN, CHASSIS)
        self.assertFalse(REGISTRY['set_can_signal'].parameter('signal').type.catalog.configured)


class TestBenchCapabilities(CommFixture):
    """Missing bench capabilities are detected before execution."""

    def bench(self, cls=VectorDummyBench):
        return cls(load_config(BENCH_CONFIG, self.profile))

    def test_contracts_declare_their_capabilities(self):
        self.assertEqual(REGISTRY['set_can_signal'].capabilities, frozenset({'write_signal'}))
        self.assertEqual(REGISTRY['expect_can_signal'].capabilities, frozenset({'read_signal'}))
        self.assertEqual(REGISTRY['set_lin_schedule'].capabilities,
                         frozenset({'set_lin_schedule'}))
        self.assertEqual(REGISTRY['call_service_method'].capabilities,
                         frozenset({'call_method'}))

    def test_full_bench_offers_every_capability(self):
        offered = bench_capabilities(self.bench())
        for name in ('read_signal', 'write_signal', 'send_frame', 'set_lin_schedule',
                     'call_method', 'subscribe_event'):
            self.assertIn(name, offered)

    def test_can_only_bench_declares_a_reduced_set(self):
        offered = bench_capabilities(self.bench(CanOnlyDummyBench))
        self.assertEqual(offered, frozenset({'read_signal', 'write_signal'}))

    def test_missing_capability_is_detected_before_execution(self):
        registry = self.registry_for(BODY_LIN)
        maps = self.mappings(registry)
        cases = compile_cases(parse_text_spec(
            spec('TC_SCHED', 'LIN-Schedule NormalTable aktivieren')),
            maps, self.profile, 'sched.md')

        required = required_capabilities(cases)
        self.assertEqual(required['TC_SCHED'], frozenset({'set_lin_schedule'}))

        report = capability_report(cases, self.bench(CanOnlyDummyBench))
        self.assertEqual(report['TC_SCHED']['missing'], ('set_lin_schedule',))

        with self.assertRaises(SpecError) as caught:
            check_bench_capabilities(required, self.bench(CanOnlyDummyBench))
        self.assertIn('set_lin_schedule', str(caught.exception))

    def test_capable_bench_passes_the_check(self):
        registry = self.registry_for(BODY_LIN)
        maps = self.mappings(registry)
        cases = compile_cases(parse_text_spec(
            spec('TC_SCHED2', 'LIN-Schedule NormalTable aktivieren')),
            maps, self.profile, 'sched2.md')
        check_bench_capabilities(required_capabilities(cases), self.bench())

    def test_generated_module_declares_its_requirements(self):
        registry = self.registry_for(BODY_LIN)
        maps = self.mappings(registry)
        cases = compile_cases(parse_text_spec(
            spec('TC_REQ', 'LIN-Schedule NormalTable aktivieren')),
            maps, self.profile, 'req.md')
        source = render_python(cases, registry, 'tcg.runtime.runner')
        self.assertIn('REQUIRED_CAPABILITIES', source)
        namespace = {'__name__': 'generated'}
        exec(compile(source, 'generated.py', 'exec'), namespace)
        self.assertEqual(namespace['REQUIRED_CAPABILITIES']['TC_REQ'],
                         ('set_lin_schedule',))


class TestUnsupportedImports(CommFixture):
    """Unsupported constructs produce a comprehensible error, never silence."""

    def write(self, name, text):
        directory = tempfile.mkdtemp()
        path = Path(directory) / name
        path.write_text(text, encoding='utf-8')
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_arxml_without_service_interfaces_is_refused(self):
        path = self.write('system.arxml',
                          '<?xml version="1.0"?><AUTOSAR xmlns="http://autosar.org/schema/r4.0">'
                          '<AR-PACKAGES><AR-PACKAGE><SHORT-NAME>Sys</SHORT-NAME>'
                          '<ELEMENTS><CAN-CLUSTER><SHORT-NAME>CAN1</SHORT-NAME></CAN-CLUSTER>'
                          '</ELEMENTS></AR-PACKAGE></AR-PACKAGES></AUTOSAR>')
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        message = str(caught.exception)
        self.assertIn('SERVICE-INTERFACE', message)
        self.assertIn('nicht unterstützt', message)

    def test_arxml_unsupported_interface_child_is_named(self):
        path = self.write('iface.arxml',
                          '<?xml version="1.0"?><AUTOSAR xmlns="http://autosar.org/schema/r4.0">'
                          '<SERVICE-INTERFACE><SHORT-NAME>S</SHORT-NAME>'
                          '<TRIGGERS><TRIGGER><SHORT-NAME>T</SHORT-NAME></TRIGGER></TRIGGERS>'
                          '</SERVICE-INTERFACE></AUTOSAR>')
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        self.assertIn('TRIGGERS', str(caught.exception))

    def test_arxml_rejects_entity_declarations(self):
        path = self.write('evil.arxml',
                          '<?xml version="1.0"?><!DOCTYPE AUTOSAR [<!ENTITY a "b">]>'
                          '<AUTOSAR></AUTOSAR>')
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        self.assertIn('ENTITY', str(caught.exception))

    def test_arxml_wrong_root_element_is_refused(self):
        path = self.write('other.arxml', '<?xml version="1.0"?><NOTAUTOSAR/>')
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        self.assertIn('AUTOSAR', str(caught.exception))

    def test_ldf_missing_encoding_type_is_refused(self):
        path = self.write('broken.ldf', """LIN_description_file;
Signals { S1: 8, 0, Slave, Master; }
Signal_representation { MissingEncoding: S1; }
""")
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        message = str(caught.exception)
        self.assertIn('MissingEncoding', message)
        self.assertIn('S1', message)

    def test_ldf_unsupported_encoding_entry_is_refused(self):
        path = self.write('bcd.ldf', """LIN_description_file;
Signals { S1: 8, 0, Slave, Master; }
Signal_encoding_types { Enc { bcd_value; } }
Signal_representation { Enc: S1; }
""")
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        self.assertIn('bcd_value', str(caught.exception))

    def test_non_ldf_file_is_refused(self):
        path = self.write('not.ldf', 'this is not a LIN description')
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        self.assertIn('LIN_description_file', str(caught.exception))

    def test_unknown_format_is_refused(self):
        path = self.write('thing.bin', 'x')
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(path), network='X')])
        self.assertIn('format', str(caught.exception).lower())

    def test_missing_file_is_refused(self):
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path='/nirgends/da.dbc', network='X')])
        self.assertIn('da.dbc', str(caught.exception))

    def test_unknown_technology_is_refused(self):
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(FIXTURES / 'powertrain_can.json'),
                                            network='X', technology='flexray')])
        self.assertIn('flexray', str(caught.exception))

    def test_duplicate_identity_across_descriptions_is_refused(self):
        same = DescriptionConfig(path=str(FIXTURES / 'powertrain_can.json'),
                                 network='PowertrainCAN', technology='can')
        with self.assertRaises(SpecError) as caught:
            load_catalog([same, same])
        self.assertIn('doppelt', str(caught.exception))


class TestExistingCanProjectsKeepWorking(CommFixture):
    """The shipped CAN project and its single-database configuration still work."""

    def test_can_database_setting_is_migrated(self):
        descriptions = migrate_can_database('inputs/can_signals.json')
        self.assertEqual(len(descriptions), 1)
        self.assertEqual(descriptions[0].format, 'can_json')
        self.assertEqual(descriptions[0].technology, 'can')

    def test_shipped_demo_database_loads_through_the_general_loader(self):
        catalog = load_catalog(migrate_can_database(str(ROOT / 'inputs' / 'can_signals.json')))
        self.assertEqual(catalog.networks(), ('Powertrain_BMS_CAN',))
        self.assertEqual(catalog.find('DoorContactStatus').encoding.state_raw('Geschlossen'),
                         Decimal('0'))
        self.assertEqual(catalog.find('InterlockStatus').encoding.state_raw('Geschlossen'),
                         Decimal('1'))

    def test_shipped_dbc_loads_through_the_dbc_importer(self):
        catalog = load_catalog([DescriptionConfig(
            path=str(ROOT / 'tools' / 'powertrain_bms.dbc'), network='PowertrainDBC')])
        self.assertGreater(len(catalog.resources), 20)
        self.assertEqual(catalog.find('PowertrainDBC::DoorContactStatus')
                         .encoding.state_raw('Geschlossen'), Decimal('0'))

    def test_demo_specifications_still_compile_and_run(self):
        catalog = load_catalog(migrate_can_database(str(ROOT / 'inputs' / 'can_signals.json')))
        registry = build_operations_registry(catalog=catalog)
        maps = load_mappings(
            parse_mapping_document((ROOT / 'inputs' / 'operation_mapping.toml')
                                   .read_text(encoding='utf-8')), registry)
        document = (ROOT / 'inputs' / 'can' / 'tc_06_can_signal_transmission.md')
        from tcg.adapters.inbound.text_parser import read_text_spec
        cases = compile_cases(read_text_spec(document), maps, self.profile, document.name)
        source = render_python(cases, registry, 'tcg.runtime.runner')
        namespace = {'__name__': 'generated'}
        exec(compile(source, 'generated.py', 'exec'), namespace)
        bench = VectorDummyBench(load_config(ROOT / 'inputs' / 'demo_bench.json', self.profile))
        for test_id, runner in namespace['RUNNERS'].items():
            self.assertEqual(runner(bench).result, 'PASS', test_id)


class TestLinExecution(CommFixture):
    """Step C: a LIN specification compiles and runs on the simulation bench.

    This is simulation evidence only. It does not demonstrate a real LIN bus, a real
    master node, or any hardware interface.
    """

    def test_lin_schedule_and_signal_round_trip(self):
        registry = self.registry_for(BODY_LIN)
        maps = self.mappings(registry)
        document = spec(
            'TC_LIN',
            'LIN-Schedule NormalTable aktivieren',
            'LIN-Signal DoorState auf Offen setzen',
            expectations=('LIN-Schedule ist NormalTable',),
        )
        cases = compile_cases(parse_text_spec(document), maps, self.profile, 'lin.md')
        source = render_python(cases, registry, 'tcg.runtime.runner')
        namespace = {'__name__': 'generated'}
        exec(compile(source, 'generated.py', 'exec'), namespace)

        bench = VectorDummyBench(load_config(BENCH_CONFIG, self.profile))
        result = namespace['RUNNERS']['TC_LIN'](bench)

        self.assertEqual(result.result, 'PASS')
        # PASS alone is not proof: check the state the bench actually holds.
        self.assertEqual(bench.lin_schedule, 'NormalTable')
        self.assertEqual(bench.can_signals['DoorState'], Decimal('1'))

    def test_lin_raw_value_differs_from_physical(self):
        registry = self.registry_for(BODY_LIN)
        physical = self.arguments(registry, 'LIN-Signal MirrorPosition auf 40 setzen',
                                  test_id='TC_MP')
        raw = self.arguments(registry, 'LIN-Signal MirrorPosition auf Rohwert 100 setzen',
                             test_id='TC_MR')
        self.assertEqual(physical['value'], Decimal('40'))
        self.assertEqual(raw['value'], Decimal('100'))


class TestEthernetExecution(CommFixture):
    """Step E: service-oriented Ethernet operations on the simulation bench.

    Simulation evidence only; no SOME/IP stack and no real network are involved.
    """

    def test_service_call_and_event_subscription(self):
        registry = self.registry_for(BACKBONE)
        maps = self.mappings(registry)
        document = spec(
            'TC_ETH',
            'Service-Methode OpenDoor aufrufen',
            'Service-Event DoorStateChanged abonnieren',
            expectations=('Service-Event DoorStateChanged wurde empfangen',),
        )
        cases = compile_cases(parse_text_spec(document), maps, self.profile, 'eth.md')
        source = render_python(cases, registry, 'tcg.runtime.runner')
        namespace = {'__name__': 'generated'}
        exec(compile(source, 'generated.py', 'exec'), namespace)

        bench = VectorDummyBench(load_config(BENCH_CONFIG, self.profile))
        result = namespace['RUNNERS']['TC_ETH'](bench)

        self.assertEqual(result.result, 'PASS')
        self.assertEqual(bench.method_calls, [('OpenDoor', '')])
        self.assertIn('DoorStateChanged', bench.subscribed_events)

    def test_someip_ids_are_attributes_not_assumptions(self):
        """A service interface carries SOME/IP ids only where a deployment exists."""
        catalog = self.catalog(BACKBONE)
        with_id = catalog.find('BackboneEth::DoorService::OpenDoor')
        without_id = catalog.find('BackboneEth::DoorService::GetDoorState')
        self.assertEqual(with_id.attributes['id'], '1')
        self.assertIsNone(without_id.attributes['id'])
        self.assertTrue(catalog.find('BackboneEth::DoorService').attributes['someip'])


class TestShippedDemoDescriptions(CommFixture):
    """The three description files in tools/ form one usable multi-bus project."""

    DEMO = (
        DescriptionConfig(path=str(ROOT / 'tools' / 'powertrain_bms.dbc'),
                          network='PowertrainCAN'),
        DescriptionConfig(path=str(ROOT / 'tools' / 'body_comfort.ldf'),
                          network='BodyComfortLIN'),
        DescriptionConfig(path=str(ROOT / 'tools' / 'vehicle_services.arxml'),
                          network='BackboneEth'),
    )

    def test_all_three_load_into_one_catalog(self):
        catalog = self.catalog(*self.DEMO)
        self.assertEqual(catalog.networks(),
                         ('BackboneEth', 'BodyComfortLIN', 'PowertrainCAN'))
        self.assertEqual(sorted(catalog.technologies()), ['can', 'ethernet', 'lin'])

    def test_states_resolve_per_technology(self):
        registry = self.registry_for(*self.DEMO)
        can = self.arguments(registry, 'CAN-Signal BMSState auf DriveReady setzen',
                             test_id='TC_D1')
        lin = self.arguments(registry,
                             'LIN-Signal DoorContactFL auf Geschlossen setzen',
                             test_id='TC_D2')
        self.assertEqual(can['value'], Decimal('3'))
        self.assertEqual(lin['value'], Decimal('0'))

    def test_quoted_state_with_a_space(self):
        registry = self.registry_for(*self.DEMO)
        self.assertEqual(
            self.arguments(registry, 'LIN-Signal SeatHeaterLevel auf "Stufe 2" setzen',
                           test_id='TC_D3')['value'],
            Decimal('2'))

    def test_lin_scaling_from_the_demo_description(self):
        catalog = self.catalog(*self.DEMO)
        mirror = catalog.find('BodyComfortLIN::MirrorPositionH')
        self.assertEqual(mirror.encoding.factor, Decimal('0.5'))
        self.assertEqual(mirror.encoding.offset, Decimal('-64'))
        self.assertEqual(mirror.encoding.raw_to_physical(Decimal('128')), Decimal('0.0'))

    def test_ethernet_service_without_someip_deployment(self):
        catalog = self.catalog(*self.DEMO)
        diagnostic = catalog.find('BackboneEth::DiagnosticService')
        self.assertFalse(diagnostic.attributes['someip'])
        self.assertIsNone(diagnostic.attributes['service_id'])

    def test_shipped_multibus_mapping_covers_the_demo_operations(self):
        registry = self.registry_for(*self.DEMO)
        toml_text = ((ROOT / 'inputs' / 'operation_mapping.toml').read_text(encoding='utf-8')
                     + (ROOT / 'inputs' / 'multibus_mapping.toml').read_text(encoding='utf-8'))
        mappings = load_mappings(parse_mapping_document(toml_text), registry)
        document = spec(
            'TC_DEMO',
            'CAN-Signal BMSState auf DriveReady setzen',
            'LIN-Schedule NormalTable aktivieren',
            'Service-Methode LockAllDoors aufrufen',
        )
        cases = compile_cases(parse_text_spec(document), mappings, self.profile, 'demo.md')
        source = render_python(cases, registry, 'tcg.runtime.runner')
        self.assertIn("value=Decimal('3')", source)
        self.assertIn("schedule='NormalTable'", source)
        self.assertIn("method='LockAllDoors'", source)


class TestSimulationHonesty(CommFixture):
    """Simulation results must be identifiable as simulation."""

    def test_dummy_benches_mark_themselves_as_simulation(self):
        for cls in (VectorDummyBench, CanOnlyDummyBench):
            bench = cls(load_config(BENCH_CONFIG, self.profile))
            with self.subTest(bench=cls.__name__):
                self.assertTrue(getattr(bench, 'is_simulation', False))
                self.assertIn('Simulation', bench.BENCH_NAME)


if __name__ == '__main__':
    unittest.main()
