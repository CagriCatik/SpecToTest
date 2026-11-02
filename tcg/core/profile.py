"""Generic resource profiles. They deliberately contain no bench simulation rules."""
from dataclasses import dataclass
import json
import re

from .model import SpecError
from .parameters import Resource

PROFILE_ID_PATTERN = re.compile(r'[A-Z][A-Z0-9_]*')
RESOURCE_IDENTIFIER = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')
KEYS = {'profile_id', 'resources'}


@dataclass(frozen=True)
class ResourceProfile:
    profile_id: str
    resources: dict


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise SpecError(f'duplicate key {key!r}')
        result[key] = value
    return result


def parse_profile(text, name='resources'):
    try:
        data = json.loads(text, object_pairs_hook=_pairs)
    except SpecError as error:
        raise SpecError(f'{name}: {error}') from None
    except json.JSONDecodeError as error:
        raise SpecError(f'{name}: invalid JSON: {error}') from None
    if not isinstance(data, dict) or set(data) != KEYS:
        found = sorted(data) if isinstance(data, dict) else type(data).__name__
        raise SpecError(f'{name}: expected exactly {sorted(KEYS)}, got {found}')
    problems, resources = [], {}
    if not isinstance(data['profile_id'], str) or not PROFILE_ID_PATTERN.fullmatch(data['profile_id']):
        problems.append(f'{name}: profile_id must match {PROFILE_ID_PATTERN.pattern}')
    if not isinstance(data['resources'], dict):
        problems.append(f'{name}: resources must be an object')
    else:
        for kind, values in data['resources'].items():
            if not isinstance(kind, str) or not re.fullmatch(r'[a-z][a-z0-9_]*', kind):
                problems.append(f'{name}: resource kind {kind!r} must be lower_snake_case')
            elif not isinstance(values, list) or not values or not all(
                    isinstance(value, str) and RESOURCE_IDENTIFIER.fullmatch(value) for value in values) or len(values) != len(set(values)):
                problems.append(f'{name}: resources.{kind} must be a non-empty list of unique identifiers')
            else:
                resources[kind] = tuple(values)
    if problems:
        raise SpecError(problems)
    return ResourceProfile(data['profile_id'], resources)


def load_profile(path):
    try:
        return parse_profile(path.read_text(encoding='utf-8'), path.name)
    except OSError as error:
        raise SpecError(f'{path.name}: cannot read resources ({error.strerror})') from None


def check_profile(profile, contracts):
    """Check only resource kinds used by the compiled cases.

    Adding an unused operation to a registry must not invalidate existing tests.
    """
    if isinstance(contracts, dict):
        contracts = contracts.values()
    needed = {spec.type.kind for contract in contracts for spec in contract.parameters
              if isinstance(spec.type, Resource)}
    problems = [f'profile {profile.profile_id}: missing resources.{kind}' for kind in sorted(needed - set(profile.resources))]
    if problems:
        raise SpecError(problems)
