"""Backend-agnostic evaluation runtime research package.

The first release phase is intentionally focused on validating upstream engine
boundaries before freezing the public execution/result contracts.
"""

from aiq_evals._version import __version__
from aiq_evals.engines import ENGINE_SPECS, EngineSpec

__all__ = ['ENGINE_SPECS', 'EngineSpec', '__version__']
