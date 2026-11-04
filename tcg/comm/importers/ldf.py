"""Importer for LIN Description Files (.ldf).

No suitable dependency-free library exists for LDF (cantools has no LIN support;
canmatrix's LDF support is partial), so this is a bounded parser for a documented
subset of LIN 2.x LDF.

Supported blocks
----------------
``LIN_protocol_version`` / ``LIN_language_version`` / ``LIN_speed``, ``Nodes``,
``Signals`` (including array initial values such as ``{5, 4, 3}``), ``Frames``
(with or without the length field, as LIN 1.3/2.0 allow), ``Diagnostic_frames``,
``Event_triggered_frames``, ``Sporadic_frames``, ``Schedule_tables`` (delays with or
without a space, e.g. ``10 ms`` and ``10ms``), ``Signal_encoding_types``
(``logical_value`` and ``physical_value``) and ``Signal_representation``.

Blocks that are not modelled -- ``Node_attributes``, ``Diagnostic_signals``,
``Node_composition`` -- are preserved verbatim so a converter can write them back
and the result stays a valid LDF for other tools.

Not supported
-------------
``bcd_value`` and ``ascii_value`` encodings. A signal that needs one fails loudly
instead of being imported with approximated semantics. Configuration commands inside
schedule tables (``AssignNAD``, ``AssignFrameId``, ``FreeFormat``, ...) are recorded
as commands, not as frame transmissions.

Verified against
----------------
``tests/conformance/`` compares this importer field by field with the independent
``ldfparser`` implementation over 12 foreign LDF files (LIN 1.3, 2.0, 2.1, 2.2,
ISO 17987, SAE J2602). Signal widths, units, factor/offset and symbolic states agree
on every file that both tools accept.

Resources produced: one `SCHEDULE` per schedule table, one `FRAME` per unconditional
frame, one `SIGNAL` per signal, with unit/factor/offset/range and symbolic states
taken from the encoding type assigned by ``Signal_representation``.
"""
from __future__ import annotations

from pathlib import Path
import re
from types import MappingProxyType

from tcg.comm.model import (
    CommunicationResource,
    ObjectKind,
    Technology,
    build_encoding,
)
from tcg.core.model import SpecError

TECHNOLOGY = Technology.LIN
FORMAT_ID = 'ldf'

#: Blocks this importer knowingly ignores; a signal depending on them still fails.
IGNORED_BLOCKS = frozenset({
    'Node_attributes', 'Diagnostic_signals', 'Node_composition',
})

#: LIN 2.x specifies these two diagnostic frames; LDFs reference them in schedule
#: tables without declaring them. They are added so no schedule entry dangles.
STANDARD_DIAGNOSTIC_FRAMES = {'MasterReq': 0x3C, 'SlaveResp': 0x3D}

_COMMENT_BLOCK = re.compile(r'/\*.*?\*/', re.DOTALL)
_COMMENT_LINE = re.compile(r'//[^\n]*')
_STRING = re.compile(r'"([^"]*)"')


def _strip_comments(text):
    return _COMMENT_LINE.sub('', _COMMENT_BLOCK.sub('', text))


def _match_block(text, name, start=0):
    """Return (body, end_index) of the brace-delimited block `name`, or (None, -1)."""
    pattern = re.compile(rf'\b{re.escape(name)}\b[^{{]*\{{', re.DOTALL)
    match = pattern.search(text, start)
    if not match:
        return None, -1
    depth, index = 1, match.end()
    while index < len(text) and depth:
        if text[index] == '{':
            depth += 1
        elif text[index] == '}':
            depth -= 1
        index += 1
    if depth:
        raise SpecError(f'LDF-Block {name!r} ist nicht geschlossen')
    return text[match.end():index - 1], index


def _statements(body):
    """Split a block body into ';'-terminated statements, ignoring nested blocks."""
    result, depth, current = [], 0, []
    for char in body:
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        if char == ';' and depth == 0:
            statement = ''.join(current).strip()
            if statement:
                result.append(statement)
            current = []
        else:
            current.append(char)
    tail = ''.join(current).strip()
    if tail:
        result.append(tail)
    return result


