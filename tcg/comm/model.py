"""Technology-neutral model for communication resources.

Four levels are kept strictly apart, because conflating them is what makes bus
support leak into the generic compiler:

1. `Technology`  -- CAN, LIN, Ethernet: the communication technology.
2. Description format -- DBC, LDF, ARXML: handled only by importers in
   `tcg.comm.importers`, never by the compiler.
3. `ObjectKind`  -- signal, frame, PDU, service, method, event, field: what the
   resource *is*. An Ethernet service is never modelled as a numeric CAN signal.
4. `Capability`  -- what a test bench must be able to do to serve an operation.

A resource is identified by its place in the project, not by its bare name: the
same signal name may legitimately exist in several networks or frames. Use
`ResourceRef` to address one, qualified as far as needed.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from decimal import Decimal, InvalidOperation
from enum import Enum
import re
from types import MappingProxyType

from tcg.core.model import SpecError

#: Separator for qualified references, e.g. ``PowertrainCAN::VehicleSpeed``.
REFERENCE_SEPARATOR = '::'

#: A single reference segment: an ordinary identifier.
SEGMENT_PATTERN = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')

#: A whole reference, qualified or not. Used as the lexical pattern of reference
#: parameters, so sentences may name either ``VehicleSpeed`` or ``BodyLIN::DoorState``.
REFERENCE_PATTERN = re.compile(
    r'[A-Za-z_][A-Za-z0-9_]*(?:::[A-Za-z_][A-Za-z0-9_]*)*')


class Technology(str, Enum):
    """The communication technology a resource belongs to."""
    CAN = 'can'
    LIN = 'lin'
    ETHERNET = 'ethernet'

    def __str__(self):
        return self.value


class ObjectKind(str, Enum):
    """What the communication object actually is."""
    SIGNAL = 'signal'
    FRAME = 'frame'
    PDU = 'pdu'
    SERVICE = 'service'
    METHOD = 'method'
    EVENT = 'event'
    FIELD = 'field'
    SCHEDULE = 'schedule'

    def __str__(self):
        return self.value


class Capability(str, Enum):
    """What a test bench must support to serve an operation.

    A loaded description says nothing about what the bench can do; these are
    checked separately at the bench adapter boundary.
    """
    READ_SIGNAL = 'read_signal'
    WRITE_SIGNAL = 'write_signal'
    SEND_FRAME = 'send_frame'
    SET_LIN_SCHEDULE = 'set_lin_schedule'
    CALL_METHOD = 'call_method'
    SUBSCRIBE_EVENT = 'subscribe_event'

    def __str__(self):
        return self.value


def normalise_state(text):
    """The one normalisation used for both loading and lookup of symbolic states.

    Surrounding whitespace is ignored, inner spaces are equated with underscores and
    case is ignored. Because this folds spellings together, a description whose
    declared names collide under it is rejected at import time instead of letting one
    mapping silently overwrite another.
    """
    return str(text).strip().replace(' ', '_').casefold()


def _decimal(value, where):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise SpecError(f'{where}: {value!r} is not a number')
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        raise SpecError(f'{where}: {value!r} is not a number') from None
    if not number.is_finite():
        raise SpecError(f'{where}: {value!r} is not finite')
    return number


@dataclass(frozen=True)
class ValueEncoding:
    """How a resource's value is represented on the bus and towards the tester.

    `factor` and `offset` relate the two: ``physical = raw * factor + offset``.
    Symbolic states are always stored as **raw** values, exactly as the description
    declares them.
    """
    data_type: str = 'number'          # number | boolean | text | opaque | void
    unit: str | None = None
    factor: Decimal = Decimal('1')
    offset: Decimal = Decimal('0')
    minimum: Decimal | None = None     # physical
    maximum: Decimal | None = None     # physical
    states: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))
    declared_states: tuple = ()

    @property
    def is_scaled(self):
        return self.factor != Decimal('1') or self.offset != Decimal('0')

    def raw_to_physical(self, raw):
        return _decimal(raw, 'raw value') * self.factor + self.offset

    def physical_to_raw(self, physical):
        if self.factor == 0:
            raise SpecError('encoding factor must not be zero')
        return (_decimal(physical, 'physical value') - self.offset) / self.factor

    def state_raw(self, text):
        """The raw value declared for `text`, or None if this resource declares none."""
        return self.states.get(normalise_state(text))

    def state_physical(self, text):
        raw = self.state_raw(text)
        return None if raw is None else self.raw_to_physical(raw)

    def declares_state(self, text):
        return normalise_state(text) in self.states


VOID_ENCODING = ValueEncoding(data_type='void')


@dataclass(frozen=True)
class CommunicationResource:
    """One addressable communication object of one project.

    Not every resource carries every property: a service has no unit or range, a
    continuous signal has no symbolic states.
    """
    name: str
    technology: Technology
    network: str
    kind: ObjectKind
    source: str                         # description file this came from
    container: str | None = None        # frame / PDU / service it belongs to
    encoding: ValueEncoding | None = None
    attributes: MappingProxyType = field(default_factory=lambda: MappingProxyType({}))

    @property
    def adapter_address(self):
        """The address the bench adapter uses, from this resource's own description.

        `adapter_naming` comes from the description's configuration:
        ``local`` (default, the bare name), ``qualified`` (the full reference) or
        ``prefixed`` (``Network_Name``). An explicit entry in ``adapter_names``
        overrides all of them. Nothing here depends on other networks.
        """
        explicit = self.attributes.get('adapter_address')
        if explicit:
            return str(explicit)
        policy = self.attributes.get('adapter_naming') or 'local'
        if policy == 'qualified':
            return self.qualified_name
        if policy == 'prefixed':
            return f'{self.network}_{self.name}'
        return self.name

    @property
    def qualified_name(self):
        """The fully qualified reference; always unique within a project."""
        parts = [self.network] + ([self.container] if self.container else []) + [self.name]
        return REFERENCE_SEPARATOR.join(parts)

    @property
    def identity(self):
        return (self.technology, self.network, self.container, self.kind, self.name)

    def reference_forms(self):
        """Every spelling that may address this resource, shortest first."""
        forms = [self.name]
        if self.container:
            forms.append(REFERENCE_SEPARATOR.join((self.container, self.name)))
        forms.append(REFERENCE_SEPARATOR.join((self.network, self.name)))
        if self.container:
            forms.append(self.qualified_name)
        return tuple(dict.fromkeys(forms))

    def describe(self):
        """A short, readable origin description for error messages and the GUI."""
        kind = f'{self.technology} {self.kind}'
        return f'{self.qualified_name} ({kind}, aus {self.source})'


class ResourceAddress(str):
    """The adapter address of one resource, carrying the resource it came from.

    Generated code renders it as a plain string, so emitted test code is unchanged.
    Dependent parameter types read `.resource` instead of resolving the address
    again -- an address is an adapter-side name and must never be fed back into
    reference resolution.
    """
    __slots__ = ('resource',)

    def __new__(cls, address, resource):
        value = super().__new__(cls, address)
        value.resource = resource
        return value


@dataclass(frozen=True)
class DescriptionSource:
    """One loaded (or failed) communication description of the active project."""
    name: str                   # file name
    path: str
    format: str                 # importer id, e.g. 'dbc', 'ldf', 'arxml', 'can_json'
    network: str
    technology: Technology | None = None
    resource_count: int = 0
    error: str | None = None

    @property
    def loaded(self):
        return self.error is None

    def status_text(self):
        if self.error:
            return f'{self.name} ({self.network}): Fehler - {self.error}'
        return (f'{self.name} ({self.network}, {self.format}): geladen, '
                f'{self.resource_count} Objekte')


class CommunicationCatalog:
    """All communication resources of one project, from any number of descriptions.

    Immutable once built. Resolution is explicit: an unqualified name works only
    while it is unambiguous, and an ambiguous reference names the alternatives.
    """

    def __init__(self, resources=(), sources=(), aliases=None, configured=True):
        self._resources = tuple(resources)
        self.sources = tuple(sources)
        self.aliases = MappingProxyType(dict(aliases or {}))
        self.configured = bool(configured)

        index = {}
        for resource in self._resources:
            for form in resource.reference_forms():
                index.setdefault(form, []).append(resource)
        self._index = MappingProxyType({key: tuple(value) for key, value in index.items()})

        # Adapter addresses. These are a property of each description's own naming
        # policy, never of what else happens to be loaded, so adding a network cannot
        # silently re-address resources that were already working.
        addresses, owners, collisions = {}, {}, []
        for resource in self._resources:
            address = resource.adapter_address
            addresses[resource.identity] = address
            previous = owners.get((resource.technology, address))
            if previous is not None and previous.identity != resource.identity:
                collisions.append(
                    f'Adapteradresse {address!r} ist mehrfach belegt: '
                    f'{previous.qualified_name} und {resource.qualified_name}; '
                    f'setze "adapter_naming" oder "adapter_names" für eine der '
                    f'Beschreibungen')
            else:
                owners[(resource.technology, address)] = resource
        self._addresses = MappingProxyType(addresses)
        self.address_collisions = tuple(collisions)

    def __len__(self):
        return len(self._resources)

    @property
    def resources(self):
        return self._resources

    def networks(self):
        return tuple(sorted({resource.network for resource in self._resources}))

    def technologies(self):
        return tuple(sorted({resource.technology.value for resource in self._resources}))

    def failed_sources(self):
        return tuple(source for source in self.sources if not source.loaded)

    def resources_of(self, network=None, technology=None, kind=None):
        return tuple(resource for resource in self._resources
                     if (network is None or resource.network == network)
                     and (technology is None or resource.technology == technology)
                     and (kind is None or resource.kind == kind))

    def candidates(self, reference, technology=None, kind=None):
        """Every resource addressed by `reference`, after alias expansion.

        `technology` and `kind` narrow the search to what the calling operation can
        actually use, so an Ethernet service never competes with a CAN signal of the
        same name.
        """
        text = str(reference).strip()
        target = self.aliases.get(text, text)
        matches = self._index.get(target, ())
        if technology is not None:
            technology = tuple(technology) if isinstance(technology, (tuple, list, set)) \
                else (technology,)
            matches = tuple(r for r in matches if r.technology in technology)
        if kind is not None:
            kind = tuple(kind) if isinstance(kind, (tuple, list, set)) else (kind,)
            matches = tuple(r for r in matches if r.kind in kind)
        return matches

    def find(self, reference, technology=None, kind=None):
        """Resolve `reference` to exactly one resource, or raise a SpecError.

        Not found and ambiguous are distinct, explicitly reported situations.
        """
        text = str(reference).strip()
        matches = self.candidates(text, technology=technology, kind=kind)
        if len(matches) == 1:
            return matches[0]
        if not matches:
            if not self.configured:
                raise SpecError(
                    f'Kommunikationsobjekt {text!r} ist unbekannt: für dieses Projekt '
                    f'ist keine Kommunikationsbeschreibung konfiguriert')
            raise SpecError(f'Kommunikationsobjekt {text!r} ist in keiner geladenen '
                            f'Beschreibung deklariert{self._did_you_mean(text)}')
        alternatives = ', '.join(sorted(resource.qualified_name for resource in matches))
        raise SpecError(
            f'Kommunikationsreferenz {text!r} ist mehrdeutig ({len(matches)} Treffer): '
            f'{alternatives}; verwende eine qualifizierte Referenz '
            f'(z. B. {matches[0].qualified_name!r})')

    def adapter_address(self, resource):
        """The address handed to the bench adapter for `resource`.

        Determined solely by the resource's own description and its configured
        `adapter_naming` policy. Loading another network never changes it: if two
        descriptions would claim the same address, the catalog reports a collision
        instead (see `address_collisions`).
        """
        return self._addresses.get(resource.identity, resource.name)

    def is_address_colliding(self, resource):
        address = self.adapter_address(resource)
        return any(address in problem for problem in self.address_collisions)

    #: Retained name for the previous API; identical to `adapter_address`.
    bench_name = adapter_address

    def declares_state_anywhere(self, text, technology=None, kind=None):
        """Whether any resource declares `text` as a symbolic state."""
        key = normalise_state(text)
        for resource in self._resources:
            if technology is not None and resource.technology != technology:
                continue
            if kind is not None and resource.kind != kind:
                continue
            if resource.encoding is not None and key in resource.encoding.states:
                return True
        return False

    def signal_names(self):
        """Qualified names of every signal resource, sorted."""
        return tuple(sorted(r.qualified_name for r in self._resources
                            if r.kind is ObjectKind.SIGNAL))

    def declared_states(self, reference, technology=None):
        """The symbolic states the referenced resource declares, as written."""
        matches = self.candidates(reference, technology=technology, kind=ObjectKind.SIGNAL)
        if len(matches) != 1 or matches[0].encoding is None:
            return ()
        return matches[0].encoding.declared_states

    def resolve_state(self, reference, text, technology=None):
        """The RAW value the referenced resource declares for `text`, else None."""
        matches = self.candidates(reference, technology=technology, kind=ObjectKind.SIGNAL)
        if len(matches) != 1 or matches[0].encoding is None:
            return None
        return matches[0].encoding.state_raw(text)

    @property
    def source(self):
        """A short description of where this catalog came from."""
        names = [source.name for source in self.sources]
        return ', '.join(names) if names else '<unkonfiguriert>'

    def _did_you_mean(self, text):
        key = text.split(REFERENCE_SEPARATOR)[-1].casefold()
        close = sorted({resource.qualified_name for resource in self._resources
                        if resource.name.casefold() == key})
        return f'; gemeint war vielleicht: {", ".join(close)}' if close else ''

    def merged_with(self, other):
        """Combine two catalogs, e.g. several descriptions of one project."""
        return CommunicationCatalog(
            resources=self._resources + other._resources,
            sources=self.sources + other.sources,
            aliases={**self.aliases, **other.aliases},
            configured=self.configured or other.configured,
        )


EMPTY_CATALOG = CommunicationCatalog(configured=False)


def check_unique_identities(resources, where='Kommunikationsbeschreibung'):
    """Reject two resources that claim the very same identity."""
    seen, problems = {}, []
    for resource in resources:
        previous = seen.get(resource.identity)
        if previous is not None:
            problems.append(
                f'{where}: {resource.qualified_name} ist doppelt deklariert '
                f'(aus {previous.source} und {resource.source})')
        else:
            seen[resource.identity] = resource
    if problems:
        raise SpecError(problems)
    return tuple(resources)


def build_encoding(where, *, data_type='number', unit=None, factor=1, offset=0,
                   minimum=None, maximum=None, values=None):
    """Validate and build a ValueEncoding from importer-supplied raw fields.

    `values` maps raw value -> declared state name. State names that collide under
    `normalise_state` while mapping to different raw values are rejected here, so a
    contradictory description can never silently overwrite one of its own mappings.
    """
    factor = _decimal(factor, f'{where}: factor')
    offset = _decimal(offset, f'{where}: offset')
    if factor == 0:
        raise SpecError(f'{where}: factor must not be zero')
    minimum = None if minimum is None else _decimal(minimum, f'{where}: min')
    maximum = None if maximum is None else _decimal(maximum, f'{where}: max')
    if minimum is not None and maximum is not None and minimum > maximum:
        raise SpecError(f'{where}: min {minimum} is greater than max {maximum}')

    states, declared, origin, problems = {}, [], {}, []
    for raw, state in (values or {}).items():
        if not isinstance(state, str) or not state.strip():
            problems.append(f'{where}: state name {state!r} must be a non-empty string')
            continue
        try:
            value = _decimal(raw, f'{where}: state {state!r} raw value')
        except SpecError as error:
            problems.extend(error.problems)
            continue
        key = normalise_state(state)
        if key in states and states[key] != value:
            problems.append(
                f'{where}: states {origin[key]!r} and {state!r} are ambiguous after '
                f'normalisation (both become {key!r}) but map to different raw values '
                f'{states[key]} and {value}')
            continue
        states[key] = value
        origin.setdefault(key, state)
        if state not in declared:
            declared.append(state)
    if problems:
        raise SpecError(problems)

    return ValueEncoding(
        data_type=data_type, unit=unit or None, factor=factor, offset=offset,
        minimum=minimum, maximum=maximum,
        states=MappingProxyType(states), declared_states=tuple(declared),
    )
