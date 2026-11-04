"""Parameter types that resolve against the active project's communication catalog.

Two generic building blocks, usable by every technology:

* `ResourceReference` -- names one communication object. It checks technology and
  object kind, so an Ethernet service can never be passed where a CAN signal is
  required. It converts to the name the bench adapter is addressed with.
* `SignalValue` -- a value *of* a referenced signal. It declares the reference
  parameter of its own operation call as its dependency (see `tcg.core.parameters`),
  so the unit, range and symbolic states always come from that very resource,
  whatever order the sentence template puts the placeholders in.

Value semantics are explicit. `SignalValue` is either `PHYSICAL` or `RAW`; it never
guesses, and scaling is applied exactly once:

    physical = raw * factor + offset
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
import re

from tcg.comm.catalog import COMM_CATALOG_KEY
from tcg.comm.model import (
    EMPTY_CATALOG,
    ObjectKind,
    REFERENCE_PATTERN,
    ResourceAddress,
    Technology,
)
from tcg.core.model import SpecError
from tcg.core.parameters import Quantity

PHYSICAL = 'physical'
RAW = 'raw'


def _as_tuple(value):
    if value is None:
        return None
    return tuple(value) if isinstance(value, (tuple, list, set, frozenset)) else (value,)


@dataclass(frozen=True)
class ResourceReference:
    """A reference to one communication object of a given technology and kind.

    Accepts a bare name while it is unambiguous, and a qualified reference such as
    ``PowertrainCAN::VehicleSpeed`` or ``BodyLIN::DoorFrame::DoorState`` otherwise.
    """
    technology: object = None          # Technology or tuple of them; None = any
    kinds: object = None               # ObjectKind or tuple of them; None = any
    catalog: object = EMPTY_CATALOG
    label: str = 'Kommunikationsobjekt'
    #: Resource-profile kind used while the project configures no description at all.
    #: This keeps projects that predate communication catalogs working unchanged.
    profile_kind: str = ''

    @property
    def lexical(self):
        return REFERENCE_PATTERN

    def bind(self, project_data):
        catalog = (project_data or {}).get(COMM_CATALOG_KEY) or EMPTY_CATALOG
        return self if catalog is self.catalog else replace(self, catalog=catalog)

    def describe_unresolved_identifier(self, name):
        if not self.catalog.configured:
            return ('für dieses Projekt ist keine Kommunikationsbeschreibung '
                    'konfiguriert; trage sie unter "communication" in der '
                    'Projektkonfiguration ein')
        return None

    def resolve(self, text):
        """The single resource `text` addresses, or a SpecError explaining why not."""
        technology, kinds = _as_tuple(self.technology), _as_tuple(self.kinds)
        resource = self.catalog.find(text, technology=technology, kind=kinds)
        return resource

    def convert(self, text, profile):
        if not self.catalog.configured:
            # No description configured: fall back to the resource profile, exactly as
            # before communication catalogs existed.
            if self.profile_kind and self.profile_kind in profile.resources:
                allowed = profile.resources[self.profile_kind]
                if text not in allowed:
                    raise SpecError(f'unknown {self.profile_kind} {text!r}; profile '
                                    f'declares: {", ".join(allowed)}')
                return text
            raise SpecError(
                f'{self.label} {text!r} kann nicht aufgelöst werden: für dieses '
                f'Projekt ist keine Kommunikationsbeschreibung konfiguriert')
        resource = self._resolve_or_explain(text)
        return ResourceAddress(self.catalog.adapter_address(resource), resource)

    def _resolve_or_explain(self, text):
        technology, kinds = _as_tuple(self.technology), _as_tuple(self.kinds)
        try:
            return self.catalog.find(text, technology=technology, kind=kinds)
        except SpecError:
            # Distinguish "exists but is the wrong sort of object" from "unknown",
            # so a service used as a signal gets a precise message.
            others = self.catalog.candidates(text)
            if len(others) == 1:
                other = others[0]
                expected = ', '.join(str(k) for k in (kinds or ())) or 'beliebig'
                raise SpecError(
                    f'{other.qualified_name} ist ein {other.technology}-'
                    f'{other.kind} und kann hier nicht verwendet werden; '
                    f'erwartet wird: {expected}'
                    + (f' ({", ".join(str(t) for t in technology)})' if technology else '')
                ) from None
            raise


@dataclass(frozen=True)
class SignalValue:
    """A value of the signal referenced by a sibling parameter of the same call.

    `semantics` states explicitly whether the operation works with PHYSICAL values
    (the tester's unit, e.g. volts) or RAW bus values. Symbolic states are declared as
    raw values in every description format, so under PHYSICAL semantics they are
    scaled exactly once on resolution.
    """
    quantity: Quantity
    reference_parameter: str = 'signal'
    semantics: str = PHYSICAL
    technology: object = None
    catalog: object = EMPTY_CATALOG

    @property
    def depends_on(self):
        return (self.reference_parameter,)

    @property
    def lexical(self):
        # Numbers with a unit, bare identifiers, and quoted states such as "Stufe 2".
        return re.compile(
            r'(?:-?(?:0|[1-9][0-9]*)(?:[.,][0-9]+)?(?:\s*[A-Za-z°%/Ω]+)?'
            r'|[A-Za-z_][A-Za-z0-9_]*|"(?:[^"\\]|\\.)*")'
        )

    def bind(self, project_data):
        catalog = (project_data or {}).get(COMM_CATALOG_KEY) or EMPTY_CATALOG
        return self if catalog is self.catalog else replace(self, catalog=catalog)

    def describe_unresolved_identifier(self, name):
        if not self.catalog.configured:
            return ('für dieses Projekt ist keine Kommunikationsbeschreibung '
                    'konfiguriert; symbolische Signalzustände können nicht '
                    'aufgelöst werden (siehe "communication" bzw. "can_database" '
                    'in der Projektkonfiguration)')
        return None

    def _resource(self, reference):
        """The signal this value belongs to.

        The reference parameter hands over the resource it resolved, so the adapter
        address is never resolved a second time (it is an adapter-side name and may
        follow any naming policy).
        """
        resource = getattr(reference, 'resource', None)
        if resource is not None:
            return resource if resource.kind is ObjectKind.SIGNAL else None
        matches = self.catalog.candidates(
            reference, technology=_as_tuple(self.technology), kind=ObjectKind.SIGNAL)
        return matches[0] if len(matches) == 1 else None

    def convert(self, text, profile, dependencies):
        reference = dependencies.get(self.reference_parameter)
        clean = text.strip().strip('"\'')
        if isinstance(reference, str):
            resource = self._resource(reference)
            if resource is not None and resource.encoding is not None:
                encoding = resource.encoding
                raw = encoding.state_raw(clean)
                if raw is not None:
                    return raw if self.semantics == RAW else encoding.raw_to_physical(raw)
                if self.catalog.declares_state_anywhere(
                        clean, technology=resource.technology, kind=ObjectKind.SIGNAL):
                    declared = encoding.declared_states
                    allowed = (f'gültige Zustände: {", ".join(declared)}' if declared
                               else 'dieses Signal deklariert keine symbolischen Zustände')
                    label = f'{resource.technology.value.upper()}-Signal'
                    raise SpecError(
                        f'Zustand {clean!r} ist für {label} {resource.name!r} '
                        f'({resource.qualified_name}) nicht gültig; {allowed} '
                        f'(Katalog: {self.catalog.source})')
        # A number with a unit, or an identifier the compiler checks against the scope.
        return self.quantity.convert(text, profile)


@dataclass(frozen=True)
class RawSignalValue(SignalValue):
    """A raw bus value: never scaled, never a physical unit."""
    semantics: str = RAW
