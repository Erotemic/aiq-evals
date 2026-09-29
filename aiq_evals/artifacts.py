"""Engine-independent run bundle publication and reading."""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from aiq_evals.contracts import (
    MANIFEST_SCHEMA_VERSION,
    ArtifactReference,
    EvaluationResult,
    ExecutionContext,
    ResolvedEvaluation,
)
from aiq_evals.errors import ArtifactError, PublicationError
from aiq_evals.jsonutil import JSONValue, normalize_json, sha256_file, sha256_json

RUN_COMPLETE = 'RUN_COMPLETE'
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


def inventory_tree(root: Path, *, role: str = 'native') -> tuple[ArtifactReference, ...]:
    """Checksum all regular files below *root* using POSIX relative paths."""
    if not root.exists():
        return ()
    refs: list[ArtifactReference] = []
    for path in sorted(p for p in root.rglob('*') if p.is_file()):
        rel = path.relative_to(root).as_posix()
        refs.append(
            ArtifactReference(
                path=rel,
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
                role=role,
            )
        )
    return tuple(refs)


@dataclass(frozen=True)
class RunBundle:
    """Dependency-free view of one published aiq-evals run."""

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
            refs: list[ArtifactReference] = []
            for row in manifest.get('native_artifacts', []):
                ref = ArtifactReference.from_dict(row)
                refs.append(ref)
                artifact = root / 'native' / ref.path
                if not artifact.is_file():
                    raise ArtifactError(f'missing native artifact {ref.path!r}')
                if artifact.stat().st_size != ref.size_bytes or sha256_file(artifact) != ref.sha256:
                    raise ArtifactError(f'native artifact checksum mismatch: {ref.path!r}')
            native_identity = sha256_json([ref.to_dict() for ref in refs])
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


def copy_native_tree(source: Path, dest: Path, *, external_symlinks: str = 'exclude') -> dict[str, list[str]]:
    """Copy a native artifact tree without silently following links out of it.

    Links resolving inside ``source`` are copied as their content. Special files
    (FIFOs, sockets, devices) and dangling links are never copied. Returns manifest notes listing
    relative paths of excluded or followed external links and skipped
    non-regular files.
    """
    if external_symlinks not in _EXTERNAL_SYMLINK_MODES:
        raise ValueError(f'external_symlinks must be one of {_EXTERNAL_SYMLINK_MODES}')
    root = source.resolve()
    notes: dict[str, list[str]] = {
        'excluded_external_symlinks': [],
        'followed_external_symlinks': [],
        'skipped_non_regular_files': [],
    }

    def visit(directory: Path, target_dir: Path, *, followed: bool) -> None:
        target_dir.mkdir(parents=True, exist_ok=True)
        for entry in sorted(directory.iterdir()):
            rel = (target_dir / entry.name).relative_to(dest).as_posix()
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
                visit(entry, target_dir / entry.name, followed=is_followed)
            elif real.is_file():
                shutil.copy2(real, target_dir / entry.name)
            else:
                notes['skipped_non_regular_files'].append(rel)

    visit(source, dest, followed=False)
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
) -> RunBundle:
    """Atomically publish one terminal run bundle.

    ``external_symlinks`` controls links in ``native_dir`` whose targets lie
    outside it: ``'exclude'`` (default) leaves them out, ``'raise'`` refuses,
    and ``'follow'`` copies their content. Copying an arbitrary link target
    into a bundle could publish unrelated host files. Whatever happens is
    recorded in the manifest.

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
        _write_json(staging / 'attempt.json', attempt)
        native_artifact_identity = sha256_json([ref.to_dict() for ref in native_refs])
        normalized_artifact_identity = sha256_json(
            {
                'measurement_identity': resolved.identity.digest,
                'adapter_version': resolved.adapter_version,
                'result_schema_version': result.schema_version,
                'native_artifact_identity': native_artifact_identity,
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
            'native_artifact_identity': native_artifact_identity,
            'normalized_artifact_identity': normalized_artifact_identity,
        }
        # Optional (ADR-0009 allows additions): symlink handling is recorded so
        # a reader can tell which native paths were followed or left out.
        manifest.update({key: value for key, value in link_notes.items() if value})
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
