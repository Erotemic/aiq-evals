"""Domain errors for :mod:`magnet_evals`."""


class AiqEvalsError(Exception):
    """Base class for aiq-magnet-evals errors."""


class RequestValidationError(AiqEvalsError, ValueError):
    """A request is invalid before native engine resolution."""


class UnknownEngineError(AiqEvalsError, LookupError):
    """No adapter is registered for the requested engine."""


class MissingDependencyError(AiqEvalsError, ImportError):
    """An optional native evaluation engine is not installed."""


class EngineCompatibilityError(AiqEvalsError):
    """The installed native engine does not expose the supported API seam."""


class ExecutionError(AiqEvalsError):
    """Native execution failed or returned a failed terminal result."""


class ActiveEventLoopError(AiqEvalsError, RuntimeError):
    """The synchronous facade was called from an active event loop."""


class ArtifactError(AiqEvalsError):
    """A run bundle or native artifact is corrupt or incompatible."""


class PublicationError(ArtifactError):
    """Atomic run publication could not be completed safely."""
