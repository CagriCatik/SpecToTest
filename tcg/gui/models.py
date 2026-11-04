"""Data models, registry loaders, and state management for SpecToTest GUI."""
from __future__ import annotations

from dataclasses import dataclass, field
import importlib
from pathlib import Path
import re
from typing import Any

from tcg.comm.catalog import COMM_CATALOG_KEY, load_catalog
from tcg.comm.model import EMPTY_CATALOG
from tcg.core.contracts import OperationContract, ParameterSpec, bind_registry
from tcg.core.mapping import (
    MAPPING_ID,
    NAME,
    PLACEHOLDER,
    _template,
    load_mappings,
    resolve,
)
from tcg.core.model import SpecError, VariableRef
from tcg.core.profile import ResourceProfile, parse_profile
from tcg.gui.profiles import ProjectProfile, get_builtin_profiles, test_validate_profile


@dataclass
class MappingItem:
    """Represents a single sentence-to-operation mapping in the GUI."""
    id: str
    template: str
    operation: str
    parameters: dict[str, str] = field(default_factory=dict)
    source_file: str = ''
    
    # Computed metadata
    is_valid: bool = False
    has_conflict: bool = False
    validation_error: str | None = None
    placeholders: list[str] = field(default_factory=list)
    allowed_phases: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = {
            'id': self.id,
            'template': self.template,
            'operation': self.operation,
            'parameters': dict(self.parameters),
        }
        if self.source_file:
            d['_source_file'] = self.source_file
        return d


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
        """Operation is only mapped if at least one valid, non-conflicting mapping exists."""
        return any(m.is_valid and not m.has_conflict for m in self.linked_mappings)

    @property
    def valid_mappings_count(self) -> int:
        return sum(1 for m in self.linked_mappings if m.is_valid and not m.has_conflict)

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
        project_profile: ProjectProfile | None = None,
        registry_target: str = 'operations.registry:REGISTRY',
        mapping_file: str | Path | None = 'inputs/operation_mapping.toml',
        resources_file: str | Path | None = 'inputs/resources.json',
    ):
        if project_profile is not None:
            self.profile_config = project_profile
            self.registry_target = project_profile.registry_target
            self.mapping_file = Path(project_profile.mapping_files[0]) if project_profile.mapping_files else None
            self.resources_file = Path(project_profile.resources_file) if project_profile.resources_file else None
        else:
            builtins = get_builtin_profiles()
            self.profile_config = builtins[0]
            self.registry_target = registry_target
            self.mapping_file = Path(mapping_file) if mapping_file else None
            self.resources_file = Path(resources_file) if resources_file else None

        self.registry: dict[str, OperationContract] = {}
        self.profile: ResourceProfile = ResourceProfile('EMPTY', {})
        self.catalog = None
        self.catalog_error: str | None = None
        self.mappings: list[MappingItem] = []
        self.operations: dict[str, OperationInfo] = {}
        self.is_dirty: bool = False

        self.reload_all()

    def set_project_profile(self, profile: ProjectProfile) -> tuple[bool, str | None]:
        """Atomically switch to a new ProjectProfile.
        
        Strictly validates loading of all components BEFORE touching state.
        If validation fails, state remains 100% untouched!
        """
        ok, err, artifacts = test_validate_profile(profile)
        if not ok:
            return False, err

        # Commit state change atomically
        self.profile_config = profile
        self.registry_target = profile.registry_target
        # The registry from test_validate_profile is already bound to this project's
        # CAN signal catalog, so no separate configuration step can fall out of step.
        self.registry = artifacts['registry']
        self.profile = artifacts['profile']
        self.catalog = artifacts.get('catalog')
        self.catalog_error = None
        self.mapping_file = Path(profile.mapping_files[0]) if profile.mapping_files else None
        self.resources_file = Path(profile.resources_file) if profile.resources_file else None

        self.set_mappings_from_dicts(artifacts['raw_mappings'])
        self.is_dirty = False
        return True, None

    def _load_catalog(self):
        """Load the active project's CAN signal catalog and bind the registry to it.

        On failure the catalog is dropped and the error recorded: the registry is bound
        to an unconfigured catalog, so CAN operations fail with a clear message instead
        of silently reusing the catalog of a previous project.
        """
        self.catalog = None
        self.catalog_error = None
        profile = self.profile_config
        try:
            descriptions = profile.description_configs() if profile is not None else ()
        except SpecError as error:
            descriptions = ()
            self.catalog_error = f'Kommunikationskonfiguration: {error}'
        if descriptions and not self.catalog_error:
            try:
                self.catalog = load_catalog(
                    descriptions, base_dir=profile.base_dir or None,
                    aliases=getattr(profile, 'aliases', None))
            except SpecError as error:
                self.catalog_error = f'Kommunikationsbeschreibung: {error}'
            except Exception as error:
                self.catalog_error = f'Kommunikationsbeschreibung: {error}'
        if self.catalog_error:
            self.catalog = None
            print(f'Fehler: {self.catalog_error}')
        if self.registry:
            self.registry = bind_registry(
                self.registry,
                {COMM_CATALOG_KEY: self.catalog or EMPTY_CATALOG})

    @property
    def communication_available(self) -> bool:
        """Whether symbolic CAN states can be resolved for the active project."""
        return self.catalog is not None and self.catalog_error is None

    def catalog_status_text(self) -> str:
        """A readable status line for the GUI; never colour alone."""
        if self.catalog_error:
            return f"Kommunikationskatalog: Fehler - {self.catalog_error}"
        if self.catalog is None:
            return "Kommunikationskatalog: nicht konfiguriert - symbolische Zustände nicht verfügbar"
        return (f"Kommunikationskatalog: geladen - {len(self.catalog.resources)} "
                f"Objekte aus {self.catalog.source}")

    def reload_all(self):
        """Reload registry, profile, and all mapping files of the active profile."""
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

        self._load_catalog()

        all_raw = []
        from tcg.gui.toml_io import load_mapping_file

        mapping_paths = self.profile_config.mapping_files if self.profile_config else []
        if not mapping_paths and self.mapping_file:
            mapping_paths = [str(self.mapping_file)]

        for mf in mapping_paths:
            p = Path(mf)
            if p.is_file():
                raw, err = load_mapping_file(p)
                if not err:
                    for entry in raw:
                        entry['_source_file'] = str(p)
                        all_raw.append(entry)

        if all_raw:
            self.set_mappings_from_dicts(all_raw)
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
                source_file=d.get('_source_file', ''),
            )
            for d in dicts
        ]
        self.recalculate()

    def recalculate(self):
        """Validate mappings, identify duplicate ID conflicts, and build the bidirectional index."""
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

        # 2. Count ID occurrences to detect project-wide duplicate ID conflicts
        id_counts: dict[str, int] = {}
        for item in self.mappings:
            clean_id = item.id.strip()
            if clean_id:
                id_counts[clean_id] = id_counts.get(clean_id, 0) + 1

        # 3. Validate individual mappings and attach conflict markers
        for item in self.mappings:
            is_valid, err, placeholders = validate_single_mapping(
                item.id, item.template, item.operation, item.parameters, self.registry
            )
            clean_id = item.id.strip()
            has_conflict = id_counts.get(clean_id, 0) > 1

            if has_conflict:
                is_valid = False
                conflict_msg = f"Konflikt: Mapping-ID '{clean_id}' ist mehrfach vergeben."
                err = f"{err}; {conflict_msg}" if err else conflict_msg

            item.is_valid = is_valid
            item.has_conflict = has_conflict
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
        if not item.source_file:
            if self.mapping_file:
                item.source_file = str(self.mapping_file)
            elif self.profile_config and self.profile_config.mapping_files:
                item.source_file = self.profile_config.mapping_files[0]
        self.mappings.append(item)
        self.is_dirty = True
        self.recalculate()

    def update_mapping(self, index: int, item: MappingItem) -> None:
        if 0 <= index < len(self.mappings):
            if not item.source_file and self.mappings[index].source_file:
                item.source_file = self.mappings[index].source_file
            self.mappings[index] = item
            self.is_dirty = True
            self.recalculate()

    def remove_mapping(self, index: int) -> None:
        if 0 <= index < len(self.mappings):
            self.mappings.pop(index)
            self.is_dirty = True
            self.recalculate()

    def save_all_mapping_files(self) -> tuple[bool, str]:
        """Save all mappings back to their respective source files.
        
        Preserves the source_file origin of each mapping so multi-file profiles
        are cleanly separated without duplicating mappings across files.
        """
        from tcg.gui.toml_io import save_mapping_file

        target_paths: list[Path] = []
        if self.profile_config and self.profile_config.mapping_files:
            target_paths = [Path(f) for f in self.profile_config.mapping_files]
        elif self.mapping_file:
            target_paths = [Path(self.mapping_file)]

        if not target_paths:
            return False, "Keine Zieldatei zum Speichern definiert."

        primary_file = target_paths[0]
        resolved_targets: dict[Path, Path] = {p.resolve(): p for p in target_paths}
        grouped: dict[Path, list[dict[str, Any]]] = {p.resolve(): [] for p in target_paths}

        for item in self.mappings:
            d = item.to_dict()
            d.pop('_source_file', None)
            if item.source_file:
                item_p = Path(item.source_file).resolve()
            else:
                item_p = primary_file.resolve()

            if item_p not in grouped:
                grouped[item_p] = []
                resolved_targets[item_p] = Path(item.source_file)

            grouped[item_p].append(d)

        saved_files: list[str] = []
        for res_path, entries in grouped.items():
            file_path = resolved_targets[res_path]
            success, msg = save_mapping_file(file_path, entries)
            if not success:
                return False, f"Fehler beim Speichern von '{file_path.name}': {msg}"
            saved_files.append(file_path.name)

        self.is_dirty = False
        names_str = ", ".join(f"'{name}'" for name in saved_files)
        return True, f"Erfolgreich {len(self.mappings)} Mappings in {len(saved_files)} Datei(en) ({names_str}) gespeichert."

    def test_sentence(self, sentence: str, phase: str | None = None) -> dict[str, Any]:
        """Test a natural language sentence against current valid mappings.
        
        Distinguishes between:
        1. Fully resolved literal values (e.g. 13.8V, 500 ms)
        2. Structural template matches with contextual variables (e.g. VariableRef('missing'))
        3. Syntax/grammar mismatch
        """
        sentence = sentence.strip()
        if not sentence:
            return {
                'success': False,
                'matched': False,
                'error': 'Leerer Satz eingegeben.',
            }

        valid_dicts = [m.to_dict() for m in self.mappings if m.is_valid and not m.has_conflict]
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

            # Check if any argument contains a VariableRef (unbound variable outside loop context)
            var_refs = [v.name for _, v in arguments if isinstance(v, VariableRef)]
            if var_refs:
                var_names_str = ", ".join(f"'{v}'" for v in var_refs)
                return {
                    'success': True,
                    'matched': True,
                    'is_contextual_variable': True,
                    'variable_names': var_refs,
                    'mapping_id': mapping.id,
                    'template': mapping.template,
                    'operation': op_name,
                    'arguments': arg_dict,
                    'allowed_phases': allowed_phases,
                    'phase_valid': False,
                    'status_text': f"Satzmuster erkannt; Variable {var_names_str} benötigt einen gültigen Kontext (z.B. Schleife).",
                }

            phase_valid = True
            phase_msg = None
            if phase:
                if phase not in allowed_phases:
                    phase_valid = False
                    phase_msg = f"Operation '{op_name}' ist in Phase '{phase}' nicht erlaubt (erlaubt: {', '.join(allowed_phases)})"

            return {
                'success': True,
                'matched': True,
                'is_contextual_variable': False,
                'mapping_id': mapping.id,
                'template': mapping.template,
                'operation': op_name,
                'arguments': arg_dict,
                'allowed_phases': allowed_phases,
                'phase_valid': phase_valid,
                'phase_msg': phase_msg,
                'status_text': "Satzmuster erkannt und Parameter vollständig validiert.",
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
