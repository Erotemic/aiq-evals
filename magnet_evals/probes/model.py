from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ProbeStatus(str, Enum):
    PASS = 'pass'
    FAIL = 'fail'
    BLOCKED = 'blocked'
    INFO = 'info'


@dataclass(frozen=True)
class ProbeRecord:
    """One durable fact captured by a phase-1 probe."""

    probe: str
    status: ProbeStatus
    summary: str
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data['status'] = self.status.value
        return data


@dataclass
class ProbeReport:
    """Serializable collection of phase-1 probe evidence."""

    schema_version: int
    generated_at: str
    host: dict[str, Any]
    records: list[ProbeRecord]

    def to_dict(self) -> dict[str, Any]:
        return {
            'schema_version': self.schema_version,
            'generated_at': self.generated_at,
            'host': self.host,
            'records': [record.to_dict() for record in self.records],
        }

    def write_json(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True) + '\n')
        return path
