"""Bounded input discovery and immutable source inventory. Never executes source."""
from __future__ import annotations

import hashlib
import io
import os
import re
import stat
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath

from charset_normalizer import from_bytes

from dataforge.models import stable_id

UPSERT_SOURCE = """INSERT INTO source_files(file_id,workspace_id,ingestion_id,file_name,
    extension,relative_path,source_path,storage_path,raw_content,content_hash,file_size,
    encoding,line_count,parsing_status,error_details,metadata) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(file_id) DO UPDATE SET ingestion_id=excluded.ingestion_id,
    raw_content=excluded.raw_content,content_hash=excluded.content_hash,
    storage_path=excluded.storage_path,file_size=excluded.file_size,encoding=excluded.encoding,
    line_count=excluded.line_count,parsing_status='pending',error_details=excluded.error_details,
    metadata='{}',imported_at=excluded.imported_at"""


@dataclass
class Limits:
    max_files: int = 10000
    max_file_bytes: int = 20 * 1024 * 1024
    max_total_bytes: int = 200 * 1024 * 1024
    max_archive_bytes: int = 100 * 1024 * 1024
    max_ratio: int = 200


@dataclass
class ImportReport:
    discovered: int = 0
    accepted: int = 0
    skipped: int = 0
    duplicates: int = 0
    diagnostics: list[str] = field(default_factory=list)


def safe_relative(name: str) -> str:
    name = name.replace("\\", "/")
    p = PurePosixPath(name)
    if not name or p.is_absolute() or any(x in {"..", "."} for x in name.split("/")):
        raise ValueError("Unsafe relative path")
    if any(re.search(r'[<>:"|?*\x00-\x1f]', x) or x.endswith((".", " ")) or
           re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", x, re.I) for x in p.parts):
        raise ValueError("Unsafe filename")
    return str(p)


def decode(data: bytes) -> tuple[str, str, str]:
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
    def __init__(self, store, workspace: str, allowed_roots=(), limits: Limits | None = None):
        self.store, self.workspace = store, workspace
        self.roots = [Path(r).resolve() for r in allowed_roots]
        self.limits = limits or Limits()

    def zip(self, data: bytes, extensions: set[str], progress=None, cancelled=None):
        if len(data) > self.limits.max_archive_bytes:
            raise ValueError("Archive exceeds compressed size limit")
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            entries = [e for e in z.infolist() if not e.is_dir()]
            if len(entries) > self.limits.max_files:
                raise ValueError("Archive exceeds file count limit")
            if sum(e.file_size for e in entries) > self.limits.max_total_bytes:
                raise ValueError("Archive exceeds decompressed size limit")

            def read(e):
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
                                "ZIP upload", progress, cancelled)

    def directory(self, directory: str | Path, extensions: set[str], progress=None, cancelled=None):
        path = Path(directory).resolve()
        if not any(path.is_relative_to(root) for root in self.roots):
            raise ValueError("Directory is outside the configured allowed roots")
        if not path.is_dir():
            raise ValueError("Directory does not exist")

        def discover():
            for parent, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = sorted(d for d in dirs if not (Path(parent) / d).is_symlink())
                for name in sorted(files):
                    p = Path(parent) / name

                    def read(p=p):
                        if p.is_symlink() or not p.resolve().is_relative_to(path):
                            raise ValueError("Symbolic links are not imported")
                        with p.open("rb") as f:
                            return f.read(self.limits.max_file_bytes + 1)

                    yield p.relative_to(path).as_posix(), read

        return self._import(discover(), extensions, str(path), progress, cancelled)

    def files(self, entries, extensions: set[str], progress=None, cancelled=None):
        return self._import(((name, lambda data=data: data) for name, data in entries), extensions,
                            "Browser upload", progress, cancelled)

    def _import(self, entries, extensions, source, progress, cancelled):
        import json

        if not extensions <= {".sql", ".sas", ".csv"} or not extensions:
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
                    report.diagnostics.append("Total byte budget exhausted; remaining files were not read")
                    break
                if cancelled and cancelled():
                    report.diagnostics.append("Import cancelled; accepted files retained")
                    break
                report.discovered += 1
                if report.discovered > self.limits.max_files:
                    raise ValueError("Import exceeds file count limit; inventory rolled back")
                try:
                    relative = safe_relative(name)
                    ext = PurePosixPath(relative).suffix.lower()
                    if ext not in extensions:
                        report.skipped += 1
                        continue
                    if relative in paths:
                        raise ValueError("Duplicate path in import; first entry retained")
                    paths.add(relative)
                    data = reader()
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
                         len(text.splitlines()), "pending", warning, "{}"])
                    report.accepted += 1
                    if warning:
                        report.diagnostics.append(f"{relative}: {warning}")
                except (ValueError, OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    report.skipped += 1
                    report.diagnostics.append(f"{name}: {exc}")
                if progress:
                    progress(report)
            if records:
                self.store.db.executemany(UPSERT_SOURCE, records)
            self.store.execute("INSERT INTO ingestion_runs(ingestion_id,workspace_id,source,report) VALUES (?,?,?,?)",
                               [ingestion, self.workspace, source, json.dumps(asdict(report))])
        return report
