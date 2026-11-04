"""TOML read, write and backup utilities for SpecToTest mapping files."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
from typing import Any

from tcg.core.mapping import parse_mapping_document
from tcg.core.model import SpecError


def serialize_mappings(mappings: list[dict[str, Any]]) -> str:
    """Serialize a list of mapping dicts to standard TOML.
    
    Each mapping contains:
      - id: str (e.g. 'MAP_SUPPLY')
      - template: str (e.g. 'Versorgung auf {spannung} setzen')
      - operation: str (e.g. 'set_supply')
      - parameters: dict[str, str] (e.g. {'spannung': 'value'})
    """
    blocks = []
    for m in mappings:
        ident = m['id'].strip()
        raw_template = m['template'].strip()
        escaped_template = raw_template.replace('\\', '\\\\').replace('"', '\\"')
        operation = m['operation'].strip()
        params = m.get('parameters', {})
        if params:
            param_items = [f'{k} = "{v}"' for k, v in params.items()]
            param_str = f"{{ {', '.join(param_items)} }}"
        else:
            param_str = "{}"

        block = (
            f"[[mapping]]\n"
            f'id = "{ident}"\n'
            f'template = "{escaped_template}"\n'
            f'operation = "{operation}"\n'
            f'parameters = {param_str}\n'
        )
        blocks.append(block)

    return '\n'.join(blocks)


def load_mapping_file(path: str | Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load and parse mappings from a TOML file.
    
    Returns (mappings_list, error_message).
    """
    p = Path(path)
    if not p.exists():
        return [], f"Datei nicht gefunden: {p}"
    try:
        text = p.read_text(encoding='utf-8-sig')
        entries = parse_mapping_document(text, name=p.name)
        # Convert tuples to mutable list of dicts for GUI editing
        return [dict(e) for e in entries], None
    except SpecError as e:
        return [], "; ".join(e.problems)
    except Exception as e:
        return [], f"Fehler beim Lesen: {e}"


def save_mapping_file(path: str | Path, mappings: list[dict[str, Any]], create_backup: bool = True) -> tuple[bool, str]:
    """Save mappings to a TOML file with optional backup.
    
    Validates TOML before writing.
    Returns (success: bool, message: str).
    """
    p = Path(path)
    try:
        content = serialize_mappings(mappings)
        # Validate that the generated TOML is strictly parseable
        parse_mapping_document(content, name=p.name)
    except SpecError as e:
        return False, f"Ungültiges TOML generiert: {'; '.join(e.problems)}"
    except Exception as e:
        return False, f"Validierungsfehler: {e}"

    try:
        # Create backup if target file exists
        if create_backup and p.exists():
            backup_path = p.with_suffix(p.suffix + '.bak')
            shutil.copy2(p, backup_path)

        p.parent.mkdir(parents=True, exist_ok=True)
        # Write via temp file for atomic replacement
        temp_path = p.with_suffix(p.suffix + '.tmp')
        temp_path.write_text(content, encoding='utf-8')
        os.replace(temp_path, p)
        return True, f"Erfolgreich {len(mappings)} Mappings in '{p.name}' gespeichert."
    except Exception as e:
        return False, f"Fehler beim Schreiben der Datei: {e}"