def _split_fields(text):
    """Split on commas that are not inside a brace group (LIN array values)."""
    fields, depth, current = [], 0, []
    for char in text:
        if char == '{':
            depth += 1
        elif char == '}':
            depth -= 1
        if char == ',' and depth == 0:
            fields.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
    tail = ''.join(current).strip()
    if tail:
        fields.append(tail)
    return [field for field in fields if field]


def _init_value(text, where):
    """A scalar initial value, or the byte list of an array signal."""
    text = text.strip()
    if text.startswith('{'):
        inner = text.strip('{}').strip()
        return [_number(part, where) for part in inner.split(',') if part.strip()]
    return _number(text, where)


def _number(text, where):
    text = text.strip()
    # LDFs in the wild write both "10 ms" and "10ms"; strip a trailing unit.
    match = re.match(r'^([+-]?(?:0[xX][0-9a-fA-F]+|[0-9]*\.?[0-9]+(?:[eE][+-]?[0-9]+)?))'
                     r'\s*[A-Za-z%/]*$', text)
    if match:
        text = match.group(1)
    try:
        return float(text) if ('.' in text or ('e' in text.lower()
                                               and not text.lower().startswith('0x'))) \
            else int(text, 0)
    except ValueError:
        raise SpecError(f'{where}: {text!r} ist keine Zahl') from None


def _parse_signals(body, where):
    """``SigName: size, init_value, publisher [, subscriber...] ;``"""
    signals = {}
    for statement in _statements(body):
        name, separator, rest = statement.partition(':')
        name = name.strip()
        if not separator or not name:
            raise SpecError(f'{where}: ungültige Signaldefinition {statement!r}')
        fields = _split_fields(rest)
        if len(fields) < 3:
            raise SpecError(f'{where}: Signal {name!r} braucht Größe, Initialwert '
                            f'und Publisher')
        signals[name] = {
            'size': _number(fields[0], f'{where}: Signal {name!r} Größe'),
            'init': _init_value(fields[1], f'{where}: Signal {name!r} Initialwert'),
            'publisher': fields[2],
            'subscribers': tuple(fields[3:]),
        }
    return signals


def _parse_frames(body, where):
    """``FrameName: id, publisher, length { SigName, offset; }``"""
    frames, index = {}, 0
    # ``Name: id, publisher, length {`` and the older ``Name: id, publisher {``.
    header = re.compile(r'([A-Za-z_]\w*)\s*:\s*([^,{]+?)\s*,\s*([^,{]+?)\s*'
                        r'(?:,\s*([^{\s]+)\s*)?\{', re.DOTALL)
    while True:
        match = header.search(body, index)
        if not match:
            break
        name = match.group(1)
        depth, cursor = 1, match.end()
        while cursor < len(body) and depth:
            if body[cursor] == '{':
                depth += 1
            elif body[cursor] == '}':
                depth -= 1
            cursor += 1
        inner = body[match.end():cursor - 1]
        layout = {}
        for statement in _statements(inner):
            signal_name, _, offset = statement.partition(',')
            layout[signal_name.strip()] = _number(
                offset, f'{where}: Frame {name!r} Offset von {signal_name.strip()!r}')
        frames[name] = {
            'id': _number(match.group(2), f'{where}: Frame {name!r} ID'),
            'publisher': match.group(3).strip(),
            'length': (_number(match.group(4), f'{where}: Frame {name!r} Länge')
                       if match.group(4) else None),
            'layout': layout,
        }
        index = cursor
    return frames


def _parse_diagnostic_frames(body, where):
    """``MasterReq: 0x3C { Sig, 0; }`` -- id only, no publisher or length."""
    frames, index = {}, 0
    header = re.compile(r'([A-Za-z_]\w*)\s*:\s*([^,{]+?)\s*\{', re.DOTALL)
    while True:
        match = header.search(body, index)
        if not match:
            break
        name = match.group(1)
        depth, cursor = 1, match.end()
        while cursor < len(body) and depth:
            if body[cursor] == '{':
                depth += 1
            elif body[cursor] == '}':
                depth -= 1
            cursor += 1
        frames[name] = {
            'id': _number(match.group(2), f'{where}: Diagnose-Frame {name!r} ID'),
            'publisher': None,
            'length': 8,
            'layout': {},
            'diagnostic': True,
        }
        index = cursor
    return frames


