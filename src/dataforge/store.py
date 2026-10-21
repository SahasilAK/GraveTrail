"""Versioned DuckDB persistence with serialized, transactional access."""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from dataforge.configuration import WorkspaceIdentity

COLUMN_TABLES = ('column_dependencies', 'column_derivations', 'column_references', 'column_analysis')
AI_SNAPSHOT_TABLES = ('ai_analysis_snapshots',)
AI_ANALYSIS_TABLES = (*AI_SNAPSHOT_TABLES, 'analysis_fact_support', 'ai_analysis_claims', 'ai_analysis_units', 'ai_analysis_runs')

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS workspaces(workspace_id VARCHAR PRIMARY KEY, name VARCHAR, description VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS settings(workspace_id VARCHAR, key VARCHAR, value VARCHAR, PRIMARY KEY(workspace_id, key));
CREATE TABLE IF NOT EXISTS ingestion_runs(ingestion_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, source VARCHAR, report VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS source_files(file_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, ingestion_id VARCHAR, file_name VARCHAR, extension VARCHAR, relative_path VARCHAR, source_path VARCHAR, storage_path VARCHAR, raw_content VARCHAR, content_hash VARCHAR, file_size BIGINT, encoding VARCHAR, line_count INTEGER, parsing_status VARCHAR, error_details VARCHAR, metadata VARCHAR, imported_at TIMESTAMP DEFAULT current_timestamp);
CREATE INDEX IF NOT EXISTS files_workspace ON source_files(workspace_id);
CREATE TABLE IF NOT EXISTS parse_cache(cache_key VARCHAR PRIMARY KEY, result VARCHAR);
CREATE TABLE IF NOT EXISTS analysis_runs(run_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, status VARCHAR, analyzed INTEGER, cached INTEGER, duration DOUBLE, configuration VARCHAR, snapshot VARCHAR, error VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS assets(asset_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, name VARCHAR, canonical_name VARCHAR, kind VARCHAR, temporary BOOLEAN, metadata VARCHAR);
CREATE INDEX IF NOT EXISTS assets_workspace ON assets(workspace_id);
CREATE TABLE IF NOT EXISTS asset_aliases(workspace_id VARCHAR, alias VARCHAR, asset_id VARCHAR, method VARCHAR);
CREATE TABLE IF NOT EXISTS statements(statement_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, file_id VARCHAR, start_line INTEGER, end_line INTEGER, code VARCHAR);
CREATE TABLE IF NOT EXISTS operations(operation_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, statement_id VARCHAR, kind VARCHAR, method VARCHAR, confidence DOUBLE, warnings VARCHAR);
CREATE TABLE IF NOT EXISTS operation_assets(workspace_id VARCHAR, operation_id VARCHAR, asset_id VARCHAR, role VARCHAR);
CREATE TABLE IF NOT EXISTS edges(edge_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, source_id VARCHAR, target_id VARCHAR, operation_id VARCHAR, statement_id VARCHAR, file_id VARCHAR, kind VARCHAR, method VARCHAR, confidence DOUBLE, status VARCHAR, run_id VARCHAR);
CREATE INDEX IF NOT EXISTS edges_workspace ON edges(workspace_id);
CREATE TABLE IF NOT EXISTS column_usages(usage_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, asset_id VARCHAR, column_name VARCHAR, context VARCHAR, alias VARCHAR, expression VARCHAR, status VARCHAR, statement_id VARCHAR, file_id VARCHAR, operation_id VARCHAR);
CREATE TABLE IF NOT EXISTS diagnostics(diagnostic_id VARCHAR, workspace_id VARCHAR, file_id VARCHAR, line INTEGER, severity VARCHAR, message VARCHAR, symbol VARCHAR);
CREATE TABLE IF NOT EXISTS llm_profiles(profile_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, name VARCHAR, config VARCHAR);
CREATE TABLE IF NOT EXISTS llm_records(record_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, profile_id VARCHAR, task VARCHAR, file_id VARCHAR, start_line INTEGER, prompt_hash VARCHAR, provider VARCHAR, model VARCHAR, outcome VARCHAR, duration DOUBLE, usage VARCHAR, details VARCHAR, created_at TIMESTAMP DEFAULT current_timestamp);
CREATE TABLE IF NOT EXISTS prompt_versions(prompt_hash VARCHAR PRIMARY KEY, task VARCHAR, version VARCHAR);
"""


class Store:
    """Own a workspace database, immutable source blobs, and serialized access locks."""

    def __init__(self, home: str | Path) -> None:
        """Open or initialize the database and required workspace storage directories."""
        self.home = Path(home).resolve()
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "blobs").mkdir(exist_ok=True)
        self.lock = threading.RLock()
        self.analysis_lock = threading.Lock()
        self.db = duckdb.connect(str(self.home / "dataforge.duckdb"))
        with self.transaction():
            self.db.execute(SCHEMA)
            self.db.execute("INSERT INTO schema_migrations(version) VALUES (1) ON CONFLICT DO NOTHING")
            versions = self.db.execute("SELECT version FROM schema_migrations").fetchall()
            if (2,) not in versions:
                self.db.execute("ALTER TABLE statements ADD COLUMN IF NOT EXISTS content_hash VARCHAR DEFAULT ''")
                self.db.execute("UPDATE statements SET content_hash=f.content_hash FROM source_files f WHERE statements.file_id=f.file_id AND statements.content_hash=''")
                self.db.execute("INSERT INTO schema_migrations(version) VALUES (2)")
            if (3,) not in versions:
                self.db.execute("""CREATE TABLE history_archives(
                    archive_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, recovery_body BLOB,
                    archive_bytes BIGINT, created_at TIMESTAMP DEFAULT current_timestamp)""")
                self.db.execute("INSERT INTO schema_migrations(version) VALUES (3)")
            if (4,) not in versions:
                self.db.execute("""CREATE TABLE temporary_recovery(
                    recovery_id VARCHAR PRIMARY KEY, workspace_id VARCHAR, file_name VARCHAR,
                    recovery_body BLOB, byte_count BIGINT, sha256 VARCHAR,
                    created_at TIMESTAMP DEFAULT current_timestamp, restored_at TIMESTAMP)""")
                self.db.execute("INSERT INTO schema_migrations(version) VALUES (4)")
            if (5,) not in versions:
                self.db.execute("""
                    CREATE TABLE column_references(column_id VARCHAR PRIMARY KEY, workspace_id VARCHAR,
                        asset_id VARCHAR, table_name VARCHAR, column_name VARCHAR, column_key VARCHAR,
                        scope VARCHAR, version VARCHAR);
                    CREATE INDEX column_ref_asset ON column_references(workspace_id,asset_id,column_key);
                    CREATE TABLE column_derivations(derivation_id VARCHAR PRIMARY KEY, workspace_id VARCHAR,
                        target_column_id VARCHAR, expression VARCHAR, category VARCHAR, status VARCHAR,
                        statement_id VARCHAR, file_id VARCHAR, operation_id VARCHAR, run_id VARCHAR,
                        branch INTEGER, ordinal INTEGER, coverage VARCHAR);
                    CREATE INDEX column_derivation_target ON column_derivations(workspace_id,target_column_id);
                    CREATE TABLE column_dependencies(dependency_id VARCHAR PRIMARY KEY, workspace_id VARCHAR,
                        derivation_id VARCHAR, source_column_id VARCHAR, role VARCHAR, ordinal INTEGER);
                    CREATE INDEX column_input_source ON column_dependencies(workspace_id,source_column_id);
                    CREATE INDEX column_input_derivation ON column_dependencies(workspace_id,derivation_id);
                    CREATE TABLE column_analysis(workspace_id VARCHAR PRIMARY KEY, run_id VARCHAR,
                        parser_version VARCHAR);
                    INSERT INTO schema_migrations(version) VALUES (5);
                """)

            if (6,) not in versions:
                self.db.execute("""
                    CREATE TABLE ai_analysis_runs(run_id VARCHAR PRIMARY KEY, workspace_id VARCHAR,
                        analysis_run_id VARCHAR, mode VARCHAR, status VARCHAR, manifest VARCHAR,
                        configuration VARCHAR, summary VARCHAR, accepted_results VARCHAR,
                        created_at TIMESTAMP DEFAULT current_timestamp, updated_at TIMESTAMP DEFAULT current_timestamp);
                    CREATE TABLE ai_analysis_units(unit_id VARCHAR, workspace_id VARCHAR, run_id VARCHAR,
                        file_id VARCHAR, content_hash VARCHAR, start_char INTEGER, end_char INTEGER,
                        context_hash VARCHAR, status VARCHAR, record_id VARCHAR, result VARCHAR,
                        PRIMARY KEY(run_id,unit_id));
                    CREATE TABLE ai_analysis_claims(claim_id VARCHAR, workspace_id VARCHAR, run_id VARCHAR,
                        unit_id VARCHAR, kind VARCHAR, status VARCHAR, payload VARCHAR, reasons VARCHAR,
                        PRIMARY KEY(run_id,claim_id));
                    CREATE TABLE analysis_fact_support(support_id VARCHAR PRIMARY KEY, workspace_id VARCHAR,
                        run_id VARCHAR, fact_type VARCHAR, fact_id VARCHAR, claim_id VARCHAR,
                        engine VARCHAR, record_id VARCHAR, payload VARCHAR);
                    CREATE INDEX ai_runs_workspace ON ai_analysis_runs(workspace_id,status,created_at);
                    CREATE INDEX ai_units_run ON ai_analysis_units(workspace_id,run_id,status);
                    CREATE INDEX ai_claims_run ON ai_analysis_claims(workspace_id,run_id,status);
                    CREATE INDEX ai_support_fact ON analysis_fact_support(workspace_id,fact_type,fact_id);
                    CREATE INDEX ai_support_record ON analysis_fact_support(record_id);
                    INSERT INTO schema_migrations(version) VALUES (6);
                """)

            if (7,) not in versions:
                self.db.execute("""
                    CREATE TABLE ai_analysis_snapshots(run_id VARCHAR, workspace_id VARCHAR,
                        file_id VARCHAR, part INTEGER, content_hash VARCHAR, payload VARCHAR,
                        PRIMARY KEY(run_id,file_id,part));
                    CREATE INDEX ai_snapshots_workspace ON ai_analysis_snapshots(workspace_id,run_id,file_id);
                    INSERT INTO schema_migrations(version) VALUES (7);
                """)

    @contextmanager
    def transaction(self) -> Iterator[Store]:
        """Run operations under the store lock and roll back if the block raises."""
        with self.lock:
            self.db.execute("BEGIN TRANSACTION")
            try:
                yield self
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def execute(self, sql: str, params: Any = None) -> None:
        """Execute one parameterized SQL statement under the store lock."""
        with self.lock:
            self.db.execute(sql, params or [])

    def rows(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
        """Execute a query and return its rows as dictionaries keyed by column name."""
        with self.lock:
            cursor = self.db.execute(sql, params or [])
            columns = [d[0] for d in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def create_workspace(self, name: str, description: str = "") -> str:
        """Create a workspace after validating its display name and description.

        Args:
            name: Workspace display name.
            description: Optional workspace description.

        Returns:
            The new workspace identifier.
        """
        identity = WorkspaceIdentity(name=name, description=description)
        wid = uuid.uuid4().hex
        self.execute("INSERT INTO workspaces(workspace_id,name,description) VALUES (?,?,?)",
                     [wid, identity.name, identity.description])
        return wid

    def update_workspace(self, workspace: str, name: str, description: str = "") -> None:
        """Update a workspace's validated display name and description."""
        identity = WorkspaceIdentity(name=name, description=description)
        with self.transaction():
            if not self.rows("SELECT 1 FROM workspaces WHERE workspace_id=?", [workspace]):
                raise ValueError("Workspace does not exist")
            self.execute("UPDATE workspaces SET name=?,description=? WHERE workspace_id=?",
                         [identity.name, identity.description, workspace])

    def workspaces(self) -> list[dict[str, Any]]:
        """List workspace records ordered by creation time."""
        return self.rows("SELECT * FROM workspaces ORDER BY created_at")

    def setting(self, workspace: str, key: str, default: Any = None) -> Any:
        """Read a JSON setting value or return the supplied default when absent."""
        rows = self.rows("SELECT value FROM settings WHERE workspace_id=? AND key=?", [workspace, key])
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, workspace: str, key: str, value: Any) -> None:
        """Serialize and insert or replace a workspace setting."""
        self.execute("INSERT INTO settings VALUES (?,?,?) ON CONFLICT(workspace_id,key) DO UPDATE SET value=excluded.value",
                     [workspace, key, json.dumps(value)])

    def files(self, workspace: str) -> list[dict[str, Any]]:
        """List a workspace's source inventory without loading raw source content."""
        return self.rows("SELECT * EXCLUDE(raw_content) FROM source_files WHERE workspace_id=? ORDER BY relative_path",
                         [workspace])

    def file(self, file_id: str, content_hash: str | None = None) -> dict[str, Any]:
        """Load one source record and optionally retrieve a referenced historical version."""
        rows = self.rows("SELECT * FROM source_files WHERE file_id=?", [file_id])
        if not rows:
            raise ValueError("Source file no longer exists")
        source = rows[0]
        if content_hash and content_hash != source["content_hash"]:
            if not re.fullmatch(r"[0-9a-f]{64}", content_hash) or not self.rows(
                "SELECT 1 FROM statements WHERE file_id=? AND content_hash=? LIMIT 1", [file_id, content_hash]):
                raise ValueError("Original source version is not referenced by this file")
            from dataforge.ingestion import decode
            data = (self.home / "blobs" / content_hash).read_bytes()
            text, encoding, _ = decode(data)
            source.update(raw_content=text, content_hash=content_hash, file_size=len(data), encoding=encoding,
                          line_count=len(text.splitlines()), storage_path="blobs/" + content_hash)
        return source

    def original(self, file_id: str, content_hash: str | None = None) -> bytes:
        """Read the immutable original bytes for a current or referenced source version."""
        return (self.home / "blobs" / self.file(file_id, content_hash)["content_hash"]).read_bytes()

    def snapshot_content(self, inventory: dict[str, Any]) -> str:
        """Read an immutable inventory snapshot and verify its content hash."""
        digest = inventory["content_hash"]
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("Invalid inventory content hash")
        data = (self.home / "blobs" / digest).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("Original source blob failed integrity verification")
        return data.decode(inventory["encoding"])

    def assets(self, workspace: str) -> list[dict[str, Any]]:
        """List workspace assets ordered by name."""
        return self.rows("SELECT * FROM assets WHERE workspace_id=? ORDER BY name", [workspace])

    def edges(self, workspace: str) -> list[dict[str, Any]]:
        """List workspace lineage edges with statement and source evidence fields."""
        return self.rows("SELECT e.*,s.start_line,s.end_line,s.code,s.content_hash AS source_hash,f.relative_path FROM edges e JOIN statements s ON e.statement_id=s.statement_id JOIN source_files f ON e.file_id=f.file_id WHERE e.workspace_id=?", [workspace])

    def diagnostics(self, workspace: str) -> list[dict[str, Any]]:
        """List workspace diagnostics with source paths when available."""
        return self.rows("SELECT d.*,f.relative_path FROM diagnostics d LEFT JOIN source_files f USING(file_id) WHERE d.workspace_id=? ORDER BY relative_path,line", [workspace])

    def runs(self, workspace: str) -> list[dict[str, Any]]:
        """List workspace analysis runs newest first."""
        return self.rows("SELECT * FROM analysis_runs WHERE workspace_id=? ORDER BY created_at DESC", [workspace])

    def delete_workspace(
        self,
        workspace: str,
        *,
        preview: dict[str, Any] | None = None,
        confirmation: str = '',
        backup_first: bool = False,
    ) -> dict[str, Any]:
        """Delete a workspace through a validated cleanup preview and confirmation."""
        from dataforge.cleanup import apply_cleanup
        if not preview or preview.get('workspace_id') != workspace or preview.get('category') != 'workspace':
            raise ValueError('Use a confirmed cleanup preview to delete a workspace safely')
        return apply_cleanup(self, preview, confirmation, backup_first)

    def close(self) -> None:
        """Close the DuckDB connection under the store lock."""
        with self.lock:
            self.db.close()
