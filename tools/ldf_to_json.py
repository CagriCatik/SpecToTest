#!/usr/bin/env python3
"""LDF to JSON & JSON to LDF Converter for LIN Descriptions.

A pure Python standard library tool for bidirectional conversion between LIN
Description Files (.ldf) and SpecToTest LIN signal definitions (.json). It is the
LIN counterpart of ``tools/dbc_to_json.py``.

The LDF text parser is not duplicated here: it lives with the importer in
``tcg/comm/importers/ldf.py``, so the compiler and this tool always agree on what
the supported subset is.

Features:
- Supported LDF subset: Nodes, Signals (incl. array initial values), Frames (with
  or without a length field), Diagnostic/Event-triggered/Sporadic frames,
  Schedule_tables, Signal_encoding_types (logical_value / physical_value) and
  Signal_representation. Blocks that are not modelled (Node_attributes,
  Diagnostic_signals, Node_composition) are preserved verbatim, so the regenerated
  LDF stays valid for other LIN tools.
- Bidirectional support: LDF -> JSON and JSON -> LDF.
- LIN validation (--check): frame capacity, signal overlap, protected identifier
  range, schedule and encoding references, scaling sanity.

Not supported (and never silently dropped when a signal needs it): bcd_value and
ascii_value encodings. Schedule configuration commands (AssignNAD, AssignFrameId,
FreeFormat, ...) are recorded as commands, not as frame transmissions.

The output of this converter is cross-checked in tests/conformance/: the regenerated
LDF must be accepted by the independent ldfparser implementation.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

if __package__ in (None, ''):  # allow `python tools/ldf_to_json.py`
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tcg.comm.importers.ldf import parse_ldf  # noqa: E402
from tcg.core.model import SpecError  # noqa: E402

#: Highest valid LIN protected identifier (6 bits).
MAX_LIN_ID = 0x3F


def _hex_id(value: Any) -> str:
    try:
        return f'0x{int(value):02X}'
    except (TypeError, ValueError):
        return str(value)


def ldf_to_dict(ldf_content: str, name: str = 'description.ldf') -> dict[str, Any]:
    """Parse a LIN Description File string into a SpecToTest dictionary.

    Args:
        ldf_content: Raw text content of an .ldf file.
        name: File name used in error messages.

    Returns:
        Dictionary with database, nodes, frames, signals and schedules.
    """
    parsed = parse_ldf(ldf_content, name)

    signal_to_frame: dict[str, str] = {}
    signal_offset: dict[str, int] = {}
    frames: dict[str, Any] = {}
    for frame_name, frame in parsed['frames'].items():
        for signal_name, offset in frame['layout'].items():
            signal_to_frame[signal_name] = frame_name
            signal_offset[signal_name] = offset
        frames[frame_name] = {
            'id': _hex_id(frame['id']),
            'publisher': frame['publisher'],
            'length': frame['length'],
            'layout': dict(frame['layout']),
        }

    signals: dict[str, Any] = {}
    for signal_name, signal in parsed['signals'].items():
        encoding_name = parsed['representation'].get(signal_name)
        encoding = parsed['encodings'].get(encoding_name) if encoding_name else None
        scaling = (encoding or {}).get('scaling') or {}
        values = (encoding or {}).get('values') or {}
        entry: dict[str, Any] = {
            'frame': signal_to_frame.get(signal_name),
            'start_bit': signal_offset.get(signal_name),
            'size': signal['size'],
            'init': signal['init'],
            'publisher': signal['publisher'],
            'subscribers': list(signal['subscribers']),
            'unit': scaling.get('unit') or '',
            'factor': scaling.get('factor', 1),
            'offset': scaling.get('offset', 0),
        }
        if 'minimum' in scaling:
            entry['min'] = scaling['minimum']
            entry['max'] = scaling['maximum']
        if encoding_name:
            entry['encoding_type'] = encoding_name
        if values:
            entry['values'] = {str(raw): text for raw, text in sorted(values.items())}
        signals[signal_name] = entry

    schedules = {
        table: [{'frame': entry['frame'], 'delay_ms': entry['delay_ms']}
                for entry in entries]
        for table, entries in parsed['schedules'].items()
    }

    return {
        'database': Path(name).stem,
        'protocol': 'LIN',
        'protocol_version': parsed['protocol_version'],
        'speed_kbps': parsed['speed'],
        'nodes': {
            'master': parsed['nodes'].get('master'),
            'slaves': list(parsed['nodes'].get('slaves', ())),
        },
        'frames': frames,
        'signals': signals,
        'schedules': schedules,
        # Verbatim copies of blocks this converter does not interpret (Node_attributes,
        # diagnostic frames, ...). They are written back unchanged so the regenerated
        # LDF stays valid for other LIN tools.
        'raw_blocks': {name: body for name, body in parsed['raw_blocks'].items()},
    }


def dict_to_ldf(data: dict[str, Any]) -> str:
    """Render a SpecToTest LIN dictionary back into LDF text."""
    nodes = data.get('nodes') or {}
    frames = data.get('frames') or {}
    signals = data.get('signals') or {}
    schedules = data.get('schedules') or {}

    lines: list[str] = [
        '/* Generated by tools/ldf_to_json.py. Edit the JSON and regenerate. */',
        'LIN_description_file;',
    ]
    version = data.get('protocol_version') or '2.1'
    lines.append(f'LIN_protocol_version = "{version}";')
    lines.append(f'LIN_language_version = "{version}";')
    speed = data.get('speed_kbps')
    if speed is not None:
        lines.append(f'LIN_speed = {speed} kbps;')
    lines.append('')

    raw_blocks = data.get('raw_blocks') or {}
    if 'Nodes' in raw_blocks:
        lines.append('Nodes {' + raw_blocks['Nodes'] + '}')
    else:
        lines.append('Nodes {')
        if nodes.get('master'):
            lines.append(f'  Master: {nodes["master"]}, 5 ms, 0.1 ms;')
        if nodes.get('slaves'):
            lines.append(f'  Slaves: {", ".join(nodes["slaves"])};')
        lines.append('}')
    lines.append('')

    lines.append('Signals {')
    for name, signal in signals.items():
        subscribers = signal.get('subscribers') or []
        parts = [str(signal.get('size', 8)), str(signal.get('init', 0)),
                 signal.get('publisher', 'Master'), *subscribers]
        lines.append(f'  {name}: {", ".join(parts)};')
    lines.append('}')
    lines.append('')

    lines.append('Frames {')
    for name, frame in frames.items():
        lines.append(f'  {name}: {frame.get("id", "0x00")}, '
                     f'{frame.get("publisher", "Master")}, {frame.get("length", 1)} {{')
        for signal_name, offset in (frame.get('layout') or {}).items():
            lines.append(f'    {signal_name}, {offset};')
        lines.append('  }')
    lines.append('}')
    lines.append('')

    # Preserved blocks (Node_attributes etc.) must appear before the schedule tables,
    # and are emitted exactly as they were read.
    for block, body in raw_blocks.items():
        if block == 'Nodes':
            continue
        lines.append(block + ' {' + body + '}')
        lines.append('')

    if schedules:
        lines.append('Schedule_tables {')
        for table, entries in schedules.items():
            lines.append(f'  {table} {{')
            for entry in entries:
                delay = entry.get('delay_ms')
                suffix = f' delay {delay} ms' if delay is not None else ''
                lines.append(f'    {entry["frame"]}{suffix};')
            lines.append('  }')
        lines.append('}')
        lines.append('')

    # One encoding type per signal that declares states or scaling.
    encodings: dict[str, dict[str, Any]] = {}
    representation: dict[str, str] = {}
    for name, signal in signals.items():
        values = signal.get('values') or {}
        scaled = (signal.get('factor', 1) != 1 or signal.get('offset', 0) != 0
                  or signal.get('unit'))
        if not values and not scaled:
            continue
        encoding_name = signal.get('encoding_type') or f'{name}_Encoding'
        encodings.setdefault(encoding_name, {'values': values, 'signal': signal})
        representation[name] = encoding_name

    if encodings:
        lines.append('Signal_encoding_types {')
        for encoding_name, info in encodings.items():
            lines.append(f'  {encoding_name} {{')
            for raw, text in (info['values'] or {}).items():
                lines.append(f'    logical_value, {raw}, "{text}";')
            signal = info['signal']
            if not info['values']:
                lines.append(
                    f'    physical_value, {signal.get("min", 0)}, '
                    f'{signal.get("max", 0)}, {signal.get("factor", 1)}, '
                    f'{signal.get("offset", 0)}, "{signal.get("unit", "")}";')
            lines.append('  }')
        lines.append('}')
        lines.append('')

        lines.append('Signal_representation {')
        grouped: dict[str, list[str]] = {}
        for signal_name, encoding_name in representation.items():
            grouped.setdefault(encoding_name, []).append(signal_name)
        for encoding_name, members in grouped.items():
            lines.append(f'  {encoding_name}: {", ".join(members)};')
        lines.append('}')

    return '\n'.join(lines) + '\n'


def validate_lin_database(data: dict[str, Any]) -> list[str]:
    """Validate a LIN database dictionary against LIN network constraints.

    Checks:
    - Protected identifier range (0x00..0x3F) and duplicate frame ids.
    - Frame capacity: every signal must fit inside the frame length.
    - Signal overlap inside one frame.
    - Signals referencing an unknown frame, and frame layouts referencing
      undeclared signals.
    - Schedule tables referencing unknown frames.
    - Zero scaling factor and inverted min/max.
    - Initial values outside the raw range the signal size allows.

    Returns:
        List of error strings (empty list if compliant).
    """
    errors: list[str] = []
    frames = data.get('frames', {}) or {}
    signals = data.get('signals', {}) or {}
    schedules = data.get('schedules', {}) or {}

    seen_ids: dict[int, str] = {}
    for frame_name, frame in frames.items():
        raw_id = frame.get('id')
        try:
            identifier = int(str(raw_id), 0)
        except (TypeError, ValueError):
            errors.append(f"Frame '{frame_name}' has a non-numeric id {raw_id!r}")
            continue
        if not 0 <= identifier <= MAX_LIN_ID:
            errors.append(f"Frame '{frame_name}' id {_hex_id(identifier)} is outside "
                          f"the LIN range 0x00..0x3F")
        if identifier in seen_ids:
            errors.append(f"Frame '{frame_name}' reuses id {_hex_id(identifier)} of "
                          f"frame '{seen_ids[identifier]}'")
        else:
            seen_ids[identifier] = frame_name

        capacity = int(frame.get('length', 0)) * 8
        occupied: dict[int, str] = {}
        for signal_name, offset in (frame.get('layout') or {}).items():
            signal = signals.get(signal_name)
            if signal is None:
                errors.append(f"Frame '{frame_name}' maps undeclared signal "
                              f"'{signal_name}'")
                continue
            size = int(signal.get('size', 0))
            if offset + size > capacity:
                errors.append(
                    f"Signal '{signal_name}' exceeds frame '{frame_name}': bits "
                    f"{offset}..{offset + size - 1} do not fit in {capacity} bits")
            for bit in range(offset, offset + size):
                if bit in occupied:
                    errors.append(
                        f"Signal '{signal_name}' overlaps '{occupied[bit]}' at bit "
                        f"{bit} in frame '{frame_name}'")
                    break
                occupied[bit] = signal_name

    for signal_name, signal in signals.items():
        frame_name = signal.get('frame')
        if frame_name is not None and frame_name not in frames:
            errors.append(f"Signal '{signal_name}' references unknown frame "
                          f"'{frame_name}'")
        factor = signal.get('factor', 1)
        try:
            if float(factor) == 0:
                errors.append(f"Signal '{signal_name}' has a scaling factor of zero")
        except (TypeError, ValueError):
            errors.append(f"Signal '{signal_name}' has a non-numeric factor {factor!r}")
        minimum, maximum = signal.get('min'), signal.get('max')
        if minimum is not None and maximum is not None and minimum > maximum:
            errors.append(f"Signal '{signal_name}' has min {minimum} greater than "
                          f"max {maximum}")
        size = int(signal.get('size', 0) or 0)
        init = signal.get('init')
        if size and isinstance(init, (int, float)) and not 0 <= init < 2 ** size:
            errors.append(f"Signal '{signal_name}' initial value {init} does not fit "
                          f"in {size} bit(s)")
        for raw in (signal.get('values') or {}):
            try:
                raw_value = int(str(raw), 0)
            except (TypeError, ValueError):
                errors.append(f"Signal '{signal_name}' has a non-numeric state key "
                              f"{raw!r}")
                continue
            if size and not 0 <= raw_value < 2 ** size:
                errors.append(f"Signal '{signal_name}' state value {raw_value} does "
                              f"not fit in {size} bit(s)")

    for table, entries in schedules.items():
        for entry in entries:
            frame_name = entry.get('frame') if isinstance(entry, dict) else entry
            if frame_name not in frames:
                errors.append(f"Schedule table '{table}' references unknown frame "
                              f"'{frame_name}'")
            delay = entry.get('delay_ms') if isinstance(entry, dict) else None
            if delay is not None and delay <= 0:
                errors.append(f"Schedule table '{table}' entry '{frame_name}' has a "
                              f"non-positive delay {delay}")

    return errors


def convert_file(
    input_path: Path,
    output_path: Path | None = None,
    force_mode: str | None = None,
    pretty: bool = True,
    check: bool = False,
) -> tuple[dict[str, Any] | str, list[str]]:
    """Convert LDF to JSON or JSON to LDF, optionally writing to output_path.

    Args:
        input_path: Path to source file (.ldf or .json).
        output_path: Path to target file (or None for in-memory return).
        force_mode: 'json' or 'ldf' to override extension inference.
        pretty: Whether to format JSON with indentation.
        check: Whether to perform validation checks.

    Returns:
        Tuple of (result_data_or_string, list_of_validation_issues).
    """
    content = input_path.read_text(encoding='utf-8-sig')
    ext = input_path.suffix.lower()

    if force_mode == 'ldf' or (force_mode is None and ext == '.json'):
        # JSON -> LDF
        data = json.loads(content)
        validation_issues = validate_lin_database(data) if check else []
        result: dict[str, Any] | str = dict_to_ldf(data)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result, encoding='utf-8')
        return result, validation_issues

    # Default: LDF -> JSON
    data = ldf_to_dict(content, input_path.name)
    validation_issues = validate_lin_database(data) if check else []
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, 'w', encoding='utf-8') as handle:
            if pretty:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write('\n')
            else:
                json.dump(data, handle, ensure_ascii=False)
    return data, validation_issues


def main() -> int:
    """CLI entrypoint for the ldf_to_json converter."""
    parser = argparse.ArgumentParser(
        description='LIN Description File (.ldf) <-> SpecToTest JSON Converter & Validator.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert LDF to JSON and validate:
  python tools/ldf_to_json.py tools/body_comfort.ldf -o inputs/lin_signals.json --check

  # Validate only, without writing anything:
  python tools/ldf_to_json.py tools/body_comfort.ldf --check

  # Regenerate an LDF from JSON:
  python tools/ldf_to_json.py inputs/lin_signals.json -o out/body_comfort.ldf
""")
    parser.add_argument('input', type=Path, help='Source .ldf or .json file')
    parser.add_argument('-o', '--output', type=Path, default=None,
                        help='Target file (omit to print a summary only)')
    parser.add_argument('--mode', choices=('json', 'ldf'), default=None,
                        help='Force the conversion direction')
    parser.add_argument('--check', action='store_true',
                        help='Validate the LIN database and report issues')
    parser.add_argument('--compact', action='store_true',
                        help='Write JSON without indentation')
    args = parser.parse_args()

    if not args.input.is_file():
        print(f'CONVERSION FAILED: input file not found: {args.input}', file=sys.stderr)
        return 2
    try:
        result, issues = convert_file(args.input, args.output, args.mode,
                                      pretty=not args.compact, check=args.check)
    except SpecError as error:
        print(f'CONVERSION FAILED: {error}', file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError, ValueError) as error:
        print(f'CONVERSION FAILED: {args.input.name}: {error}', file=sys.stderr)
        return 2

    if isinstance(result, dict):
        print(f'LIN database "{result.get("database")}": '
              f'{len(result.get("frames", {}))} frames, '
              f'{len(result.get("signals", {}))} signals, '
              f'{len(result.get("schedules", {}))} schedule table(s)')
    else:
        print(f'Rendered LDF: {len(result.splitlines())} lines')
    if args.output:
        print(f'Written to: {args.output}')

    if args.check:
        if issues:
            print(f'\nValidation found {len(issues)} issue(s):', file=sys.stderr)
            for issue in issues:
                print(f'  - {issue}', file=sys.stderr)
            return 1
        print('Validation: no issues found')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
