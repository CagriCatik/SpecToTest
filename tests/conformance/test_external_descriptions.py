"""Conformance tests against independent implementations and foreign files.

These are deliberately *not* round-trip tests. A round trip through one's own
importer and exporter proves only internal consistency: if both share a wrong
assumption, the trip still succeeds. What is checked here instead:

1. **Foreign input** -- description files written by other people and tools
   (`tests/fixtures/comm/external/`) are imported and compared field by field with
   an independent reference implementation.
2. **Foreign acceptance** -- files this project *exports* are handed to that
   independent implementation, which must accept them.

The reference implementations are development dependencies only (see
`requirements-dev.txt`); the product itself needs none of them. When they are not
installed, these tests skip rather than silently pass.
"""

from pathlib import Path
import tempfile
import unittest

from tcg.comm.importers import dbc as dbc_importer
from tcg.comm.importers import ldf as ldf_importer
from tcg.core.model import SpecError

ROOT = Path(__file__).resolve().parents[2]
EXTERNAL = ROOT / 'tests' / 'fixtures' / 'comm' / 'external'
OWN_LDF = ROOT / 'tools' / 'body_comfort.ldf'
OWN_DBC = ROOT / 'tools' / 'powertrain_bms.dbc'

try:
    import ldfparser
    from ldfparser.encoding import LogicalValue, PhysicalValue
    HAVE_LDFPARSER = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_LDFPARSER = False

try:
    import cantools
    HAVE_CANTOOLS = True
except ImportError:  # pragma: no cover - depends on the environment
    HAVE_CANTOOLS = False


def reference_signal_encoding(signal):
    """States and scaling of one signal, as the independent LDF parser sees them."""
    states, scaling = {}, None
    if signal.encoding_type is not None:
        for converter in signal.encoding_type.get_converters():
            if isinstance(converter, LogicalValue):
                states[converter.phy_value] = converter.info
            elif isinstance(converter, PhysicalValue):
                scaling = (float(converter.scale), float(converter.offset),
                           converter.unit or '')
    return states, scaling


def own_signal_encoding(resource):
    """The same information, as this project's importer sees it."""
    if resource.encoding is None:
        return {}, None
    states = {int(resource.encoding.state_raw(name)): name
              for name in resource.encoding.declared_states}
    scaling = (float(resource.encoding.factor), float(resource.encoding.offset),
               resource.encoding.unit or '')
    return states, scaling


@unittest.skipUnless(HAVE_LDFPARSER, 'ldfparser (dev dependency) is not installed')
class LdfForeignInputTests(unittest.TestCase):
    """Import LDF files written by other authors and tools."""

    #: Files whose constructs this importer deliberately refuses. Keeping them here
    #: documents the limit and fails the moment the refusal stops being deliberate.
    DELIBERATELY_UNSUPPORTED = {
        'lin_encoders.ldf': 'bcd_value',   # BCD/ASCII encodings are not modelled
    }

    def external_files(self):
        files = sorted(EXTERNAL.glob('*.ldf'))
        self.assertGreaterEqual(len(files), 10, 'conformance corpus is missing')
        return files

    def test_corpus_is_present_and_foreign(self):
        self.assertTrue((EXTERNAL / 'README.md').is_file())
        self.assertTrue((EXTERNAL / 'LICENSE.ldfparser').is_file())

    def test_every_foreign_file_is_imported_or_refused_on_purpose(self):
        for path in self.external_files():
            with self.subTest(file=path.name):
                try:
                    ldfparser.parse_ldf(str(path))
                except Exception:
                    self.skipTest(f'{path.name}: reference parser rejects it too')
                try:
                    ldf_importer.load(path, network='N')
                except SpecError as error:
                    expected = self.DELIBERATELY_UNSUPPORTED.get(path.name)
                    self.assertIsNotNone(
                        expected,
                        f'{path.name} failed unexpectedly: {error}')
                    self.assertIn(expected, str(error))

    def test_signals_match_the_reference_implementation(self):
        for path in self.external_files():
            if path.name in self.DELIBERATELY_UNSUPPORTED:
                continue
            try:
                reference = ldfparser.parse_ldf(str(path))
            except Exception:
                continue
            resources = {r.name: r for r in ldf_importer.load(path, network='N')}
            for signal in reference.signals:
                with self.subTest(file=path.name, signal=signal.name):
                    resource = resources.get(signal.name)
                    self.assertIsNotNone(resource, 'signal missing from the import')
                    self.assertEqual(int(resource.attributes['size']), signal.width)
                    reference_states, reference_scaling = reference_signal_encoding(signal)
                    own_states, own_scaling = own_signal_encoding(resource)
                    self.assertEqual(own_states, reference_states, 'symbolic states differ')
                    if reference_scaling is not None:
                        self.assertIsNotNone(own_scaling)
                        self.assertAlmostEqual(own_scaling[0], reference_scaling[0], places=9)
                        self.assertAlmostEqual(own_scaling[1], reference_scaling[1], places=9)
                        self.assertEqual(own_scaling[2], reference_scaling[2])

    def test_frames_match_the_reference_implementation(self):
        for path in self.external_files():
            if path.name in self.DELIBERATELY_UNSUPPORTED:
                continue
            try:
                reference = ldfparser.parse_ldf(str(path))
            except Exception:
                continue
            resources = {r.name: r for r in ldf_importer.load(path, network='N')}
            for frame in reference.frames:
                with self.subTest(file=path.name, frame=frame.name):
                    resource = resources.get(frame.name)
                    self.assertIsNotNone(resource, 'frame missing from the import')
                    self.assertEqual(int(resource.attributes['id']), frame.frame_id)

    def test_schedule_frame_entries_match_the_reference(self):
        """Only plain frame entries; configuration commands are modelled differently."""
        for path in self.external_files():
            if path.name in self.DELIBERATELY_UNSUPPORTED:
                continue
            try:
                reference = ldfparser.parse_ldf(str(path))
            except Exception:
                continue
            resources = {r.name: r for r in ldf_importer.load(path, network='N')}
            for table in reference.get_schedule_tables():
                with self.subTest(file=path.name, table=table.name):
                    resource = resources.get(table.name)
                    self.assertIsNotNone(resource, 'schedule table missing')
                    reference_frames = {entry.frame.name for entry in table.schedule
                                        if getattr(entry, 'frame', None) is not None}
                    own_frames = set(resource.attributes['frames'])
                    # Every frame the reference sees must be known to the importer.
                    self.assertTrue(
                        reference_frames <= own_frames | set(resources),
                        f'unknown frames: {reference_frames - own_frames}')

    def test_schedule_entries_never_dangle(self):
        """A schedule entry must always name a frame the catalog actually contains."""
        for path in self.external_files():
            if path.name in self.DELIBERATELY_UNSUPPORTED:
                continue
            try:
                resources = {r.name: r for r in ldf_importer.load(path, network='N')}
            except SpecError:
                continue
            for resource in resources.values():
                for frame_name in resource.attributes.get('frames', ()):
                    with self.subTest(file=path.name, frame=frame_name):
                        self.assertIn(frame_name, resources)


