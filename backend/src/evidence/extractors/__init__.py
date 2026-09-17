"""Evidence extractors. One per evidence type, registered on import.

An extractor reports what an artifact says, with provenance. It never performs
reconciliation arithmetic and never reaches a conclusion, so a future model-
backed extractor can replace a deterministic one without gaining any authority
over compliance decisions.
"""

from .base import EvidenceExtractor, get, register, registered_types
from .user_access_review import UserAccessReviewExtractor

__all__ = [
    "EvidenceExtractor",
    "UserAccessReviewExtractor",
    "get",
    "register",
    "registered_types",
]