def _parse_aggregate_frames(body, where, kind, has_identifier):
    """``Name : [resolver,] [id,] frame, frame ;`` for event-triggered/sporadic frames."""
    frames = {}
    for statement in _statements(body):
        name, separator, rest = statement.partition(':')
        name = name.strip()
        if not separator or not name:
            continue
        fields = _split_fields(rest)
        identifier, members = None, list(fields)
        if has_identifier:
            # Event-triggered: collision resolver, then the protected identifier.
            members = fields[2:] if len(fields) > 2 else []
            if len(fields) > 1:
                try:
                    identifier = _number(fields[1], f'{where}: Frame {name!r} ID')
                except SpecError:
                    identifier = None
        frames[name] = {
            'id': identifier,
            'publisher': None,
            'length': None,
            'layout': {},
            'aggregate': kind,
            'members': tuple(members),
        }
    return frames


def _parse_schedule_tables(body, where):
    tables, index = {}, 0
    header = re.compile(r'([A-Za-z_]\w*)\s*\{', re.DOTALL)
    while True:
        match = header.search(body, index)
        if not match:
            break
        name = match.group(1)
        depth, cursor = 1, match.end()
        while cursor < len(body) and depth:
            if body[cursor] == '{':
                depth += 1
            elif body[cursor] == '}':
                depth -= 1
            cursor += 1
        entries = []
        for statement in _statements(body[match.end():cursor - 1]):
            parts = statement.split()
            if not parts:
                continue
            delay = None
            if 'delay' in parts:
                position = parts.index('delay')
                if position + 1 < len(parts):
                    delay = _number(parts[position + 1],
                                    f'{where}: Schedule {name!r} Delay')
            # ``AssignNAD { ... } delay 10 ms`` is a configuration command, not a
            # frame reference. It is recorded, but never presented as a frame.
            is_command = '{' in statement
            entries.append({'frame': None if is_command else parts[0],
                            'command': parts[0] if is_command else None,
                            'delay_ms': delay})
        tables[name] = entries
        index = cursor
    return tables


def _parse_encoding_types(body, where):
    """``EncName { logical_value, raw, "text"; physical_value, min, max, factor, offset, "unit"; }``"""
    encodings, index = {}, 0
    header = re.compile(r'([A-Za-z_]\w*)\s*\{', re.DOTALL)
    while True:
        match = header.search(body, index)
        if not match:
            break
        name = match.group(1)
        depth, cursor = 1, match.end()
        while cursor < len(body) and depth:
            if body[cursor] == '{':
                depth += 1
            elif body[cursor] == '}':
                depth -= 1
            cursor += 1
        values, scaling, unsupported = {}, None, []
        for statement in _statements(body[match.end():cursor - 1]):
            fields = [part.strip() for part in statement.split(',')]
            kind = fields[0].lower()
            if kind == 'logical_value':
                if len(fields) < 3:
                    raise SpecError(f'{where}: Encoding {name!r}: logical_value braucht '
                                    f'Rohwert und Bezeichnung')
                label = _STRING.search(fields[2])
                if not label:
                    raise SpecError(f'{where}: Encoding {name!r}: Bezeichnung '
                                    f'{fields[2]!r} muss in Anführungszeichen stehen')
                values[_number(fields[1], f'{where}: Encoding {name!r}')] = label.group(1)
            elif kind == 'physical_value':
                if len(fields) < 5:
                    raise SpecError(f'{where}: Encoding {name!r}: physical_value braucht '
                                    f'min, max, factor und offset')
                unit = _STRING.search(fields[5]) if len(fields) > 5 else None
                scaling = {
                    'minimum': _number(fields[1], f'{where}: Encoding {name!r} min'),
                    'maximum': _number(fields[2], f'{where}: Encoding {name!r} max'),
                    'factor': _number(fields[3], f'{where}: Encoding {name!r} factor'),
                    'offset': _number(fields[4], f'{where}: Encoding {name!r} offset'),
                    'unit': unit.group(1) if unit else None,
                }
            elif kind in ('bcd_value', 'ascii_value'):
                unsupported.append(kind)
            elif kind:
                unsupported.append(kind)
        encodings[name] = {'values': values, 'scaling': scaling,
                           'unsupported': tuple(unsupported)}
        index = cursor
    return encodings


