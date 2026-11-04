"""Exact TOML mapping, placeholder binding and deterministic type conversion."""
from dataclasses import dataclass
import re
import tomllib

from .model import SpecError
from .parameters import reset_step_context, set_step_context


MAPPING_KEYS = frozenset({'id', 'template', 'operation', 'parameters'})
MAPPING_ID = re.compile(r'[A-Z][A-Z0-9_]*')
PLACEHOLDER = re.compile(r'\{([a-z][a-z0-9_]*)\}')
NAME = re.compile(r'[a-z][a-z0-9_]*')


@dataclass(frozen=True)
class Mapping:
    id: str
    template: str
    contract: object
    literals: tuple
    placeholders: tuple
    parameters: tuple
    entry: int


def single_line_text(value, where):
    if not isinstance(value, str):
        raise SpecError(f'{where}: expected text, got {type(value).__name__} {value!r}')
    if value.splitlines() != [value] or any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise SpecError(f'{where}: must be one line without control characters')
    if value != value.strip():
        raise SpecError(f'{where}: leading or trailing whitespace is not allowed')
    return value


def _template(template, where):
    literals, placeholders, end = [], [], 0
    for match in PLACEHOLDER.finditer(template):
        literal, placeholder = template[end:match.start()], match[1]
        if placeholder in placeholders:
            raise SpecError(f'{where}: placeholder {{{placeholder}}} occurs more than once')
        if placeholders and not literal:
            raise SpecError(f'{where}: placeholders must be separated by literal text')
        literals.append(literal)
        placeholders.append(placeholder)
        end = match.end()
    literals.append(template[end:])
    if any('{' in literal or '}' in literal for literal in literals):
        raise SpecError(f'{where}: unbalanced braces in template')
    if not ''.join(literals).strip():
        raise SpecError(f'{where}: template needs literal text')
    return tuple(literals), tuple(placeholders)


def _bindings(bindings, placeholders, contract, where):
    if not isinstance(bindings, dict):
        raise SpecError(f'{where}: parameters must be a TOML table')
    for source, target in bindings.items():
        if not isinstance(source, str) or not NAME.fullmatch(source):
            raise SpecError(f'{where}: invalid placeholder name {source!r}')
        if not isinstance(target, str) or not NAME.fullmatch(target):
            raise SpecError(f'{where}: invalid operation parameter {target!r}')
    if set(bindings) != set(placeholders):
        raise SpecError(f'{where}: parameters must name exactly these placeholders: '
                        f'{", ".join(placeholders) or "none"}')
    targets = tuple(bindings[source] for source in placeholders)
    if len(targets) != len(set(targets)):
        raise SpecError(f'{where}: multiple placeholders map to one operation parameter')
    parameters = []
    for target in targets:
        parameter = contract.parameter(target)
        if parameter is None:
            raise SpecError(f'{where}: unknown operation parameter {target!r} for {contract.id}')
        parameters.append(parameter)
    missing = [parameter.name for parameter in contract.parameters
               if parameter.required and parameter.name not in targets]
    if missing:
        raise SpecError(f'{where}: required operation parameters not mapped: {", ".join(missing)}')
    return tuple(parameters)


def parse_mapping_document(text, name='mapping.toml'):
    try:
        document = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise SpecError(f'{name}: invalid TOML: {error}') from None
    if set(document) != {'mapping'} or not isinstance(document['mapping'], list) or not document['mapping']:
        raise SpecError(f'{name}: expected one or more [[mapping]] tables and no other top-level keys')
    entries, problems = [], []
    for index, entry in enumerate(document['mapping'], 1):
        if not isinstance(entry, dict) or set(entry) != MAPPING_KEYS:
            found = sorted(entry) if isinstance(entry, dict) else type(entry).__name__
            problems.append(f'{name}:mapping[{index}]: expected exactly {sorted(MAPPING_KEYS)}, got {found}')
        else:
            entries.append(entry)
    if problems:
        raise SpecError(problems)
    return tuple(entries)


def load_mappings(entries, registry, source='mapping.toml'):
    mappings, problems, identifiers = [], [], {}
    for index, data in enumerate(entries, 1):
        where = f'{source}:mapping[{index}]'
        try:
            ident = single_line_text(data['id'], f'{where}.id')
            template = single_line_text(data['template'], f'{where}.template')
            operation = single_line_text(data['operation'], f'{where}.operation')
            if not MAPPING_ID.fullmatch(ident):
                raise SpecError(f'{where}: id {ident!r} must match {MAPPING_ID.pattern}')
            if ident in identifiers:
                raise SpecError(f'{where}: duplicate id {ident!r} (first entry {identifiers[ident]})')
            identifiers[ident] = index
            if operation not in registry:
                raise SpecError(f'{where}: unknown operation {operation!r}; registered: '
                                f'{", ".join(sorted(registry))}')
            literals, placeholders = _template(template, where)
            parameters = _bindings(data['parameters'], placeholders, registry[operation], where)
            mappings.append(Mapping(ident, template, registry[operation], literals,
                                    placeholders, parameters, index))
        except SpecError as error:
            problems.extend(error.problems)
    if problems:
        raise SpecError(problems)
    return tuple(mappings)


