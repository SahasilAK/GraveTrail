"""Bounded input discovery and immutable source inventory. Never executes source."""
from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import uuid
import zipfile
from collections.abc import Callable, Iterable, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

from charset_normalizer import from_bytes

from dataforge.models import stable_id

UPSERT_SOURCE = """INSERT INTO source_files(file_id,workspace_id,ingestion_id,file_name,
    extension,relative_path,source_path,storage_path,raw_content,content_hash,file_size,
    encoding,line_count,parsing_status,error_details,metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(file_id) DO UPDATE SET ingestion_id=excluded.ingestion_id,
    raw_content=excluded.raw_content,content_hash=excluded.content_hash,
    storage_path=excluded.storage_path,file_size=excluded.file_size,encoding=excluded.encoding,
    line_count=excluded.line_count,parsing_status='pending',error_details=excluded.error_details,
    metadata=excluded.metadata,imported_at=excluded.imported_at"""


@dataclass
class Limits:
    """Per-import ceilings for files, bytes, and archive compression."""

    max_files: int = 10000
    max_file_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 200 * 1024 * 1024
    max_archive_bytes: int = 100 * 1024 * 1024
    max_ratio: int = 200


@dataclass
class ImportReport:
    """Counts and diagnostics collected during one source import."""

    discovered: int = 0
    accepted: int = 0
    skipped: int = 0
    duplicates: int = 0
    diagnostics: list[str] = field(default_factory=list)


