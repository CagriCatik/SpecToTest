"""Standalone Persistent Software Target System (RecordStoreService).

A concrete, hardware-free software service demonstrating state persistence,
input validation, restart/reload lifecycles, and deliberate fault injection modes.
"""
from enum import Enum
import json
from pathlib import Path
import time
from typing import Any


class FaultMode(str, Enum):
    NONE = 'NONE'
    DROP_ON_RESTART = 'DROP_ON_RESTART'
    CORRUPT_DATA = 'CORRUPT_DATA'
    CRASH_SERVICE = 'CRASH_SERVICE'
    REJECT_ALL = 'REJECT_ALL'


class ServiceError(Exception):
    """Base exception for service errors."""
    pass


class ValidationError(ServiceError):
    """Raised when record keys or values fail domain schema validation."""
    pass


class ServiceConnectionError(ServiceError):
    """Raised when the service is unreachable or crashed."""
    pass


class RecordStoreService:
    """Persistent Record Store Service with file-backed storage and fault-injection."""

    def __init__(self, storage_dir: Path):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.storage_dir / 'records.json'
        self.fault_mode = FaultMode.NONE
        self._records: dict[str, dict[str, Any]] = {}
        self._load_from_disk()

    def _load_from_disk(self) -> None:
        if self.db_path.is_file():
            try:
                data = json.loads(self.db_path.read_text(encoding='utf-8'))
                if isinstance(data, dict):
                    self._records = data
            except Exception as err:
                raise ServiceError(f"Corrupted storage file at {self.db_path}: {err}") from err
        else:
            self._records = {}

    def _persist_to_disk(self) -> None:
        if self.fault_mode == FaultMode.DROP_ON_RESTART:
            # Bug simulation: Service updates in-memory state but skips disk persistence
            return
        tmp = self.db_path.with_suffix('.json.tmp')
        tmp.write_text(json.dumps(self._records, indent=2), encoding='utf-8')
        tmp.replace(self.db_path)

    def _check_connectivity(self) -> None:
        if self.fault_mode == FaultMode.CRASH_SERVICE:
            raise ServiceConnectionError("Connection to RecordStoreService failed (service unavailable/crashed)")

    def set_record(self, key: str, value: str, owner: str = 'system') -> None:
        self._check_connectivity()
        if self.fault_mode == FaultMode.REJECT_ALL:
            raise ServiceError("Service is currently in REJECT_ALL fault mode")

        # Schema & domain validation
        if not key or not isinstance(key, str):
            raise ValidationError(f"Invalid record key: {key!r} (must be a non-empty string)")
        if not key.replace('_', '').replace('-', '').isalnum():
            raise ValidationError(f"Invalid record key: {key!r} (must contain only alphanumeric characters, underscores, and hyphens)")
        if len(key) > 64:
            raise ValidationError(f"Key exceeds maximum length of 64 characters: {key!r}")
        if value is None or not isinstance(value, str):
            raise ValidationError(f"Record value for '{key}' must be a string, got {type(value).__name__}")

        self._records[key] = {
            'value': value,
            'owner': owner,
            'updated_at': time.time(),
        }
        self._persist_to_disk()

    def get_record(self, key: str) -> str | None:
        self._check_connectivity()
        if key not in self._records:
            return None
        val = self._records[key]['value']
        if self.fault_mode == FaultMode.CORRUPT_DATA:
            return f"{val}__CORRUPTED"
        return val

    def delete_record(self, key: str) -> bool:
        self._check_connectivity()
        if key in self._records:
            del self._records[key]
            self._persist_to_disk()
            return True
        return False

    def list_keys(self) -> list[str]:
        self._check_connectivity()
        return sorted(self._records.keys())

    def restart(self) -> None:
        """Simulates process shutdown and cold restart by dropping in-memory cache and reading disk."""
        self._check_connectivity()
        self._records.clear()
        self._load_from_disk()

    def inject_fault(self, fault: str) -> None:
        """Injects a deliberate operational failure for negative testing."""
        try:
            self.fault_mode = FaultMode(fault.upper())
        except ValueError:
            valid = [m.value for m in FaultMode]
            raise ValueError(f"Unknown fault mode {fault!r}; available: {valid}")

    def clear_faults(self) -> None:
        self.fault_mode = FaultMode.NONE

    def is_healthy(self) -> bool:
        return self.fault_mode != FaultMode.CRASH_SERVICE

    def purge_storage(self) -> None:
        """Completely purges persisted storage and clears in-memory state."""
        self._records.clear()
        if self.db_path.is_file():
            self.db_path.unlink()
        self.clear_faults()