def _parse_nodes(body, where):
    """``Master: Name, time_base, jitter;`` and ``Slaves: A, B;``"""
    nodes = {'master': None, 'slaves': ()}
    for statement in _statements(body):
        key, separator, rest = statement.partition(':')
        if not separator:
            continue
        values = [part.strip() for part in rest.split(',') if part.strip()]
        if key.strip().lower() == 'master' and values:
            nodes['master'] = values[0]
        elif key.strip().lower() == 'slaves':
            nodes['slaves'] = tuple(values)
    return nodes


def _parse_representation(body, where):
    """``EncName: Sig1, Sig2;``"""
    assignment = {}
    for statement in _statements(body):
        encoding, separator, signals = statement.partition(':')
        if not separator:
            raise SpecError(f'{where}: ungültige Signal_representation {statement!r}')
        for signal in signals.split(','):
            signal = signal.strip()
            if signal:
                assignment[signal] = encoding.strip()
    return assignment


def parse_ldf(text, where='description.ldf'):
    """Parse the supported subset of an LDF into plain dictionaries."""
    text = _strip_comments(text)
    if 'LIN_description_file' not in text:
        raise SpecError(f'{where}: keine LDF-Datei '
                        f'(Kennung "LIN_description_file" fehlt)')

    speed = re.search(r'LIN_speed\s*=\s*([0-9.]+)', text)
    protocol = _STRING.search(
        text[text.find('LIN_protocol_version'):text.find('LIN_protocol_version') + 80]
    ) if 'LIN_protocol_version' in text else None

    nodes_body, _ = _match_block(text, 'Nodes')
    signals_body, _ = _match_block(text, 'Signals')
    # Blocks this importer does not model are preserved verbatim, so a converter can
    # write them back out and the result stays a valid LDF for other tools.
    raw_blocks = {}
    for block in ('Nodes', *sorted(IGNORED_BLOCKS)):
        body, _end = _match_block(text, block)
        if body is not None:
            raw_blocks[block] = body
    frames_body, _ = _match_block(text, 'Frames')
    diagnostic_body, _ = _match_block(text, 'Diagnostic_frames')
    event_body, _ = _match_block(text, 'Event_triggered_frames')
    sporadic_body, _ = _match_block(text, 'Sporadic_frames')
    schedules_body, _ = _match_block(text, 'Schedule_tables')
    encodings_body, _ = _match_block(text, 'Signal_encoding_types')
    representation_body, _ = _match_block(text, 'Signal_representation')

    if signals_body is None:
        raise SpecError(f'{where}: Block "Signals" fehlt')

    return {
        'speed': float(speed.group(1)) if speed else None,
        'protocol_version': protocol.group(1) if protocol else None,
        'nodes': _parse_nodes(nodes_body, where) if nodes_body else {},
        'raw_blocks': raw_blocks,
        'signals': _parse_signals(signals_body, where),
        'frames': {**(_parse_frames(frames_body, where) if frames_body else {}),
                   **(_parse_diagnostic_frames(diagnostic_body, where)
                      if diagnostic_body else {}),
                   **(_parse_aggregate_frames(event_body, where, 'event_triggered', True)
                      if event_body else {}),
                   **(_parse_aggregate_frames(sporadic_body, where, 'sporadic', False)
                      if sporadic_body else {})},
        'schedules': _parse_schedule_tables(schedules_body, where) if schedules_body else {},
        'encodings': _parse_encoding_types(encodings_body, where) if encodings_body else {},
        'representation': _parse_representation(representation_body, where)
        if representation_body else {},
    }


