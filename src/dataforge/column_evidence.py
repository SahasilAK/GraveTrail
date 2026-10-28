"""Validated, lazy source resolution for the local column lineage inspector."""

from __future__ import annotations

import json
import re
from typing import Any

from dataforge.store import Store


def load_column_evidence(store: Store, workspace: str, run_id: str, derivation_id: str,
                         *, include_file: bool = False) -> dict[str, Any]:
    """Resolve a current derivation and, on request, its exact analyzed source.

    Browser selections identify only derivations. All file, hash and coordinate
    information comes from workspace-scoped stored relationships under one lock.
    An old analysis selection returns ``stale_run`` without exposing new evidence.
    Full source and original bytes are never loaded for logic-only inspection.
    """
    with store.lock:
        if not store.rows('SELECT 1 FROM workspaces WHERE workspace_id=?', [workspace]):
            raise ValueError('Workspace does not exist')
        if not store.rows("SELECT 1 FROM analysis_runs WHERE workspace_id=? AND run_id=? AND status='completed'",
                          [workspace, run_id]):
            raise ValueError('Analysis run does not belong to this workspace')
        result = {'state': 'stale_run', 'derivation_id': derivation_id, 'expression': '',
                  'coverage': [], 'evidence': {}, 'statement_preview': {}}
        if include_file:
            result['file'] = None
        current = store.rows('SELECT run_id FROM column_analysis WHERE workspace_id=?', [workspace])
        if not current or current[0]['run_id'] != run_id:
            return result

        rows = store.rows('''SELECT d.expression,d.coverage,d.file_id,d.statement_id,d.operation_id,
            s.start_line,s.end_line,s.content_hash AS source_hash,
            substr(s.code,1,12000) AS code,length(s.code)>12000 AS source_truncated,
            f.file_id AS validated_file_id,f.relative_path,f.extension,f.content_hash AS current_hash,o.method,o.warnings
            FROM column_derivations d
            JOIN statements s ON s.statement_id=d.statement_id AND s.workspace_id=d.workspace_id
                AND s.file_id=d.file_id
            LEFT JOIN source_files f ON f.file_id=d.file_id AND f.workspace_id=d.workspace_id
            JOIN operations o ON o.operation_id=d.operation_id AND o.workspace_id=d.workspace_id
                AND o.statement_id=d.statement_id
            WHERE d.workspace_id=? AND d.run_id=? AND d.derivation_id=?''',
            [workspace, run_id, derivation_id])
        if not rows:
            raise ValueError('Derivation or its evidence does not belong to this workspace and run')
        row = rows[0]
        if not row['validated_file_id'] and store.rows('SELECT 1 FROM source_files WHERE file_id=?', [row['file_id']]):
            raise ValueError('Evidence file does not belong to this workspace')
        coverage = json.loads(row['coverage'])
        warnings = json.loads(row['warnings'] or '[]')
        compiled = any('compiled sql' in str(message).lower() for message in [*coverage, *warnings])
        language = {'.sql': 'sql', '.sas': 'sas', '.json': 'json', '.yml': 'yaml', '.yaml': 'yaml'}.get(
            (row['extension'] or '').lower(), 'text')
        focus = (bool(row['validated_file_id']) and not compiled
                 and isinstance(row['start_line'], int) and isinstance(row['end_line'], int)
                 and 1 <= row['start_line'] <= row['end_line'])
        evidence = {key: row[key] for key in ('file_id', 'statement_id', 'operation_id', 'relative_path',
                                              'start_line', 'end_line', 'source_hash', 'method')}
        evidence.update(language=language, origin='compiled_sql' if compiled else 'original',
                        focus_available=focus, coordinate_warning=(
                            'Expression comes from supplied compiled SQL; source mapping is unavailable. '
                            'Compiled SQL coordinates cannot focus the original source or artifact.' if compiled else ''))
        result.update(state='available', expression=row['expression'], coverage=coverage, evidence=evidence,
                      statement_preview={'code': row['code'] or '', 'truncated': bool(row['source_truncated']),
                                         'language': language})
        if not row['validated_file_id']:
            result['state'] = 'missing_version'
            return result
        if not include_file:
            return result

        digest = row['source_hash'] or ''
        try:
            if not re.fullmatch(r'[0-9a-f]{64}', digest):
                raise ValueError('Analyzed source hash is unavailable')
            source = store.file(row['file_id'], digest)
            # Verify even current versions against immutable bytes, not a cached text field.
            text = store.snapshot_content(source)
        except (OSError, ValueError, LookupError):
            result['state'] = 'missing_version'
            return result
        result['file'] = {key: source[key] for key in ('file_id', 'file_name', 'relative_path', 'extension',
                                                       'content_hash', 'file_size', 'encoding', 'line_count')}
        result['file'].update(raw_content=text, language=language, version_mismatch=digest != row['current_hash'],
                              focus_start_line=row['start_line'] if focus else None,
                              focus_end_line=row['end_line'] if focus else None)
        return result
