"""Native engine adapters and lazy registry."""

from aiq_evals.backends.registry import (
    BackendRegistration,
    get_backend,
    register_backend,
    registrations,
)

__all__ = ['BackendRegistration', 'get_backend', 'register_backend', 'registrations']
