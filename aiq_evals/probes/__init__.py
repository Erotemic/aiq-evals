"""Phase-1 probe support.

Probe output is evidence about an environment or upstream checkout. It is not a
runtime compatibility promise and does not mark release gates green by itself.
"""

from aiq_evals.probes.model import ProbeRecord, ProbeStatus

__all__ = ['ProbeRecord', 'ProbeStatus']