def resources_from_ldf(data, network, source, technology=Technology.LIN):
    resources, problems = [], []

    referenced = {entry['frame'] for entries in data['schedules'].values()
                  for entry in entries if entry.get('frame')}
    for name, identifier in STANDARD_DIAGNOSTIC_FRAMES.items():
        if name in referenced and name not in data['frames']:
            data['frames'][name] = {'id': identifier, 'publisher': None, 'length': 8,
                                    'layout': {}, 'diagnostic': True}

    for table, entries in data['schedules'].items():
        resources.append(CommunicationResource(
            name=table, technology=technology, network=network,
            kind=ObjectKind.SCHEDULE, source=source,
            attributes=MappingProxyType({
                'frames': tuple(entry['frame'] for entry in entries
                                if entry.get('frame')),
                'entries': tuple((entry['frame'], entry['delay_ms'])
                                 for entry in entries if entry.get('frame')),
                'commands': tuple((entry['command'], entry['delay_ms'])
                                  for entry in entries if entry.get('command')),
            }),
        ))

    signal_to_frame = {}
    for frame_name, frame in data['frames'].items():
        for signal_name in frame['layout']:
            signal_to_frame[signal_name] = frame_name
        resources.append(CommunicationResource(
            name=frame_name, technology=technology, network=network,
            kind=ObjectKind.FRAME, source=source,
            attributes=MappingProxyType({
                'id': frame['id'], 'publisher': frame['publisher'],
                'length': frame['length'],
                'diagnostic': bool(frame.get('diagnostic')),
                'aggregate': frame.get('aggregate'),
                'members': frame.get('members', ()),
            }),
        ))

    for signal_name, signal in data['signals'].items():
        encoding_name = data['representation'].get(signal_name)
        values, scaling = {}, None
        if encoding_name is not None:
            encoding = data['encodings'].get(encoding_name)
            if encoding is None:
                problems.append(
                    f'{source}: Signal {signal_name!r} verweist auf den Encoding-Typ '
                    f'{encoding_name!r}, der in "Signal_encoding_types" fehlt')
                continue
            if encoding['unsupported']:
                problems.append(
                    f'{source}: Signal {signal_name!r} benötigt den nicht '
                    f'unterstützten Encoding-Eintrag '
                    f'{", ".join(sorted(set(encoding["unsupported"])))} '
                    f'(Encoding {encoding_name!r})')
                continue
            values = encoding['values']
            scaling = encoding['scaling'] or None

        where = f'{source}: Signal {signal_name!r}'
        try:
            built = build_encoding(
                where,
                unit=(scaling or {}).get('unit'),
                factor=(scaling or {}).get('factor', 1),
                offset=(scaling or {}).get('offset', 0),
                minimum=(scaling or {}).get('minimum'),
                maximum=(scaling or {}).get('maximum'),
                values=values,
            )
        except SpecError as error:
            problems.extend(error.problems)
            continue

        resources.append(CommunicationResource(
            name=signal_name, technology=technology, network=network,
            kind=ObjectKind.SIGNAL, source=source,
            container=signal_to_frame.get(signal_name),
            encoding=built,
            attributes=MappingProxyType({
                'size': signal['size'], 'init': signal['init'],
                'publisher': signal['publisher'], 'subscribers': signal['subscribers'],
                'encoding_type': encoding_name,
            }),
        ))

    if problems:
        raise SpecError(problems)
    return tuple(resources)


def load(path, *, network=None, technology=None):
    path = Path(path)
    try:
        text = path.read_text(encoding='utf-8-sig')
    except FileNotFoundError:
        raise SpecError(f'{path.name}: Kommunikationsbeschreibung nicht gefunden: '
                        f'{path}') from None
    except OSError as error:
        raise SpecError(f'{path.name}: Beschreibung nicht lesbar '
                        f'({error.strerror})') from None
    data = parse_ldf(text, path.name)
    return resources_from_ldf(
        data, network=network or path.stem, source=path.name,
        technology=technology or TECHNOLOGY,
    )
