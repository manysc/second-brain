"""Legacy import path: the API schemas live in app.presentation.api.schemas and the raw extraction file schema
with its parser. Kept until the remaining callers and tests import from there."""
from app.infrastructure.external_services.extraction_parser import (  # noqa: F401
    RawCandidate,
    RawEvidence,
    RawExtraction,
    RawMeetingInfo,
    RawReviewCandidate,
)
from app.presentation.api.schemas import *  # noqa: F401,F403
from app.presentation.api.schemas import MAX_TAG_LENGTH, MAX_TAGS, normalize_tag  # noqa: F401
