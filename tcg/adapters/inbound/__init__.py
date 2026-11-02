"""Inbound (Driving) Adapters for TCG."""
from .text_parser import TextSpecificationParser, parse_text_spec, read_text_spec

__all__ = ['TextSpecificationParser', 'parse_text_spec', 'read_text_spec']

