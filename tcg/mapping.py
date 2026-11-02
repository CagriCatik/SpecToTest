"""Exact template matching and explicit placeholder-to-parameter mapping."""
from dataclasses import dataclass
import re

from .model import SpecError

MAPPING_COLUMNS = ('Mapping_ID', 'Vorlage', 'Operation', 'Parameterzuordnung')
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
    row: int


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


def _bindings(text, placeholders, contract, where):
    bindings = {}
    if text != '-':
        for entry in text.split(';'):
            if entry.count('=') != 1:
                raise SpecError(f'{where}: mappings use placeholder=parameter pairs separated by semicolons')
            source, target = entry.split('=')
            if not NAME.fullmatch(source) or not NAME.fullmatch(target):
                raise SpecError(f'{where}: invalid parameter mapping {entry!r}')
            if source in bindings:
                raise SpecError(f'{where}: placeholder {source!r} mapped more than once')
            bindings[source] = target
    if set(bindings) != set(placeholders):
        raise SpecError(f'{where}: mappings must name exactly these placeholders: {", ".join(placeholders) or "none"}')
    targets = tuple(bindings[source] for source in placeholders)
    if len(targets) != len(set(targets)):
        raise SpecError(f'{where}: multiple placeholders map to one operation parameter')
    parameters = []
    for target in targets:
        parameter = contract.parameter(target)
        if parameter is None:
            raise SpecError(f'{where}: unknown operation parameter {target!r} for {contract.id}')
        parameters.append(parameter)
    missing = [parameter.name for parameter in contract.parameters if parameter.required and parameter.name not in targets]
    if missing:
        raise SpecError(f'{where}: required operation parameters not mapped: {", ".join(missing)}')
    return tuple(parameters)


def load_mappings(rows, registry):
    mappings, problems, identifiers = [], [], {}
    for row, data in rows:
        where = f'Mapping!{row}'
        try:
            ident, template, operation, parameter_map = (single_line_text(data[column], f'{where} {column}') for column in MAPPING_COLUMNS)
            if not MAPPING_ID.fullmatch(ident):
                raise SpecError(f'{where}: Mapping_ID {ident!r} must match {MAPPING_ID.pattern}')
            if ident in identifiers:
                raise SpecError(f'{where}: duplicate Mapping_ID {ident!r} (first in row {identifiers[ident]})')
            identifiers[ident] = row
            if operation not in registry:
                raise SpecError(f'{where}: unknown operation {operation!r}; registered: {", ".join(sorted(registry))}')
            literals, placeholders = _template(template, where)
            parameters = _bindings(parameter_map, placeholders, registry[operation], where)
            mappings.append(Mapping(ident, template, registry[operation], literals, placeholders, parameters, row))
        except SpecError as error:
            problems.extend(error.problems)
    if problems:
        raise SpecError(problems)
    if not mappings:
        raise SpecError('Mapping: no mappings defined')
    return tuple(mappings)


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
    for parameter, value in zip(mapping.parameters, values):
        try:
            converted[parameter.name] = parameter.type.convert(value, profile)
        except SpecError as error:
            problems.extend(f'{mapping.id}.{parameter.name}: {problem}' for problem in error.problems)
    if problems:
        raise SpecError(problems)
    arguments = tuple((parameter.name, converted.get(parameter.name, parameter.default)) for parameter in mapping.contract.parameters)
    return mapping, arguments
