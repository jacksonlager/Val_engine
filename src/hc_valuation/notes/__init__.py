"""The note reader: what a row's free text says that its columns do not (see reader.py)."""
from .catalogue import ASPECTS, BY_KIND, AspectKind, AspectSpec
from .reader import ClaudeReader, OffReader, Reader, make_reader, read_feed
from .schema import Aspect, Conflict, ReadingReport, RowReading, Supersession

__all__ = ["ASPECTS", "BY_KIND", "Aspect", "AspectKind", "AspectSpec", "ClaudeReader", "Conflict", "OffReader", "Reader",
           "ReadingReport", "RowReading", "Supersession", "make_reader", "read_feed"]
