"""The JSON descriptions in `inputs/` are first-class, self-identifying descriptions.

`tools/*_to_json.py` writes one JSON per technology, and all three share the `.json`
extension. A project must be able to reference them directly, and the loader must
never guess the wrong technology: reading a LIN description as CAN would silently
produce plausible-looking but wrong signals.
"""

import json
from pathlib import Path
import tempfile
import unittest

from tcg.comm.catalog import DescriptionConfig, load_catalog
from tcg.comm.importers import format_for, sniff_json_format
from tcg.comm.model import ObjectKind, Technology
from tcg.core.model import SpecError

ROOT = Path(__file__).resolve().parents[2]
INPUTS = ROOT / 'inputs'
TOOLS = ROOT / 'tools'

PAIRS = (
    ('tools/body_comfort.ldf', 'inputs/lin_signals.json', 'BodyComfortLIN'),
    ('tools/vehicle_services.arxml', 'inputs/eth_services.json', 'BackboneEth'),
)


def snapshot(path, network):
    catalog = load_catalog([DescriptionConfig(path=str(ROOT / path), network=network)])
    return {
        (resource.kind.value, resource.name, resource.container): (
            resource.technology.value,
            getattr(resource.encoding, 'declared_states', ()),
            str(getattr(resource.encoding, 'factor', '')),
            str(getattr(resource.encoding, 'offset', '')),
            getattr(resource.encoding, 'unit', None),
        )
        for resource in catalog.resources
    }


class ShippedJsonDescriptionsTests(unittest.TestCase):
    """The files the documentation points at exist and are usable."""

    def test_all_three_json_descriptions_are_shipped(self):
        for name in ('can_signals.json', 'lin_signals.json', 'eth_services.json'):
            with self.subTest(file=name):
                self.assertTrue((INPUTS / name).is_file(),
                                f'inputs/{name} is missing')

    def test_each_description_declares_its_protocol(self):
        expected = {'can_signals.json': 'CAN', 'lin_signals.json': 'LIN',
                    'eth_services.json': 'Ethernet'}
        for name, protocol in expected.items():
            with self.subTest(file=name):
                data = json.loads((INPUTS / name).read_text(encoding='utf-8'))
                self.assertEqual(data.get('protocol'), protocol)

    def test_json_matches_the_description_it_was_generated_from(self):
        """The converter output must describe exactly the same network."""
        for original, generated, network in PAIRS:
            with self.subTest(description=generated):
                self.assertEqual(snapshot(generated, network),
                                 snapshot(original, network))

    def test_lin_json_yields_lin_resources(self):
        catalog = load_catalog([DescriptionConfig(
            path=str(INPUTS / 'lin_signals.json'), network='BodyComfortLIN')])
        self.assertEqual(catalog.technologies(), ('lin',))
        kinds = {resource.kind for resource in catalog.resources}
        self.assertEqual(kinds, {ObjectKind.SIGNAL, ObjectKind.FRAME,
                                 ObjectKind.SCHEDULE})
        door = catalog.find('BodyComfortLIN::DoorContactFL')
        self.assertEqual(door.technology, Technology.LIN)
        self.assertEqual(door.encoding.state_raw('Geschlossen'), 0)
        self.assertEqual(door.container, 'LIN_Door_01')

    def test_service_json_yields_ethernet_resources(self):
        catalog = load_catalog([DescriptionConfig(
            path=str(INPUTS / 'eth_services.json'), network='BackboneEth')])
        self.assertEqual(catalog.technologies(), ('ethernet',))
        kinds = {resource.kind for resource in catalog.resources}
        self.assertEqual(kinds, {ObjectKind.SERVICE, ObjectKind.METHOD,
                                 ObjectKind.EVENT, ObjectKind.FIELD})
        method = catalog.find('BackboneEth::DoorService::LockAllDoors')
        self.assertEqual(method.attributes['id'], '1')
        self.assertIsNone(method.encoding, 'a method is not a numeric signal')

    def test_can_json_still_yields_can_resources(self):
        catalog = load_catalog([DescriptionConfig(
            path=str(INPUTS / 'can_signals.json'), network='PowertrainCAN')])
        self.assertEqual(catalog.technologies(), ('can',))
        self.assertEqual(
            catalog.find('PowertrainCAN::DoorContactStatus')
            .encoding.state_raw('Geschlossen'), 0)

    def test_all_three_load_side_by_side(self):
        catalog = load_catalog([
            DescriptionConfig(path=str(INPUTS / 'can_signals.json'),
                              network='PowertrainCAN'),
            DescriptionConfig(path=str(INPUTS / 'lin_signals.json'),
                              network='BodyComfortLIN'),
            DescriptionConfig(path=str(INPUTS / 'eth_services.json'),
                              network='BackboneEth'),
        ])
        self.assertEqual(sorted(catalog.technologies()), ['can', 'ethernet', 'lin'])
        self.assertEqual(len(catalog.networks()), 3)


class JsonFormatDetectionTests(unittest.TestCase):
    """A `.json` description is never assumed to be CAN."""

    def write(self, payload):
        directory = tempfile.mkdtemp()
        path = Path(directory) / 'description.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        self.addCleanup(lambda: path.unlink(missing_ok=True))
        return path

    def test_protocol_marker_decides(self):
        for protocol, expected in (('CAN', 'can_json'), ('LIN', 'lin_json'),
                                   ('Ethernet', 'service_json')):
            with self.subTest(protocol=protocol):
                path = self.write({'protocol': protocol, 'signals': {},
                                   'services': {}})
                self.assertEqual(sniff_json_format(path), expected)

    def test_shipped_files_are_detected(self):
        expected = {'can_signals.json': 'can_json',
                    'lin_signals.json': 'lin_json',
                    'eth_services.json': 'service_json'}
        for name, importer in expected.items():
            with self.subTest(file=name):
                self.assertEqual(format_for(INPUTS / name), importer)

    def test_structure_decides_when_no_marker_is_present(self):
        """CAN databases that predate the marker still work."""
        self.assertEqual(
            sniff_json_format(self.write({'messages': {}, 'signals': {}})),
            'can_json')
        self.assertEqual(
            sniff_json_format(self.write({'schedules': {}, 'signals': {}})),
            'lin_json')
        self.assertEqual(sniff_json_format(self.write({'services': {}})),
                         'service_json')

    def test_unrecognisable_json_is_refused(self):
        path = self.write({'something': 'else'})
        with self.assertRaises(SpecError) as caught:
            format_for(path)
        message = str(caught.exception)
        self.assertIn('protocol', message)
        self.assertIn('lin_json', message)

    def test_a_lin_description_is_never_read_as_can(self):
        """The regression this guards: LIN signals silently becoming CAN signals."""
        catalog = load_catalog([DescriptionConfig(
            path=str(INPUTS / 'lin_signals.json'), network='X')])
        self.assertNotIn('can', catalog.technologies())
        for resource in catalog.resources:
            with self.subTest(resource=resource.name):
                self.assertEqual(resource.technology, Technology.LIN)

    def test_an_explicit_format_still_wins(self):
        self.assertEqual(format_for(INPUTS / 'lin_signals.json', 'can_json'),
                         'can_json')

    def test_explicitly_wrong_format_fails_visibly(self):
        with self.assertRaises(SpecError) as caught:
            load_catalog([DescriptionConfig(path=str(INPUTS / 'eth_services.json'),
                                            network='X', format='lin_json')])
        self.assertIn('signals', str(caught.exception))


if __name__ == '__main__':
    unittest.main()
