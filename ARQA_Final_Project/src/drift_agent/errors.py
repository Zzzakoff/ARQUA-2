class DriftAgentError(Exception):
    """Base exception for the project."""


class SpecLoadError(DriftAgentError):
    """Raised when the spec file cannot be loaded."""


class SpecParseError(DriftAgentError):
    """Raised when the spec file is not valid YAML/JSON."""


class SpecValidationError(DriftAgentError):
    """Raised when the document is not a valid OpenAPI 3.x spec."""


class UnsupportedVersionError(DriftAgentError):
    """Raised when an unsupported OpenAPI version is provided."""


class UnsupportedFeatureError(DriftAgentError):
    """Raised for features intentionally unsupported in V1."""


class ConflictError(DriftAgentError):
    """Raised when a lossy merge is unavoidable."""


class CodeAnalysisError(DriftAgentError):
    """Raised when the code analyzer cannot continue."""


class ModelNotAvailableError(DriftAgentError):
    """Raised when the configured local model is unavailable."""


class OllamaConnectionError(DriftAgentError):
    """Raised when the local Ollama runtime cannot be contacted."""


class AgentFailure(DriftAgentError):
    """Raised for a failed agent inference on a single item."""

