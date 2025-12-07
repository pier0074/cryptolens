"""
Domain Exceptions
Custom exception classes for standardized error handling
"""


class CryptoLensError(Exception):
    """Base exception for all application errors"""
    status_code = 500
    message = "An unexpected error occurred"

    def __init__(self, message=None, details=None):
        self.message = message or self.__class__.message
        self.details = details
        super().__init__(self.message)

    def to_dict(self):
        return {
            'error': self.__class__.__name__,
            'message': self.message,
            'details': self.details
        }


class AuthenticationError(CryptoLensError):
    """Raised when authentication fails"""
    status_code = 401
    message = "Authentication required"


class AuthorizationError(CryptoLensError):
    """Raised when user lacks permission"""
    status_code = 403
    message = "Access denied"


class ValidationError(CryptoLensError):
    """Raised when input validation fails"""
    status_code = 400
    message = "Invalid input"


class NotFoundError(CryptoLensError):
    """Raised when a resource is not found"""
    status_code = 404
    message = "Resource not found"


class RateLimitError(CryptoLensError):
    """Raised when rate limit is exceeded"""
    status_code = 429
    message = "Rate limit exceeded"


class ExternalServiceError(CryptoLensError):
    """Raised when an external service fails"""
    status_code = 502
    message = "External service unavailable"


class ConfigurationError(CryptoLensError):
    """Raised when configuration is invalid"""
    status_code = 500
    message = "Configuration error"