@unittest.skipUnless(HAVE_LDFPARSER, 'ldfparser (dev dependency) is not installed')
class LdfForeignAcceptanceTests(unittest.TestCase):
    """Files this project writes must be accepted by an independent LIN tool."""

    def test_shipped_demo_file_is_accepted(self):
        parsed = ldfparser.parse_ldf(str(OWN_LDF))
        self.assertEqual(len(parsed.frames), 6)
        self.assertEqual(len(parsed.slaves), 5)

    def test_exported_file_is_accepted(self):
        from tools.ldf_to_json import dict_to_ldf, ldf_to_dict

        data = ldf_to_dict(OWN_LDF.read_text(encoding='utf-8'), OWN_LDF.name)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'exported.ldf'
            path.write_text(dict_to_ldf(data), encoding='utf-8')
            parsed = ldfparser.parse_ldf(str(path))

        self.assertEqual({frame.name for frame in parsed.frames},
                         {'LIN_Door_01', 'LIN_Door_02', 'LIN_Mirror_01',
                          'LIN_Seat_01', 'LIN_Sensor_01', 'LIN_Master_01'})
        self.assertEqual(len(parsed.slaves), 5)

    def test_exported_file_keeps_scaling_and_states(self):
        from tools.ldf_to_json import dict_to_ldf, ldf_to_dict

        data = ldf_to_dict(OWN_LDF.read_text(encoding='utf-8'), OWN_LDF.name)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'exported.ldf'
            path.write_text(dict_to_ldf(data), encoding='utf-8')
            parsed = ldfparser.parse_ldf(str(path))

        mirror = parsed.get_signal('MirrorPositionH')
        states, scaling = reference_signal_encoding(mirror)
        self.assertEqual(scaling, (0.5, -64.0, 'deg'))

        door = parsed.get_signal('DoorContactFL')
        states, _ = reference_signal_encoding(door)
        self.assertEqual(states, {0: 'Geschlossen', 1: 'Offen', 2: 'Fehler'})


