"""Typed exceptions used by EvalCanary."""

from __future__ import annotations


class EvalCanaryError(Exception):
    """Base exception for expected EvalCanary failures."""


class InputValidationError(EvalCanaryError):
    """Raised when an input artifact does not satisfy the public schema."""


class VerifierExecutionError(EvalCanaryError):
    """Raised when a verifier subprocess cannot complete safely."""


class PolicyConfigurationError(EvalCanaryError):
    """Raised when a policy file is invalid or internally inconsistent."""