def safe_relative(name: str) -> str:
    """Validate and normalize an imported relative path.

    Args:
        name: Path supplied by an upload or archive entry.

    Returns:
        Normalized POSIX-style relative path.

    Raises:
        ValueError: If the path is absolute, traverses directories, or has an unsafe name.
    """
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if not name or p.is_absolute() or any(x in {"..", "."} for x in name.split("/")):
        raise ValueError("Unsafe relative path")
    if any(re.search(r'[<>:"|?*\x00-\x1f]', x) or x.endswith((".", " ")) or
           re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", x, re.I) for x in p.parts):
        raise ValueError("Unsafe filename")
    return str(p)


def decode(data: bytes) -> tuple[str, str, str]:
    """Decode supported text bytes and report any detected encoding warning.

    Args:
        data: Raw file contents.

    Returns:
        Decoded text, encoding name, and an optional warning string.

    Raises:
        ValueError: If the input appears binary or its text encoding cannot be detected.
    """
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16"), "utf-16", ""
    if b"\0" in data or (data and sum(c < 9 or 13 < c < 32 for c in data[:8192]) / min(len(data), 8192) > .05):
        raise ValueError("Binary content is not supported")
    try:
        return data.decode("utf-8-sig"), "utf-8-sig", ""
    except UnicodeDecodeError:
        match = from_bytes(data).best()
        if match is None:
            raise ValueError("Text encoding could not be detected") from None
        return str(match), match.encoding, f"Encoding detected as {match.encoding}; verify source text"


class Importer:
    """Import bounded source files into a workspace inventory."""

    def __init__(self, store: Any, workspace: str, allowed_roots: Iterable[str | Path] = (), limits: Limits | None = None) -> None:
        """Create an importer with workspace, root, and size constraints.

        Args:
            store: Persistence store used to record imported sources.
            workspace: Workspace identifier receiving the sources.
            allowed_roots: Filesystem roots permitted for directory imports.
            limits: Optional import limits; defaults to the standard limits.
        """
        self.store, self.workspace = store, workspace
        self.roots = [Path(r).resolve() for r in allowed_roots]
        self.limits = limits or Limits()

    def zip(self, data: bytes, extensions: set[str], progress: Callable[[ImportReport], Any] | None = None,
            cancelled: Callable[[], bool] | None = None, *, source_kind: str = 'files', dbt_options=None) -> ImportReport:
        """Import supported files from a ZIP upload.

        Args:
            data: Compressed archive bytes.
            extensions: Lowercase extensions allowed for import.
            progress: Optional callback invoked after each processed entry.
            cancelled: Optional predicate checked between entries.

        Returns:
            Report of discovered, accepted, skipped, and duplicate files.

        Raises:
            ValueError: If archive or import size limits are exceeded.
        """
        if len(data) > self.limits.max_archive_bytes:
            raise ValueError("Archive exceeds compressed size limit")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = [e for e in z.infolist() if not e.is_dir()]
            if len(entries) > self.limits.max_files:
                raise ValueError("Archive exceeds file count limit")
            if sum(e.file_size for e in entries) > self.limits.max_total_bytes:
                raise ValueError("Archive exceeds decompressed size limit")

            def read(e: zipfile.ZipInfo) -> bytes:
                """Read and validate one archive entry.

                Args:
                    e: ZIP member metadata to validate and read.

                Returns:
                    Bounded uncompressed member bytes.
                """
                safe_relative(e.filename)
                if stat.S_ISLNK(e.external_attr >> 16):
                    raise ValueError("Symbolic links are not imported")
                if e.file_size > self.limits.max_file_bytes:
                    raise ValueError("File exceeds size limit")
                if e.file_size / max(e.compress_size, 1) > self.limits.max_ratio:
                    raise ValueError("Archive entry exceeds compression ratio limit")
                with z.open(e) as f:
                    return f.read(self.limits.max_file_bytes + 1)

            return self._import(((e.filename, lambda e=e: read(e)) for e in entries), extensions,
                                "ZIP upload", progress, cancelled, source_kind=source_kind, dbt_options=dbt_options)

    def directory(self, directory: str | Path, extensions: set[str], progress: Callable[[ImportReport], Any] | None = None,
                  cancelled: Callable[[], bool] | None = None, *, source_kind: str = 'files', dbt_options=None) -> ImportReport:
        """Import supported files beneath an authorized directory.

        Args:
            directory: Directory to traverse under an allowed root.
            extensions: Lowercase extensions allowed for import.
            progress: Optional callback invoked after each processed file.
            cancelled: Optional predicate checked between files.

        Returns:
            Import report for the traversed directory.

        Raises:
            ValueError: If the directory is unauthorized or import limits are exceeded.
        """
        # Normalize without touching the requested path, then check a complete root
        # boundary before resolve/stat/walk. The trailing separator also admits the
        # root itself without admitting siblings such as "allowed-private".
        candidate = os.path.join(os.path.normcase(os.path.abspath(os.fspath(directory))), "")
        for root in self.roots:
            if candidate.startswith(os.path.join(os.path.normcase(str(root)), "")):
                path = Path(candidate).resolve()
                break
        else:
            raise ValueError("Directory is outside the configured allowed roots")
        # A lexically contained directory can still be a link to an unapproved root.
        if not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError("Directory is outside the configured allowed roots")
        if not path.is_dir():
            raise ValueError("Directory does not exist")

        def discover() -> Iterator[tuple[str, Callable[[], bytes]]]:
            """Yield safe relative paths and deferred file readers.

                Yields:
                    Discovered paths paired with callbacks that read their bytes.
            """
            for parent, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not (Path(parent) / d).is_symlink())
                for name in sorted(files):
                    p = Path(parent) / name

                    def read(p: Path = p) -> bytes:
                        """Read a discovered file after checking its path remains safe.

                        Args:
                            p: File path to validate and read.

                        Returns:
                            Bounded file bytes.
                        """
                        if p.is_symlink() or not p.resolve().is_relative_to(path):
                            raise ValueError("Symbolic links are not imported")
                        with p.open("rb") as f:
                            return f.read(self.limits.max_file_bytes + 1)

                    yield p.relative_to(path).as_posix(), read

        return self._import(discover(), extensions, str(path), progress, cancelled,
                            source_kind=source_kind, dbt_options=dbt_options)

    def files(self, entries: Iterable[tuple[str, bytes]], extensions: set[str],
              progress: Callable[[ImportReport], Any] | None = None,
              cancelled: Callable[[], bool] | None = None, *, source_kind: str = 'files', dbt_options=None) -> ImportReport:
        """Import files supplied as browser upload entries.

        Args:
            entries: Relative file names paired with raw contents.
            extensions: Lowercase extensions allowed for import.
            progress: Optional callback invoked after each processed file.
            cancelled: Optional predicate checked between files.

        Returns:
            Import report for the upload.
        """
        return self._import(((name, lambda data=data: data) for name, data in entries), extensions,
                            "Browser upload", progress, cancelled, source_kind=source_kind, dbt_options=dbt_options)

    def _import(self, entries: Iterable[tuple[str, Callable[[], bytes]]], extensions: set[str], source: str,
                progress: Callable[[ImportReport], Any] | None, cancelled: Callable[[], bool] | None,
                *, source_kind: str = 'files', dbt_options=None) -> ImportReport:
        """Validate entries and record accepted source files transactionally.

        Args:
            entries: File names paired with deferred byte readers.
            extensions: Lowercase extensions allowed for import.
            source: Human-readable source label recorded in the inventory.
            progress: Optional callback invoked after each processed entry.
            cancelled: Optional predicate checked between entries.

        Returns:
            Counts and diagnostics from the completed import.

        Raises:
            ValueError: If extension selection or aggregate import limits are invalid.
        """
        import json

        if source_kind not in {'files', 'dbt'}:
            raise ValueError('Unknown source kind')
        admission, buffered = None, {}
        if source_kind == 'dbt':
            from dataforge.dbt.imports import DbtImportOptions, preview_dbt_import
            bounded = []
            for entry in entries:
                bounded.append(entry)
                if len(bounded) > self.limits.max_files:
                    raise ValueError('Import exceeds file count limit')
            readers = dict(bounded)

            def read_config(path):
                data = readers[path]()
                if len(data) > self.limits.max_file_bytes:
                    raise ValueError('File exceeds size limit')
                buffered[path] = data
                if sum(map(len, buffered.values())) > self.limits.max_total_bytes:
                    raise ValueError('Import exceeds total byte budget')
                return decode(data)[0]

            options = dbt_options or DbtImportOptions()
            if isinstance(options, dict):
                options = DbtImportOptions(**options)
            admission = preview_dbt_import([name for name, _ in bounded], options, read_config)
            entries = bounded
        elif not extensions <= {".sql", ".sas", ".csv"} or not extensions:
            raise ValueError("Select at least one supported extension")
        report = ImportReport()
        ingestion = uuid.uuid4().hex
        total = 0
        known = {f["content_hash"] for f in self.store.files(self.workspace)}
        paths = set()
        records = []
        with self.store.transaction():
            for name, reader in entries:
                if total >= self.limits.max_total_bytes:
                    if admission is not None:
                        raise ValueError('dbt import exceeds total byte budget; inventory rolled back')
                    report.diagnostics.append("Total byte budget exhausted; remaining files were not read")
                    break
                if cancelled and cancelled():
                    if admission is not None:
                        raise ValueError('dbt import cancelled; inventory rolled back')
                    report.diagnostics.append("Import cancelled; accepted files retained")
                    break
                report.discovered += 1
                if report.discovered > self.limits.max_files:
                    raise ValueError("Import exceeds file count limit; inventory rolled back")
                try:
                    relative = safe_relative(name)
                    ext = PurePosixPath(relative).suffix.lower()
                    if (admission is not None and relative not in admission.paths) or (admission is None and ext not in extensions):
                        report.skipped += 1
                        continue
                    if relative in paths:
                        raise ValueError("Duplicate path in import; first entry retained")
                    paths.add(relative)
                    data = buffered[relative] if relative in buffered else reader()
                    if len(data) > self.limits.max_file_bytes:
                        raise ValueError("File exceeds size limit")
                    total += len(data)
                    if total > self.limits.max_total_bytes:
                        raise ValueError("Import exceeds total byte budget")
                    text, encoding, warning = decode(data)
                    digest = hashlib.sha256(data).hexdigest()
                    report.duplicates += digest in known
                    known.add(digest)
                    blob = self.store.home / "blobs" / digest
                    if not blob.exists():
                        blob.write_bytes(data)
                    fid = stable_id(self.workspace, relative)
                    records.append([fid, self.workspace, ingestion, PurePosixPath(relative).name, ext, relative,
                         source + "/" + relative, "blobs/" + digest, text, digest, len(data), encoding,
                         len(text.splitlines()), "pending", warning,
                         json.dumps(admission.paths[relative]) if admission is not None else "{}"])
                    report.accepted += 1
                    if warning:
                        report.diagnostics.append(f"{relative}: {warning}")
                except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    if admission is not None:
                        raise ValueError(f'dbt import failed at {name}: {exc}; inventory rolled back') from exc
                    report.skipped += 1
                    report.diagnostics.append(f"{name}: {exc}")
                if progress:
                    progress(report)
            if records:
                self.store.db.executemany(UPSERT_SOURCE, records)
            self.store.execute("INSERT INTO ingestion_runs(ingestion_id,workspace_id,source,report) VALUES (?,?,?,?)",
                               [ingestion, self.workspace, source, json.dumps(asdict(report))])
        return report