def load_mapping_files(paths, registry):
    """Load one or more TOML mapping files and ensure globally unique mapping IDs."""
    from pathlib import Path
    if isinstance(paths, (str, Path)):
        paths = [Path(paths)]
    paths = [Path(p) for p in paths]
    all_mappings = []
    identifiers = {}
    problems = []

    for path in paths:
        if path.suffix.lower() != '.toml':
            problems.append(f'{path.name}: operation mapping must be a .toml file')
            continue
        try:
            text = path.read_text(encoding='utf-8-sig')
        except OSError as error:
            problems.append(f'{path.name}: cannot read mapping ({error.strerror})')
            continue
        try:
            entries = parse_mapping_document(text, path.name)
        except SpecError as error:
            problems.extend(error.problems)
            continue

        for index, data in enumerate(entries, 1):
            where = f'{path.name}:mapping[{index}]'
            try:
                ident = single_line_text(data['id'], f'{where}.id')
                template = single_line_text(data['template'], f'{where}.template')
                operation = single_line_text(data['operation'], f'{where}.operation')
                if not MAPPING_ID.fullmatch(ident):
                    raise SpecError(f'{where}: id {ident!r} must match {MAPPING_ID.pattern}')
                if ident in identifiers:
                    first_where = identifiers[ident]
                    raise SpecError(f'{where}: duplicate mapping id {ident!r} (already defined in {first_where})')
                identifiers[ident] = where
                if operation not in registry:
                    raise SpecError(f'{where}: unknown operation {operation!r}; registered: '
                                    f'{", ".join(sorted(registry))}')
                literals, placeholders = _template(template, where)
                parameters = _bindings(data['parameters'], placeholders, registry[operation], where)
                all_mappings.append(Mapping(ident, template, registry[operation], literals,
                                            placeholders, parameters, index))
            except SpecError as error:
                problems.extend(error.problems)

    if problems:
        raise SpecError(problems)

    # Sort mappings by id for deterministic evaluation order across mapping file permutations
    return tuple(sorted(all_mappings, key=lambda m: m.id))


def load_mapping(path_or_paths, registry):
    """Backwards-compatible loader accepting a single Path or iterable of Paths."""
    return load_mapping_files(path_or_paths, registry)


def _splits(text, mapping):
    if not text.startswith(mapping.literals[0]):
        return
    lexers = [parameter.type.lexical for parameter in mapping.parameters]

    def walk(position, index, values):
        if index == len(lexers):
            if position == len(text):
                yield tuple(values)
            return
        tail = mapping.literals[index + 1]
        if index + 1 == len(lexers):
            ends = (len(text) - len(tail),) if text.endswith(tail) else ()
        else:
            ends, found = [], text.find(tail, position + 1)
            while found != -1:
                ends.append(found)
                found = text.find(tail, found + 1)
        for end in ends:
            value = text[position:end]
            if end > position and lexers[index].fullmatch(value):
                yield from walk(end + len(tail), index + 1, values + [value])
    yield from walk(len(mapping.literals[0]), 0, [])


def resolve(text, mappings, profile):
    found = [(mapping, values) for mapping in mappings for values in _splits(text, mapping)]
    if not found:
        raise SpecError(f'no mapping template exactly matches {text!r}')
    if len(found) != 1:
        details = '; '.join(mapping.id for mapping, _ in sorted(found, key=lambda item: item[0].id))
        raise SpecError(f'ambiguous: {len(found)} template matches for {text!r}: {details}')
    mapping, values = found[0]
    converted, problems = {}, []

    # Map placeholders to their raw matched values and store in sentence-level context
    raw_params = {parameter.name: value for parameter, value in zip(mapping.parameters, values)}
    token = set_step_context(raw_params)

    # Dependency ordering: reference/resource parameters (e.g. 'signal', Resource types)
    # are converted first, so dependent values always find their reference in context.
    def _param_priority(item):
        param, _ = item
        if param.name == 'signal' or getattr(param.type, 'kind', None) is not None:
            return 0
        return 1

    ordered_pairs = sorted(zip(mapping.parameters, values), key=_param_priority)
    try:
        for parameter, value in ordered_pairs:
            try:
                converted[parameter.name] = parameter.type.convert(value, profile)
            except SpecError as error:
                problems.extend(f'{mapping.id}.{parameter.name}: {problem}' for problem in error.problems)
    finally:
        reset_step_context(token)

    if problems:
        raise SpecError(problems)
    arguments = tuple((parameter.name, converted.get(parameter.name, parameter.default))
                      for parameter in mapping.contract.parameters)
    return mapping, arguments
