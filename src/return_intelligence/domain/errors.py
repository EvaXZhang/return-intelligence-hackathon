class DomainError(RuntimeError):
    pass


class ValidationError(DomainError):
    pass


class ConflictError(DomainError):
    pass


class PolicyViolation(DomainError):
    pass


class NotFoundError(DomainError):
    pass


class ArtifactGenerationError(DomainError):
    pass


class AIProviderError(DomainError):
    pass
