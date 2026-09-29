"""Engine-independent run bundle publication and reading."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from magnet_evals.contracts import (
    MANIFEST_SCHEMA_VERSION,
    ArtifactReference,
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
)
from magnet_evals.errors import ArtifactError, PublicationError
from magnet_evals.jsonutil import (
    JSONValue,
    normalize_json,
    normalize_json_object,
    sha256_file,
    sha256_json,
)

RUN_COMPLETE = 'RUN_COMPLETE'
METADATA_FILES = ('resolved_request.json', 'results.json', 'attempt.json')
ATTEMPT_TERMINAL = 'ATTEMPT_TERMINAL'


def _write_json(path: Path, data: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(normalize_json(dict(data)), indent=2, sort_keys=True) + '\n')


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError as ex:
        raise ArtifactError(f'missing required artifact: {path}') from ex
    except json.JSONDecodeError as ex:
        raise ArtifactError(f'invalid JSON artifact {path}: {ex}') from ex
    if not isinstance(data, dict):
        raise ArtifactError(f'expected JSON object in {path}')
    return data


def _inventory_order(rel: str) -> tuple[str, ...]:
    # Path order (component by component), which the published v1 bundles use.
    return tuple(rel.split('/'))


def _artifact_refs(files: list[tuple[str, Path]], role: str) -> tuple[ArtifactReference, ...]:
    return tuple(
        ArtifactReference(path=rel, sha256=sha256_file(path), size_bytes=path.stat().st_size, role=role)
        for rel, path in sorted(files, key=lambda item: _inventory_order(item[0]))
    )


def inventory_tree(root: Path, *, role: str = 'native') -> tuple[ArtifactReference, ...]:
    """Checksum all regular files below *root* using POSIX relative paths."""
    if not root.exists():
        return ()
    files = [(p.relative_to(root).as_posix(), p) for p in root.rglob('*') if p.is_file()]
    return _artifact_refs(files, role)


def native_artifact_identity(refs: tuple[ArtifactReference, ...] | list[ArtifactReference]) -> str:
    """Digest of a native inventory: the content identity of native artifacts."""
    return sha256_json([ref.to_dict() for ref in refs])


def native_source_identity(source: str | Path, *, allow_external_symlinks: bool = False) -> str:
    """Content identity of a native artifact source, before importing it.

    Equals the ``native_artifact_identity`` of the bundle that importing
    ``source`` publishes (same traversal, links, and ordering), so a store can
    key an import by its content without copying it first. Editing any file,
    even at the same path, changes it. Engine-free: it only reads bytes.
    """
    source = Path(source).expanduser().absolute()
    if source.is_file():
        return native_artifact_identity(_artifact_refs([(source.name, source.resolve())], 'native'))
    if not source.is_dir():
        raise ArtifactError(f'native artifact source does not exist: {source}')
    files, _, _ = _walk_native_tree(source, 'follow' if allow_external_symlinks else 'raise')
    return native_artifact_identity(_artifact_refs(files, 'native'))


@dataclass(frozen=True)
class RunBundle:
    """Dependency-free view of one published aiq-magnet-evals run."""

    path: Path
    resolved: ResolvedEvaluation
    result: EvaluationResult
    manifest: Mapping[str, Any]
    attempt: Mapping[str, Any]

    @property
    def complete(self) -> bool:
        return (self.path / RUN_COMPLETE).is_file()

    @classmethod
    def load(cls, path: str | Path, *, verify_checksums: bool = True) -> 'RunBundle':
        root = Path(path).expanduser().resolve()
        manifest = _load_json(root / 'run_manifest.json')
        schema = manifest.get('schema_version')
        if schema != MANIFEST_SCHEMA_VERSION:
            raise ArtifactError(
                f'unsupported run manifest schema {schema!r}; expected {MANIFEST_SCHEMA_VERSION}'
            )
        resolved = ResolvedEvaluation.from_dict(_load_json(root / 'resolved_request.json'))
        result = EvaluationResult.from_dict(_load_json(root / 'results.json'))
        attempt = _load_json(root / 'attempt.json')
        if result.identity.digest != resolved.identity.digest:
            raise ArtifactError('result identity does not match resolved request identity')
        if manifest.get('measurement_identity') != resolved.identity.digest:
            raise ArtifactError('manifest measurement identity does not match resolved request')
        if result.status == 'succeeded' and not (root / RUN_COMPLETE).is_file():
            raise ArtifactError('successful run is missing RUN_COMPLETE marker')
        if not (root / ATTEMPT_TERMINAL).is_file():
            raise ArtifactError('run is missing ATTEMPT_TERMINAL marker')
        if verify_checksums:
            for name, digest in dict(manifest.get('metadata_checksums') or {}).items():
                if name not in METADATA_FILES:
                    raise ArtifactError(f'unexpected metadata checksum entry {name!r}')
                if sha256_file(root / name) != digest:
                    raise ArtifactError(f'bundle metadata file {name} does not match its manifest checksum')
            refs: list[ArtifactReference] = []
            for row in manifest.get('native_artifacts', []):
                ref = ArtifactReference.from_dict(row)
                refs.append(ref)
                artifact = root / 'native' / ref.path
                if not artifact.is_file():
                    raise ArtifactError(f'missing native artifact {ref.path!r}')
                if artifact.stat().st_size != ref.size_bytes or sha256_file(artifact) != ref.sha256:
                    raise ArtifactError(f'native artifact checksum mismatch: {ref.path!r}')
            listed = {ref.path for ref in refs}
            native_root = root / 'native'
            present = {
                path.relative_to(native_root).as_posix()
                for path in native_root.rglob('*')
                if path.is_file() or path.is_symlink()
            } if native_root.is_dir() else set()
            extra = sorted(present - listed)
            if extra:
                raise ArtifactError(f'native files not in the manifest inventory: {extra[:5]}')
            native_identity = native_artifact_identity(refs)
            if manifest.get('native_artifact_identity') != native_identity:
                raise ArtifactError('native artifact identity does not match manifest inventory')
            normalized_identity = sha256_json(
                {
                    'measurement_identity': resolved.identity.digest,
                    'adapter_version': resolved.adapter_version,
                    'result_schema_version': result.schema_version,
                    'native_artifact_identity': native_identity,
                    'result': result.to_dict(),
                }
            )
            if manifest.get('normalized_artifact_identity') != normalized_identity:
                raise ArtifactError('normalized artifact identity does not match result payload')
        return cls(root, resolved, result, manifest, attempt)


_EXTERNAL_SYMLINK_MODES = ('exclude', 'raise', 'follow')


def _walk_native_tree(
    source: Path, external_symlinks: str,
) -> tuple[list[tuple[str, Path]], dict[str, list[str]], list[str]]:
    """Files (relative path, real path) and directories a native tree publishes.

    Links resolving inside ``source`` count as their content. Special files
    (FIFOs, sockets, devices) and dangling links never count. External links
    are excluded, refused, or followed per ``external_symlinks``. Returns the
    files, manifest notes, and every directory (so empty ones survive a copy).
    """
    if external_symlinks not in _EXTERNAL_SYMLINK_MODES:
        raise ValueError(f'external_symlinks must be one of {_EXTERNAL_SYMLINK_MODES}')
    root = source.resolve()
    notes: dict[str, list[str]] = {
        'excluded_external_symlinks': [],
        'followed_external_symlinks': [],
        'skipped_non_regular_files': [],
    }
    files: list[tuple[str, Path]] = []
    directories: list[str] = []

    def visit(directory: Path, prefix: str, *, followed: bool) -> None:
        for entry in sorted(directory.iterdir()):
            rel = f'{prefix}{entry.name}'
            real = entry.resolve()
            inside = real == root or root in real.parents
            if entry.is_symlink() and not inside and not followed:
                if external_symlinks == 'raise':
                    raise ArtifactError(
                        f'native artifact {rel!r} is a symlink outside the source tree; '
                        'pass allow_external_symlinks=True only for a trusted source'
                    )
                if external_symlinks == 'exclude':
                    notes['excluded_external_symlinks'].append(rel)
                    continue
                notes['followed_external_symlinks'].append(rel)
            is_followed = followed or (entry.is_symlink() and not inside)
            if real.is_dir():
                if entry.is_symlink() and inside and real in (directory.resolve(), *directory.resolve().parents):
                    continue  # a link back up the tree would recurse forever
                directories.append(rel)
                visit(entry, rel + '/', followed=is_followed)
            elif real.is_file():
                files.append((rel, real))
            else:
                notes['skipped_non_regular_files'].append(rel)

    visit(source, '', followed=False)
    return files, notes, directories


def copy_native_tree(source: Path, dest: Path, *, external_symlinks: str = 'exclude') -> dict[str, list[str]]:
    """Copy a native artifact tree without silently following links out of it.

    Links resolving inside ``source`` are copied as their content. Special files
    (FIFOs, sockets, devices) and dangling links are never copied. Returns manifest notes listing
    relative paths of excluded or followed external links and skipped
    non-regular files.
    """
    files, notes, directories = _walk_native_tree(source, external_symlinks)
    dest.mkdir(parents=True, exist_ok=True)
    for rel in directories:
        (dest / rel).mkdir(parents=True, exist_ok=True)
    for rel, real in files:
        shutil.copy2(real, dest / rel)
    return notes


def publish_run(
    destination: str | Path,
    *,
    resolved: ResolvedEvaluation,
    result: EvaluationResult,
    context: ExecutionContext,
    native_dir: str | Path | None = None,
    replace: bool = False,
    external_symlinks: str = 'exclude',
    attempt_metadata: Mapping[str, Any] | None = None,
    manifest_notes: Mapping[str, Any] | None = None,
) -> RunBundle:
    """Atomically publish one terminal run bundle.

    ``external_symlinks`` controls links in ``native_dir`` whose targets lie
    outside it: ``'exclude'`` (default) leaves them out, ``'raise'`` refuses,
    and ``'follow'`` copies their content. Copying an arbitrary link target
    into a bundle could publish unrelated host files. Whatever happens is
    recorded in the manifest.

    ``attempt_metadata`` extends (and may override) ``attempt.json``; the store
    uses it to carry the producing attempt's execution context and a
    ``source_attempt`` pointer into a promoted canonical run. ``manifest_notes``
    carries symlink notes recorded when the native files were first published.

    Failed/cancelled/incomplete attempts are terminal and inspectable but do not
    receive ``RUN_COMPLETE`` and are therefore never reusable as successful
    computations.
    """
    destination = Path(destination).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() and not replace:
        raise PublicationError(f'destination already exists: {destination}')
    staging = Path(tempfile.mkdtemp(prefix=f'.{destination.name}.', dir=destination.parent))
    try:
        native_out = staging / 'native'
        link_notes: dict[str, list[str]] = {}
        if native_dir is not None:
            source = Path(native_dir).expanduser().absolute()
            if source.is_dir():
                link_notes = copy_native_tree(
                    source, native_out, external_symlinks=external_symlinks
                )
            elif source.is_file():
                native_out.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source.resolve(), native_out / source.name)
        native_refs = inventory_tree(native_out)
        # Artifacts in result are adapter-declared semantic references; manifest
        # inventory is authoritative for bundle integrity.
        _write_json(staging / 'resolved_request.json', resolved.to_dict())
        _write_json(staging / 'results.json', result.to_dict())
        attempt = {
            'schema_version': 1,
            'status': result.status,
            'diagnostics': result.diagnostics,
            'execution_context': context.public_dict(),
        }
        attempt.update(dict(attempt_metadata or {}))
        _write_json(staging / 'attempt.json', attempt)
        native_identity = native_artifact_identity(native_refs)
        normalized_artifact_identity = sha256_json(
            {
                'measurement_identity': resolved.identity.digest,
                'adapter_version': resolved.adapter_version,
                'result_schema_version': result.schema_version,
                'native_artifact_identity': native_identity,
                'result': result.to_dict(),
            }
        )
        manifest: dict[str, JSONValue] = {
            'schema_version': MANIFEST_SCHEMA_VERSION,
            'engine': result.engine,
            'measurement_identity': resolved.identity.digest,
            'identity_algorithm': resolved.identity.algorithm,
            'reusable': resolved.identity.reusable and result.status == 'succeeded',
            'identity_unknown_reasons': list(resolved.identity.unknown_reasons),
            'result_schema_version': result.schema_version,
            'request_schema_version': resolved.request.schema_version,
            'native_artifacts': [ref.to_dict() for ref in native_refs],
            'native_artifact_identity': native_identity,
            'normalized_artifact_identity': normalized_artifact_identity,
            # Integrity of the bundle's own metadata files (optional when
            # loading: older bundles without it still load).
            'metadata_checksums': {
                name: sha256_file(staging / name) for name in METADATA_FILES
            },
        }
        # Optional: symlink handling is recorded so a reader can tell which
        # native paths were followed or left out.
        manifest.update(
            normalize_json_object({key: value for key, value in dict(manifest_notes or {}).items() if value})
        )
        manifest.update(normalize_json_object({key: value for key, value in link_notes.items() if value}))
        _write_json(staging / 'run_manifest.json', manifest)
        (staging / ATTEMPT_TERMINAL).write_text(result.status + '\n')
        if result.status == 'succeeded':
            (staging / RUN_COMPLETE).write_text(resolved.identity.digest + '\n')
        # Flush file metadata before rename where supported.
        for directory in (staging, staging.parent):
            try:
                fd = os.open(directory, os.O_RDONLY)
            except OSError:
                continue
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        if destination.exists():
            if not replace:
                raise PublicationError(f'destination appeared during publication: {destination}')
            backup = destination.with_name(destination.name + '.old')
            if backup.exists():
                shutil.rmtree(backup)
            destination.rename(backup)
            try:
                staging.rename(destination)
            except Exception:
                backup.rename(destination)
                raise
            shutil.rmtree(backup)
        else:
            staging.rename(destination)
        return RunBundle.load(destination)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