class ArxmlForeignInputTests(unittest.TestCase):
    """Real ARXML files must be refused comprehensibly, never crash or be invented.

    The vendored corpus consists of CAN system and ECU-extract descriptions (AUTOSAR
    3.1.2, 3.2.3, 4.2). **None of them contains a SERVICE-INTERFACE**, so they do not
    validate the service import path -- they validate that unsupported real-world
    input fails cleanly and says why.
    """

    def external_files(self):
        files = sorted(EXTERNAL.glob('*.arxml'))
        self.assertGreaterEqual(len(files), 4, 'ARXML corpus is missing')
        return files

    def test_corpus_contains_no_service_interfaces(self):
        """Guards the claim above: if this ever fails, the corpus changed."""
        for path in self.external_files():
            with self.subTest(file=path.name):
                text = path.read_text(encoding='utf-8', errors='replace')
                self.assertNotIn('<SERVICE-INTERFACE>', text)

    def test_unsupported_files_are_refused_with_an_explanation(self):
        from tcg.comm.importers import arxml as arxml_importer

        for path in self.external_files():
            with self.subTest(file=path.name):
                try:
                    arxml_importer.load(path, network='N')
                except SpecError as error:
                    message = str(error)
                    self.assertTrue(
                        'SERVICE-INTERFACE' in message or 'AUTOSAR' in message,
                        f'unhelpful refusal: {message}')
                    self.assertIn(path.name, message)
                except Exception as error:  # noqa: BLE001 - that is the point
                    self.fail(f'{path.name} crashed instead of being refused: '
                              f'{type(error).__name__}: {error}')
                else:
                    self.fail(f'{path.name} was imported although it declares no '
                              f'service interface')

    def test_refusal_names_the_detected_autosar_version(self):
        from tcg.comm.importers import arxml as arxml_importer

        expected = {'system-3.2.3.arxml': '3.x', 'system-4.2.arxml': '4.x',
                    'system-DAI-3.1.2.arxml': '3.x'}
        for name, version in expected.items():
            path = EXTERNAL / name
            if not path.is_file():
                continue
            with self.subTest(file=name):
                with self.assertRaises(SpecError) as caught:
                    arxml_importer.load(path, network='N')
                self.assertIn(version, str(caught.exception))


@unittest.skipUnless(HAVE_CANTOOLS, 'cantools (dev dependency) is not installed')
class DbcConformanceTests(unittest.TestCase):
    """The CAN importer is compared with an independent DBC implementation."""

    @classmethod
    def setUpClass(cls):
        cls.reference = cantools.database.load_file(str(OWN_DBC))
        cls.resources = {r.name: r for r in dbc_importer.load(OWN_DBC, network='N')}

    def test_every_message_is_imported(self):
        for message in self.reference.messages:
            with self.subTest(message=message.name):
                resource = self.resources.get(message.name)
                self.assertIsNotNone(resource)
                self.assertEqual(int(str(resource.attributes['id']), 0),
                                 message.frame_id)

    def test_every_signal_matches_scaling_unit_and_states(self):
        for message in self.reference.messages:
            for signal in message.signals:
                with self.subTest(signal=signal.name):
                    resource = self.resources.get(signal.name)
                    self.assertIsNotNone(resource, 'signal missing from the import')
                    self.assertEqual(resource.container, message.name)
                    encoding = resource.encoding
                    self.assertAlmostEqual(float(encoding.factor),
                                           float(signal.scale), places=9)
                    self.assertAlmostEqual(float(encoding.offset),
                                           float(signal.offset), places=9)
                    self.assertEqual(encoding.unit or '', signal.unit or '')
                    reference_states = {int(raw): str(name) for raw, name
                                        in (signal.choices or {}).items()}
                    own_states = {int(encoding.state_raw(name)): name
                                  for name in encoding.declared_states}
                    self.assertEqual(own_states, reference_states)

    def test_shipped_dbc_is_ascii_only(self):
        """DBC carries no encoding declaration, so tools disagree on non-ASCII bytes.

        The shipped demo file therefore stays ASCII, which removes the ambiguity.
        """
        raw = OWN_DBC.read_bytes()
        offending = [byte for byte in raw if byte > 127]
        self.assertEqual(offending, [], 'shipped DBC must be ASCII for portability')

    def test_cp1252_encoded_dbc_is_imported_correctly(self):
        """A DBC written in the conventional cp1252 encoding must still import."""
        text = OWN_DBC.read_text(encoding='utf-8').replace('"degC"', '"\u00b0C"')
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'cp1252.dbc'
            path.write_bytes(text.encode('cp1252'))
            resources = {r.name: r for r in dbc_importer.load(path, network='N')}
        self.assertEqual(resources['CellTempMax'].encoding.unit, '\u00b0C')

    def test_signal_count_agrees(self):
        reference_signals = {s.name for m in self.reference.messages for s in m.signals}
        own_signals = {name for name, r in self.resources.items()
                       if r.encoding is not None}
        self.assertEqual(own_signals, reference_signals)

    def test_exported_dbc_is_accepted_by_the_reference(self):
        """A DBC written from our JSON must load in an independent tool."""
        from tools.dbc_to_json import dbc_to_dict, dict_to_dbc

        data = dbc_to_dict(OWN_DBC.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'exported.dbc'
            path.write_text(dict_to_dbc(data), encoding='utf-8')
            regenerated = cantools.database.load_file(str(path))

        self.assertEqual({m.name for m in regenerated.messages},
                         {m.name for m in self.reference.messages})
        for message in self.reference.messages:
            other = regenerated.get_message_by_name(message.name)
            with self.subTest(message=message.name):
                self.assertEqual(other.frame_id, message.frame_id)
                self.assertEqual({s.name for s in other.signals},
                                 {s.name for s in message.signals})


if __name__ == '__main__':
    unittest.main()
