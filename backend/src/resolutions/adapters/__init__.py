"""Concrete implementations of the application ports.

Every module here owns exactly one vendor dependency. Swapping Tesseract for
PaddleOCR, or Claude for another model, is a one-file change that the domain and
use cases never see.
"""

from .mistral_summary import MistralSummaryAdapter, MistralSummaryConfig

__all__ = [
    "MistralSummaryAdapter",
    "MistralSummaryConfig",
]
