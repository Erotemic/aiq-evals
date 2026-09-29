"""Small JSON/canonicalization helpers used by public contracts."""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from aiq_evals.errors import RequestValidationError

JSONScalar = None | bool | int | float | str
JSONValue = JSONScalar | list['JSONValue'] | dict[str, 'JSONValue']

_SECRET_FRAGMENTS = (
    'api_key',
    'apikey',
    'password',
    'passwd',
    'secret',
    'credential',
    'access_token',
    'auth_token',
)

# These fields contain *names* of environment variables, not credential values.
_SECRET_NAME_FIELDS = {'required_secrets'}


def normalize_json(value: Any, *, path: str = '$') -> JSONValue:
    """Return a strict JSON value with deterministic mapping keys.

    Tuples are accepted as input convenience and normalized to lists. Paths and
    arbitrary Python objects are rejected so request identity never depends on
    ``repr`` or object identity.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise RequestValidationError(f'{path} contains non-finite float {value!r}')
        return value
    if isinstance(value, Path):
        raise RequestValidationError(
            f'{path} contains Path {value!r}; use an immutable string reference instead'
        )
    if isinstance(value, Mapping):
        out: dict[str, JSONValue] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise RequestValidationError(f'{path} has non-string key {key!r}')
            out[key] = normalize_json(value[key], path=f'{path}.{key}')
        return out
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [normalize_json(item, path=f'{path}[{idx}]') for idx, item in enumerate(value)]
    raise RequestValidationError(
        f'{path} contains non-JSON value of type {type(value).__name__}'
    )


def canonical_json_bytes(value: Any) -> bytes:
    """Serialize a JSON value in the canonical form used for identities."""
    normalized = normalize_json(value)
    return json.dumps(
        normalized,
        sort_keys=True,
        separators=(',', ':'),
        ensure_ascii=False,
        allow_nan=False,
    ).encode('utf8')


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def sha256_file(path: str | Path, *, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with Path(path).open('rb') as file:
        while True:
            chunk = file.read(chunk_size)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def find_secret_paths(value: Any, *, path: str = '$') -> list[str]:
    """Find keys that look credential-bearing.

    Evaluation requests are persisted and hashed, so secrets belong in
    :class:`ExecutionContext.env`, never in request/native option dictionaries.
    """
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            key_text = str(key).lower().replace('-', '_')
            child = f'{path}.{key}'
            if key_text not in _SECRET_NAME_FIELDS:
                if any(fragment in key_text for fragment in _SECRET_FRAGMENTS):
                    found.append(child)
                found.extend(find_secret_paths(item, path=child))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for idx, item in enumerate(value):
            found.extend(find_secret_paths(item, path=f'{path}[{idx}]'))
    return found


def omitted_fields(native: Mapping[str, Any], retained: set[str]) -> list[str]:
    """Names of non-empty native fields a normalizer did not carry over."""
    return sorted(
        str(key) for key, value in native.items()
        if str(key) not in retained and value not in (None, '', [], {}, ())
    )


def check_secret_name_list(value: Any, *, label: str) -> None:
    """``required_secrets`` must be a list of environment-variable names."""
    if not isinstance(value, list) or any(
        not isinstance(name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name) for name in value
    ):
        raise ValueError(f'{label} must be a list of environment variable names')


def required_secret_names(value: Any) -> list[str]:
    """Collect environment-variable names listed under any ``required_secrets`` key."""
    names: list[str] = []
    if isinstance(value, Mapping):
        for key, item in value.items():
            if str(key) in _SECRET_NAME_FIELDS and isinstance(item, Sequence) and not isinstance(item, str):
                names.extend(str(name) for name in item)
            else:
                names.extend(required_secret_names(item))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            names.extend(required_secret_names(item))
    return sorted(set(names))


# Environment values shorter than this are not scrubbed from structured data:
# replacing e.g. "1" would corrupt sample IDs and digests, and a value that short
# is not a credential. Free-text worker logs are still scrubbed of every value.
MIN_REDACTED_VALUE_LENGTH = 8


def redact_values(value: Any, secrets: Mapping[str, str]) -> Any:
    """Replace every occurrence of a secret value in JSON-shaped data.

    Values shorter than ``MIN_REDACTED_VALUE_LENGTH`` are left in place.

    Keys and string leaves are both scrubbed; each occurrence becomes
    ``<redacted:NAME>``. Used for worker-returned results, whose native
    exception text and tracebacks can quote credentials from the environment.
    """
    replacements = [
        (secret, f'<redacted:{name}>')
        for name, secret in secrets.items()
        if secret and len(secret) >= MIN_REDACTED_VALUE_LENGTH
    ]
    # Longest first so a secret containing another secret is fully replaced.
    replacements.sort(key=lambda item: len(item[0]), reverse=True)
    if not replacements:
        return value

    def scrub(text: str) -> str:
        for secret, replacement in replacements:
            text = text.replace(secret, replacement)
        return text

    def walk(item: Any) -> Any:
        if isinstance(item, str):
            return scrub(item)
        if isinstance(item, Mapping):
            return {scrub(str(key)): walk(child) for key, child in item.items()}
        if isinstance(item, (list, tuple)):
            return [walk(child) for child in item]
        return item

    return walk(value)
