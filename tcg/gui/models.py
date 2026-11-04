"""Data models, registry loaders, and state management for SpecToTest GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
import json
from pathlib import Path
import re
from typing import Any

from tcg.core.contracts import OperationContract, ParameterSpec
from tcg.core.mapping import (
    MAPPING_ID,
    NAME,
    PLACEHOLDER,
    _template,
    load_mappings,
    resolve,
)
from tcg.core.model import SpecError
from tcg.core.profile import ResourceProfile, parse_profile


@dataclass
class MappingItem:
    """Represents a single sentence-to-operation mapping in the GUI."""
    id: str
    template: str
    operation: str
    parameters: dict[str, str] = field(default_factory=dict)
    
    # Computed metadata
    is_valid: bool = False
    validation_error: str | None = None
    placeholders: list[str] = field(default_factory=list)
    allowed_phases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'template': self.template,
            'operation': self.operation,
            'parameters': dict(self.parameters),
        }


@dataclass
class OperationInfo:
    """Represents an operation contract from the registry for GUI display."""
    name: str
    docstring: str
    phases: list[str]
    parameters: list[ParameterSpec]
    linked_mappings: list[MappingItem] = field(default_factory=list)

    @property
    def is_mapped(self) -> bool:
        return len(self.linked_mappings) > 0

    @property
    def required_parameters(self) -> list[str]:
        return [p.name for p in self.parameters if p.required]

    @property
    def optional_parameters(self) -> list[str]:
        return [p.name for p in self.parameters if not p.required]


def load_registry_from_target(target: str) -> dict[str, OperationContract]:
    """Load an operation registry from a 'module.submodule:VARIABLE' string."""
    if ':' not in target:
        raise ValueError(f"Ungültiges Format für Registry: '{target}'. Erwartet: 'modul.name:VARIABLE'")
    mod_name, var_name = target.split(':', 1)
    module = importlib.import_module(mod_name)
    registry = getattr(module, var_name, None)
    if not isinstance(registry, dict):
        raise ValueError(f"'{target}' ist kein Dictionary / Registry-Objekt.")
    return registry


def load_profile_from_file(path: str | Path | None) -> ResourceProfile:
    """Load a ResourceProfile from JSON, or return an empty profile if None/missing."""
    if not path:
        return ResourceProfile('EMPTY', {})
    p = Path(path)
    if not p.exists():
        return ResourceProfile('EMPTY', {})
    text = p.read_text(encoding='utf-8')
    return parse_profile(text, name=p.name)


def extract_template_placeholders(template: str) -> list[str]:
    """Safely extract unique placeholder names in order of appearance."""
    placeholders = []
    for match in PLACEHOLDER.finditer(template):
        name = match[1]
        if name not in placeholders:
            placeholders.append(name)
    return placeholders


def validate_single_mapping(
    ident: str,
    template: str,
    operation: str,
    parameters: dict[str, str],
    registry: dict[str, OperationContract]
) -> tuple[bool, str | None, list[str]]:
    """Validate a single mapping definition against SpecToTest rules and registry.
    
    Returns (is_valid, error_message, placeholders).
    """
    if not ident or not MAPPING_ID.fullmatch(ident):
        return False, f"ID '{ident}' ungültig (erwartet: MAP_GROSSBUCHSTABEN)", []

    where = f"Mapping '{ident}'"
    try:
        literals, placeholders = _template(template, where)
    except SpecError as e:
        return False, "; ".join(e.problems), []
    except Exception as e:
        return False, str(e), []

    if operation not in registry:
        registered = ", ".join(sorted(registry))
        return False, f"Unbekannte Operation '{operation}'. Verfügbar: {registered}", list(placeholders)

    contract = registry[operation]

    # Validate parameters bindings
    for src, tgt in parameters.items():
        if not NAME.fullmatch(src):
            return False, f"Ungültiger Platzhaltername '{src}'", list(placeholders)
        if not NAME.fullmatch(tgt):
            return False, f"Ungültiger Parametername '{tgt}'", list(placeholders)

    if set(parameters) != set(placeholders):
        missing_bindings = set(placeholders) - set(parameters)
        extra_bindings = set(parameters) - set(placeholders)
        if missing_bindings:
            return False, f"Nicht zugewiesene Platzhalter: {', '.join(missing_bindings)}", list(placeholders)
        if extra_bindings:
            return False, f"Überflüssige Parameter-Zuweisungen: {', '.join(extra_bindings)}", list(placeholders)

    targets = [parameters[p] for p in placeholders]
    if len(targets) != len(set(targets)):
        return False, "Mehrere Platzhalter dürfen nicht auf denselben Operations-Parameter verweisen", list(placeholders)

    for target in targets:
        param = contract.parameter(target)
        if param is None:
            return False, f"Operation '{operation}' hat keinen Parameter namens '{target}'", list(placeholders)

    # Check required parameters
    missing_required = [
        p.name for p in contract.parameters
        if p.required and p.name not in targets
    ]
    if missing_required:
        return False, f"Erforderliche Parameter der Operation nicht gemappt: {', '.join(missing_required)}", list(placeholders)

    return True, None, list(placeholders)


class MappingStudioState:
    """Central data state for the GUI."""

    def __init__(
        self,
        registry_target: str = 'operations.registry:REGISTRY',
        mapping_file: str | Path | None = 'inputs/operation_mapping.toml',
        resources_file: str | Path | None = 'inputs/resources.json',
    ):
        self.registry_target = registry_target
        self.mapping_file: Path | None = Path(mapping_file) if mapping_file else None
        self.resources_file: Path | None = Path(resources_file) if resources_file else None
        
        self.registry: dict[str, OperationContract] = {}
        self.profile: ResourceProfile = ResourceProfile('EMPTY', {})
        self.mappings: list[MappingItem] = []
        self.operations: dict[str, OperationInfo] = {}
        self.is_dirty: bool = False

        self.reload_all()

    def reload_all(self):
        """Reload registry, profile, and mappings."""
        try:
            self.registry = load_registry_from_target(self.registry_target)
        except Exception as e:
            self.registry = {}
            print(f"Warnung: Konnte Registry '{self.registry_target}' nicht laden: {e}")

        try:
            self.profile = load_profile_from_file(self.resources_file)
        except Exception as e:
            self.profile = ResourceProfile('EMPTY', {})
            print(f"Warnung: Konnte Profil '{self.resources_file}' nicht laden: {e}")

        if self.mapping_file and self.mapping_file.exists():
            from tcg.gui.toml_io import load_mapping_file
            raw_mappings, err = load_mapping_file(self.mapping_file)
            if not err:
                self.set_mappings_from_dicts(raw_mappings)
            else:
                self.mappings = []
        else:
            self.mappings = []

        self.recalculate()
        self.is_dirty = False

    def set_mappings_from_dicts(self, dicts: list[dict[str, Any]]):
        """Populate mappings from a list of dictionaries."""
        self.mappings = [
            MappingItem(
                id=d.get('id', ''),
                template=d.get('template', ''),
                operation=d.get('operation', ''),
                parameters=dict(d.get('parameters', {})),
            )
            for d in dicts
        ]
        self.recalculate()

    def recalculate(self):
        """Validate mappings and build the bidirectional Operation -> Mappings index."""
        # 1. Build OperationInfo map
        self.operations = {}
        for op_name, contract in self.registry.items():
            doc = ''
            if contract.function and hasattr(contract.function, '__doc__') and contract.function.__doc__:
                doc = contract.function.__doc__.strip()
            self.operations[op_name] = OperationInfo(
                name=op_name,
                docstring=doc,
                phases=sorted(contract.phases),
                parameters=list(contract.parameters),
                linked_mappings=[],
            )

        # 2. Validate mappings and link to operations
        for item in self.mappings:
            is_valid, err, placeholders = validate_single_mapping(
                item.id, item.template, item.operation, item.parameters, self.registry
            )
            item.is_valid = is_valid
            item.validation_error = err
            item.placeholders = placeholders
            
            if item.operation in self.registry:
                contract = self.registry[item.operation]
                item.allowed_phases = sorted(contract.phases)
                if item.operation in self.operations:
                    self.operations[item.operation].linked_mappings.append(item)
            else:
                item.allowed_phases = []

    def get_mappings_dicts(self) -> list[dict[str, Any]]:
        return [m.to_dict() for m in self.mappings]

    def add_mapping(self, item: MappingItem) -> None:
        self.mappings.append(item)
        self.is_dirty = True
        self.recalculate()

    def update_mapping(self, index: int, item: MappingItem) -> None:
        if 0 <= index < len(self.mappings):
            self.mappings[index] = item
            self.is_dirty = True
            self.recalculate()

    def remove_mapping(self, index: int) -> None:
        if 0 <= index < len(self.mappings):
            self.mappings.pop(index)
            self.is_dirty = True
            self.recalculate()

    def test_sentence(self, sentence: str, phase: str | None = None) -> dict[str, Any]:
        """Test a natural language sentence against current valid mappings."""
        sentence = sentence.strip()
        if not sentence:
            return {
                'success': False,
                'matched': False,
                'error': 'Leerer Satz eingegeben.',
            }

        valid_dicts = [m.to_dict() for m in self.mappings if m.is_valid]
        if not valid_dicts:
            return {
                'success': False,
                'matched': False,
                'error': 'Keine gültigen Mappings zum Prüfen verfügbar.',
            }

        try:
            compiled_mappings = load_mappings(valid_dicts, self.registry, source='GUI_Test')
        except SpecError as e:
            return {
                'success': False,
                'matched': False,
                'error': f"Fehler in Mapping-Definitionen: {'; '.join(e.problems)}",
            }

        try:
            mapping, arguments = resolve(sentence, compiled_mappings, self.profile)
            arg_dict = dict(arguments)
            op_name = mapping.contract.id
            allowed_phases = sorted(mapping.contract.phases)

            phase_valid = True
            phase_msg = None
            if phase:
                if phase not in allowed_phases:
                    phase_valid = False
                    phase_msg = f"Operation '{op_name}' ist in Phase '{phase}' nicht erlaubt (erlaubt: {', '.join(allowed_phases)})"

            return {
                'success': True,
                'matched': True,
                'mapping_id': mapping.id,
                'template': mapping.template,
                'operation': op_name,
                'arguments': arg_dict,
                'allowed_phases': allowed_phases,
                'phase_valid': phase_valid,
                'phase_msg': phase_msg,
            }
        except SpecError as e:
            return {
                'success': False,
                'matched': False,
                'error': "; ".join(e.problems),
            }
        except Exception as e:
            return {
                'success': False,
                'matched': False,
                'error': f"Unerwarteter Fehler: {e}",
            }
