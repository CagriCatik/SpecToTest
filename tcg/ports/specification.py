"""Hexagonal Architecture: Driving Port (Primary Interface) for Specification Parsers."""
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SpecificationParserPort(Protocol):
    """Driving port for parsing test specifications into structured section tables."""

    def parse_specification(self, path: Path | str) -> dict[str, list[tuple[int, dict]]]:
        """Parse a test specification into section rows (line number, dict of step fields)."""
        ...

