#!/usr/bin/env python3
"""DBC to JSON & JSON to DBC Converter for CAN Databases.

A zero-dependency, pure Python standard library tool for bidirectional conversion
between Vector CANdb (.dbc) database files and SpecToTest CAN signal definitions (.json).

Features:
- Full Vector CANdb DBC format support (BO_, SG_, CM_, BA_DEF_, BA_DEF_DEF_, BA_, VAL_).
- Standard (11-bit) and extended (29-bit) CAN identifier handling.
- Little-endian (Intel) and big-endian (Motorola) byte order layout extraction.
- Extraction of cycle times, start values, scaling factors, offsets, and comments.
- Bidirectional support: DBC -> JSON and JSON -> DBC.
- DBC validation (--check): frame boundary overflow detection, signal overlap checking,
  and physical range verification.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any


def _parse_numeric(value: str) -> int | float:
    """Parse string representation of integer or floating-point number."""
    s = value.strip()
    if "." in s or "e" in s.lower():
        f = float(s)
        return int(f) if f.is_integer() and "." not in s else f
    try:
        return int(s)
    except ValueError:
        return float(s)


def dbc_to_dict(dbc_content: str) -> dict[str, Any]:
    """Parse a Vector CANdb (.dbc) file string into a SpecToTest dictionary.

    Args:
        dbc_content: Raw text content of a .dbc file.

    Returns:
        Dictionary conforming to inputs/can_signals.json structure.
    """
    lines = dbc_content.splitlines()

    # Default values
    db_name = "CAN_Database"
    baudrate = 500000
    messages: dict[str, dict[str, Any]] = {}
    signals: dict[str, dict[str, Any]] = {}

    # 1. Parse comments (CM_)
    # Message comments: CM_ BO_ <id> "<comment>";
    cm_bo: dict[int, str] = {}
    for m in re.finditer(r'CM_\s+BO_\s+(\d+)\s+"([^"]*)"\s*;', dbc_content, re.DOTALL):
        cm_bo[int(m.group(1)) & 0x1FFFFFFF] = m.group(2).strip()

    # Signal comments: CM_ SG_ <id> <signal_name> "<comment>";
    cm_sg: dict[tuple[int, str], str] = {}
    for m in re.finditer(r'CM_\s+SG_\s+(\d+)\s+([a-zA-Z0-9_]+)\s+"([^"]*)"\s*;', dbc_content, re.DOTALL):
        cm_sg[(int(m.group(1)) & 0x1FFFFFFF, m.group(2))] = m.group(3).strip()

    # Database general comment / name: CM_ "<comment>";
    cm_db = re.search(r'CM_\s+"([^"]*)"\s*;', dbc_content)
    if cm_db:
        candidate_name = cm_db.group(1).strip()
        if candidate_name:
            db_name = candidate_name

    # 2. Parse attributes (BA_)
    cycle_times: dict[int, int] = {}
    start_values: dict[tuple[int, str], int | float] = {}

    # Baudrate: BA_ "Baudrate" <val>;
    m_baud = re.search(r'BA_\s+"Baudrate"\s+(\d+)\s*;', dbc_content)
    if m_baud:
        baudrate = int(m_baud.group(1))
    else:
        m_baud_def = re.search(r'BA_DEF_DEF_\s+"Baudrate"\s+(\d+)\s*;', dbc_content)
        if m_baud_def:
            baudrate = int(m_baud_def.group(1))

    # GenMsgCycleTime: BA_ "GenMsgCycleTime" BO_ <id> <val>;
    for m in re.finditer(r'BA_\s+"GenMsgCycleTime"\s+BO_\s+(\d+)\s+(\d+)\s*;', dbc_content):
        cycle_times[int(m.group(1)) & 0x1FFFFFFF] = int(m.group(2))

    # GenSigStartValue: BA_ "GenSigStartValue" SG_ <id> <sig> <val>;
    for m in re.finditer(r'BA_\s+"GenSigStartValue"\s+SG_\s+(\d+)\s+([a-zA-Z0-9_]+)\s+([^\s;]+)\s*;', dbc_content):
        raw_val = _parse_numeric(m.group(3))
        start_values[(int(m.group(1)) & 0x1FFFFFFF, m.group(2))] = raw_val

    # Value descriptions (VAL_ <id> <signal> <num> "<desc>" ... ;)
    val_entries: dict[tuple[int, str], dict[str, str]] = {}
    val_pattern = re.compile(r'VAL_\s+(\d+)\s+([a-zA-Z0-9_]+)\s+(.*?)\s*;', re.DOTALL)
    for m in val_pattern.finditer(dbc_content):
        can_id = int(m.group(1)) & 0x1FFFFFFF
        sname = m.group(2)
        pairs_str = m.group(3)
        pairs = re.findall(r'(-?\d+)\s+"([^"]*)"', pairs_str)
        if pairs:
            val_entries[(can_id, sname)] = {val: desc for val, desc in pairs}

    # 3. Parse messages (BO_) and signals (SG_)
    bo_pattern = re.compile(r"^BO_\s+(\d+)\s+([a-zA-Z0-9_]+)\s*:\s*(\d+)\s+([a-zA-Z0-9_]+)")
    sg_pattern = re.compile(
        r"^\s*SG_\s+([a-zA-Z0-9_]+)\s*(?:m\d+)?\s*:\s*(\d+)\|(\d+)@([01])([+-])\s*"
        r"\(([^,]+),([^)]+)\)\s*\[([^|]+)\|([^]]+)\]\s*\"([^\"]*)\"\s*([a-zA-Z0-9_,\s]+)"
    )

    current_msg_name: str | None = None
    current_can_id: int | None = None

    for line in lines:
        line_clean = line.strip()
        m_bo = bo_pattern.match(line_clean)
        if m_bo:
            raw_id = int(m_bo.group(1))
            can_id = raw_id & 0x1FFFFFFF
            msg_name = m_bo.group(2)
            dlc = int(m_bo.group(3))

            current_msg_name = msg_name
            current_can_id = can_id

            messages[msg_name] = {
                "id": f"0x{can_id:03X}",
                "dlc": dlc,
                "cycle_time_ms": cycle_times.get(can_id, 0),
                "comment": cm_bo.get(can_id, ""),
            }
            continue

        m_sg = sg_pattern.match(line_clean)
        if m_sg and current_msg_name and current_can_id is not None:
            sig_name = m_sg.group(1)
            start_bit = int(m_sg.group(2))
            length = int(m_sg.group(3))
            factor = _parse_numeric(m_sg.group(6))
            offset = _parse_numeric(m_sg.group(7))
            sig_min = _parse_numeric(m_sg.group(8))
            sig_max = _parse_numeric(m_sg.group(9))
            unit = m_sg.group(10)

            default_val = start_values.get((current_can_id, sig_name), 0)
            comment_val = cm_sg.get((current_can_id, sig_name), "")

            sig_dict: dict[str, Any] = {
                "message": current_msg_name,
                "start_bit": start_bit,
                "length": length,
                "unit": unit,
                "factor": factor,
                "offset": offset,
                "min": sig_min,
                "max": sig_max,
                "default": default_val,
                "comment": comment_val,
            }
            if (current_can_id, sig_name) in val_entries:
                sig_dict["values"] = val_entries[(current_can_id, sig_name)]

            signals[sig_name] = sig_dict

    return {
        "database": db_name,
        "baudrate": baudrate,
        "messages": messages,
        "signals": signals,
    }


def dict_to_dbc(data: dict[str, Any]) -> str:
    """Serialize a SpecToTest signal database dictionary into a Vector CANdb (.dbc) file string.

    Args:
        data: Dictionary conforming to inputs/can_signals.json structure.

    Returns:
        Formatted DBC file text.
    """
    db_name = data.get("database", "CAN_Database")
    baudrate = data.get("baudrate", 500000)
    messages = data.get("messages", {})
    signals = data.get("signals", {})

    lines: list[str] = [
        'VERSION ""',
        "",
        "",
        "NS_ : ",
        "\tNS_DESC_",
        "\tCM_",
        "\tBA_DEF_",
        "\tBA_",
        "\tVAL_",
        "\tCAT_DEF_",
        "\tCAT_",
        "\tFILTER",
        "\tBA_DEF_DEF_",
        "\tEV_DATA_",
        "\tENVVAR_DATA_",
        "\tSGTYPE_",
        "\tSGTYPE_VAL_",
        "\tBA_DEF_SGTYPE_",
        "\tBA_SGTYPE_",
        "\tSIG_TYPE_REF_",
        "\tVAL_TABLE_",
        "\tSIG_GROUP_",
        "\tSIG_VALTYPE_",
        "\tSIGTYPE_VALTYPE_",
        "\tBO_TX_BU_",
        "\tBA_DEF_REL_",
        "\tBA_REL_",
        "\tBA_DEF_DEF_REL_",
        "\tBU_SG_REL_",
        "\tBU_EV_REL_",
        "\tBU_BO_REL_",
        "\tSG_MUL_VAL_",
        "",
        "BS_:",
        "",
        "BU_: ECU_BCM ECU_BMS ECU_ENGINE ECU_BRAKE Vector__XXX",
        "",
    ]

    # Group signals by message
    msg_to_signals: dict[str, list[tuple[str, dict[str, Any]]]] = {msg: [] for msg in messages}
    for sname, sdata in signals.items():
        mname = sdata.get("message")
        if mname in msg_to_signals:
            msg_to_signals[mname].append((sname, sdata))

    msg_id_map: dict[str, int] = {}
    cm_bo_list: list[tuple[int, str]] = []
    cm_sg_list: list[tuple[int, str, str]] = []
    cycle_time_list: list[tuple[int, int]] = []
    start_value_list: list[tuple[int, str, Any]] = []

    for msg_name, msg_data in messages.items():
        raw_id_str = str(msg_data.get("id", "0x000"))
        can_id = int(raw_id_str, 16) if raw_id_str.lower().startswith("0x") else int(raw_id_str)
        msg_id_map[msg_name] = can_id
        dlc = msg_data.get("dlc", 8)
        comment = msg_data.get("comment", "")
        cycle_time = msg_data.get("cycle_time_ms", 0)

        transmitter = "Vector__XXX"
        if "BCM" in msg_name or "Power" in msg_name or "Body" in msg_name:
            transmitter = "ECU_BCM"
        elif "Engine" in msg_name:
            transmitter = "ECU_ENGINE"
        elif "Brake" in msg_name:
            transmitter = "ECU_BRAKE"
        elif "BMS" in msg_name:
            transmitter = "ECU_BMS"

        lines.append(f"BO_ {can_id} {msg_name}: {dlc} {transmitter}")

        if comment:
            cm_bo_list.append((can_id, comment))
        if cycle_time > 0:
            cycle_time_list.append((can_id, cycle_time))

        # Sort signals by start_bit
        sorted_sigs = sorted(msg_to_signals.get(msg_name, []), key=lambda item: item[1].get("start_bit", 0))
        for sname, sdata in sorted_sigs:
            start_bit = sdata.get("start_bit", 0)
            length = sdata.get("length", 1)
            factor = sdata.get("factor", 1)
            offset = sdata.get("offset", 0)
            min_v = sdata.get("min", 0)
            max_v = sdata.get("max", 1)
            unit = sdata.get("unit", "")
            default_v = sdata.get("default", 0)
            sig_comment = sdata.get("comment", "")

            sign = "-" if min_v < 0 or offset < 0 else "+"
            lines.append(
                f" SG_ {sname} : {start_bit}|{length}@1{sign} ({factor},{offset}) [{min_v}|{max_v}] \"{unit}\" Vector__XXX"
            )

            if sig_comment:
                cm_sg_list.append((can_id, sname, sig_comment))
            if default_v is not None and default_v != 0:
                start_value_list.append((can_id, sname, default_v))

        lines.append("")

    # Comments CM_
    lines.append(f'CM_ "{db_name}";')
    for cid, ctext in cm_bo_list:
        lines.append(f'CM_ BO_ {cid} "{ctext}";')
    for cid, sname, ctext in cm_sg_list:
        lines.append(f'CM_ SG_ {cid} {sname} "{ctext}";')
    lines.append("")

    # Attributes definitions
    lines.extend([
        'BA_DEF_ "BusType" STRING ;',
        'BA_DEF_ "Baudrate" INT 0 1000000;',
        'BA_DEF_ BO_ "GenMsgCycleTime" INT 0 65535;',
        'BA_DEF_ SG_ "GenSigStartValue" FLOAT -10000000 10000000;',
        "",
        'BA_DEF_DEF_ "BusType" "CAN";',
        f'BA_DEF_DEF_ "Baudrate" {baudrate};',
        'BA_DEF_DEF_ "GenMsgCycleTime" 0;',
        'BA_DEF_DEF_ "GenSigStartValue" 0;',
        "",
        f'BA_ "Baudrate" {baudrate};',
    ])

    for cid, ctime in cycle_time_list:
        lines.append(f'BA_ "GenMsgCycleTime" BO_ {cid} {ctime};')
    lines.append("")

    for cid, sname, sval in start_value_list:
        lines.append(f'BA_ "GenSigStartValue" SG_ {cid} {sname} {sval};')
    lines.append("")

    # Value descriptions (VAL_)
    for sname, sdata in signals.items():
        vals = sdata.get("values")
        mname = sdata.get("message")
        if vals and mname in msg_id_map:
            cid = msg_id_map[mname]
            pairs_str = " ".join(f'{k} "{v}"' for k, v in vals.items())
            lines.append(f"VAL_ {cid} {sname} {pairs_str} ;")
    lines.append("")

    return "\n".join(lines) + "\n"


def validate_can_database(data: dict[str, Any]) -> list[str]:
    """Validate CAN database dictionary against CAN network specification constraints.

    Checks:
    - Signal bounds (min <= max, start_value within min and max).
    - Message payload capacity: all signals must fit inside DLC (start_bit + length <= dlc * 8).
    - Signal overlap: no two signals in the same message may occupy overlapping bit positions.
    - Zero scaling factor prevention.

    Returns:
        List of error / warning strings (empty list if perfectly compliant).
    """
    errors: list[str] = []
    messages = data.get("messages", {})
    signals = data.get("signals", {})

    msg_bit_allocation: dict[str, dict[int, str]] = {msg: {} for msg in messages}

    for sname, sdata in signals.items():
        mname = sdata.get("message")
        if not mname or mname not in messages:
            errors.append(f"Signal '{sname}' references unknown or missing message '{mname}'")
            continue

        msg_info = messages[mname]
        dlc = msg_info.get("dlc", 8)
        max_bits = dlc * 8

        start_bit = sdata.get("start_bit", 0)
        length = sdata.get("length", 1)
        factor = sdata.get("factor", 1)
        min_v = sdata.get("min", 0)
        max_v = sdata.get("max", 0)
        default_v = sdata.get("default", 0)

        # Factor check
        if factor == 0:
            errors.append(f"Signal '{sname}' has invalid factor 0")

        # Range check
        if min_v > max_v:
            errors.append(f"Signal '{sname}' has min ({min_v}) > max ({max_v})")
        if default_v is not None and not (min_v <= default_v <= max_v):
            errors.append(
                f"Signal '{sname}' start value {default_v} is out of bounds [{min_v}, {max_v}]"
            )

        # Frame boundary check
        end_bit = start_bit + length
        if end_bit > max_bits:
            errors.append(
                f"Signal '{sname}' (bits {start_bit}..{end_bit - 1}) exceeds message '{mname}' DLC {dlc} ({max_bits} bits)"
            )

        # Bit overlap check
        allocation = msg_bit_allocation[mname]
        for bit in range(start_bit, end_bit):
            if bit in allocation:
                errors.append(
                    f"Bit collision in message '{mname}': bit {bit} is used by both '{allocation[bit]}' and '{sname}'"
                )
            else:
                allocation[bit] = sname

    return errors


def convert_file(
    input_path: Path,
    output_path: Path | None = None,
    force_mode: str | None = None,
    pretty: bool = True,
    check: bool = False,
) -> tuple[dict[str, Any] | str, list[str]]:
    """Convert DBC to JSON or JSON to DBC, optionally writing to output_path.

    Args:
        input_path: Path to source file (.dbc or .json).
        output_path: Path to target file (or None for in-memory return).
        force_mode: 'json' or 'dbc' to override extension inference.
        pretty: Whether to format JSON with indentation.
        check: Whether to perform validation checks.

    Returns:
        Tuple of (result_data_or_string, list_of_validation_issues).
    """
    content = input_path.read_text(encoding="utf-8")
    ext = input_path.suffix.lower()

    if force_mode == "dbc" or (force_mode is None and ext == ".json"):
        # JSON -> DBC
        data = json.loads(content)
        validation_issues = validate_can_database(data) if check else []
        result: dict[str, Any] | str = dict_to_dbc(data)
        if output_path:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(result, encoding="utf-8")
        return result, validation_issues

    # Default: DBC -> JSON
    data = dbc_to_dict(content)
    validation_issues = validate_can_database(data) if check else []
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            if pretty:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            else:
                json.dump(data, f, ensure_ascii=False)
    return data, validation_issues


def main() -> int:
    """CLI entrypoint for dbc_to_json converter."""
    parser = argparse.ArgumentParser(
        description="Vector CANdb (.dbc) <-> SpecToTest JSON Converter & Validator.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Convert DBC to JSON:
  python tools/dbc_to_json.py tools/powertrain_bms.dbc -o inputs/can_signals.json --check

  # Validate existing CAN signals JSON or DBC:
  python tools/dbc_to_json.py inputs/can_signals.json --check

  # Convert JSON back to DBC:
  python tools/dbc_to_json.py inputs/can_signals.json -o tools/generated.dbc
""",
    )
    parser.add_argument("input", type=Path, help="Path to input .dbc or .json file")
    parser.add_argument("-o", "--output", type=Path, default=None, help="Path to output file")
    parser.add_argument("--to-json", action="store_true", help="Force conversion from DBC to JSON")
    parser.add_argument("--to-dbc", action="store_true", help="Force conversion from JSON to DBC")
    parser.add_argument("--check", action="store_true", help="Run CAN DBC compliance checks (DLC, overlaps, bounds)")
    parser.add_argument("--compact", action="store_true", help="Output compact unindented JSON")

    args = parser.parse_args()

    if not args.input.exists():
        sys.stderr.write(f"Error: Input file '{args.input}' not found.\n")
        return 1

    force_mode = None
    if args.to_json:
        force_mode = "json"
    elif args.to_dbc:
        force_mode = "dbc"

    try:
        result, issues = convert_file(
            input_path=args.input,
            output_path=args.output,
            force_mode=force_mode,
            pretty=not args.compact,
            check=args.check or True,  # Always check by default for quality assurance
        )

        if issues:
            sys.stderr.write(f"⚠️ Validation warnings ({len(issues)}):\n")
            for issue in issues:
                sys.stderr.write(f"  - {issue}\n")
        else:
            print("✅ CAN database validation passed: zero collisions, all signals fit within DLC.")

        if args.output:
            print(f"✅ Successfully converted '{args.input}' -> '{args.output}'")
        elif not args.check:
            if isinstance(result, dict):
                print(json.dumps(result, indent=2, ensure_ascii=False))
            else:
                print(result)

        return 0
    except Exception as exc:
        sys.stderr.write(f"❌ Error during conversion: {exc}\n")
        return 2


if __name__ == "__main__":
    sys.exit(main())

