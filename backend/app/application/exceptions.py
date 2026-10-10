"""Failures of the application's surroundings, already translated out of their technology."""
from __future__ import annotations


class ApplicationError(Exception):
    """Base class for failures that are not business-rule violations."""


class StorageUnavailable(ApplicationError):
    """The database cannot be reached."""


class StorageNotConfigured(StorageUnavailable):
    """The database connection has not been configured."""


class ExtractSourceUnavailable(ApplicationError):
    """The extract source (object storage) cannot be reached."""


class MalformedExtract(ApplicationError, ValueError):
    """An extract file has an unrecognized shape or invalid content (e.g. a non-ISO meeting date)."""


class IngestionAlreadyRunning(ApplicationError):
    """Two ingestion runs must never overlap: they would race on the near-duplicate check."""
