"""Pure operation-aware reconciliation and accepted sparse publication operations."""
from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field

from dataforge.ai_analysis_models import (
    DerivationInput,
    EvidenceCitation,
    NormalizedFact,
    ValidationContext,
    ValidationReport,
)
from dataforge.ai_validation import _detail, expression_key, operation_contexts
from dataforge.models import AssetRef, Operation, ParseResult, Usage, canonical, stable_id

RECONCILIATION_VERSION = "1"


@dataclass
class ReconciliationReport:
    facts: list = field(default_factory=list)
    operations: list[Operation] = field(default_factory=list)
    assets: list[AssetRef] = field(default_factory=list)
    supports: list[dict] = field(default_factory=list)
    agreed: list[str] = field(default_factory=list)
    parser_only: list = field(default_factory=list)
    ai_only: list = field(default_factory=list)
    conflicts: list[dict] = field(default_factory=list)
    omissions: list[dict] = field(default_factory=list)
    rejected: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)

    @property
    def accepted(self):
        return self.facts


def normalize_parser_facts(parsed, context):
    """Use the same original operation coordinates as the AI validator; never array order identity."""
    context = context if isinstance(context, ValidationContext) else ValidationContext.model_validate(context)
    facts = []
    for op, start, stop, key in operation_contexts(context, parsed):
        common = dict(unit_id=context.unit.unit_id, evidence_key=key,
                      evidence=EvidenceCitation.from_unit(context.unit), origin="parser",
                      detail=_detail(op, start, stop, context))
        pairs = op.table_pairs if op.table_pairs is not None else [
            (source, target) for source in range(len(op.sources)) for target in range(len(op.targets))]
        for source, target in pairs:
            if not 0 <= source < len(op.sources) or not 0 <= target < len(op.targets):
                raise ValueError("Invalid parser table pair")
            facts.append(NormalizedFact(kind="table_edge", source=op.sources[source].name,
                                        target=op.targets[target].name, operation=op.kind,
                                        status="inferred" if op.confidence < 1 else "verified", **common))
        for usage in op.usages:
            fact = NormalizedFact(kind="direct_usage", table=usage.table, column=usage.column,
                                  operation=usage.context, expression=usage.expression,
                                  status=usage.status, **common)
            fact.detail = {**fact.detail, "usage": asdict(usage)}
            facts.append(fact)
        for record in op.derivations:
            fact = NormalizedFact(kind="derivation", table=record["target_table"], column=record["target_column"],
                                  expression=record["expression"], scope=record.get("scope", ""),
                                  branch=record.get("branch", 0), version=record.get("target_version", ""),
                                  ordinal=record.get("ordinal", 0),
                                  inputs=[{k: v for k, v in item.items() if k in DerivationInput.model_fields}
                                          for item in record["inputs"]],
                                  status=record.get("status", "unresolved"), **common)
            fact.detail = {**fact.detail, "derivation": record.copy()}
            facts.append(fact)
    return facts


def _norm(value, context):
    return value.strip() if context and context.settings.get("case_sensitive") else canonical(value)


def fact_key(fact, context=None):
    """Full semantic identity, including operation/job/source, output position and role structure."""
    def norm(value):
        return _norm(value, context)
    base = (fact.evidence_key, fact.evidence.file_id, fact.evidence.content_hash,
            fact.detail.get("workspace_id", ""), fact.detail.get("job_id", ""), fact.kind)
    if fact.kind == "table_edge":
        return (*base, norm(fact.source), norm(fact.target), fact.operation.upper())
    dialect = context.settings.get("dialect", "") if context else ""
    if fact.kind == "direct_usage":
        return (*base, norm(fact.table), norm(fact.column), fact.operation.upper(),
                expression_key(fact.expression, dialect))
    inputs = tuple(sorted((norm(i.table), norm(i.column), i.role, i.scope, str(i.version)) for i in fact.inputs))
    return (*base, norm(fact.table), norm(fact.column), fact.scope, fact.branch, str(fact.version),
            fact.ordinal, expression_key(fact.expression, dialect),
            fact.detail.get("derivation", {}).get("category", ""), inputs)


def _slot(fact, context):
    return (fact.evidence_key, _norm(fact.table, context), _norm(fact.column, context),
            fact.scope, fact.branch, str(fact.version), fact.ordinal)


def _publication_operations(facts, mode, context):
    grouped = defaultdict(list)
    for fact in facts:
        grouped[fact.evidence_key].append(fact)
    operations = []
    for key, items in grouped.items():
        host = items[0].detail.get("operation")
        if not host:
            raise ValueError("Accepted facts require a host-established operation")
        needed = set()
        for fact in items:
            needed.update(_norm(name, context) for name in (fact.source, fact.target, fact.table) if name)
            needed.update(_norm(i.table, context) for i in fact.inputs if not i.scope)
        sources = [AssetRef(**ref) for ref in host["sources"] if _norm(ref["name"], context) in needed]
        targets = [AssetRef(**ref) for ref in host["targets"] if _norm(ref["name"], context) in needed]
        has_parser = mode == "hybrid" and any(fact.origin in {"parser", "both"} for fact in items)
        op = Operation(host["kind"], sources, targets, host["code"], host["start"], host["end"],
                       method=host.get("method", "parser") if has_parser else "ai-project",
                       confidence=host.get("confidence", 1.0) if has_parser else .8,
                       warnings=list(host.get("warnings", [])), evidence_key=key, table_pairs=[])
        for fact in items:
            if fact.kind == "table_edge":
                # Disputed table facts remain in the report; only accepted relationships become adjacency.
                if fact.status == "unresolved":
                    continue
                source = next(i for i, ref in enumerate(sources) if _norm(ref.name, context) == _norm(fact.source, context))
                target = next(i for i, ref in enumerate(targets) if _norm(ref.name, context) == _norm(fact.target, context))
                if (source, target) not in op.table_pairs:
                    op.table_pairs.append((source, target))
            elif fact.kind == "direct_usage":
                usage = fact.detail.get("usage", {})
                op.usages.append(Usage(fact.table, fact.column, fact.operation,
                                       usage.get("alias", ""), fact.expression, fact.status,
                                       usage.get("wildcard_safe", False)))
            else:
                record = dict(fact.detail.get("derivation", {}))
                record.update(target_table=fact.table, target_column=fact.column, expression=fact.expression,
                              scope=fact.scope, branch=fact.branch, target_version=fact.version,
                              ordinal=fact.ordinal, inputs=[i.model_dump() for i in fact.inputs], status=fact.status)
                record.setdefault("category", "expression")
                record.setdefault("coverage", [])
                if fact.detail.get("conflict") and "Locally established semantic conflict" not in record["coverage"]:
                    record["coverage"] = [*record["coverage"], "Locally established semantic conflict"]
                op.derivations.append(record)
        operations.append(op)
    return operations


def reconcile_candidates(parser, ai, mode="hybrid", *, context=None):
    """Compare validated facts; model criticism or confidence cannot demote local facts."""
    if mode not in {"hybrid", "ai"}:
        raise ValueError("Reconciliation mode must be hybrid or ai")
    if context is not None and not isinstance(context, ValidationContext):
        context = ValidationContext.model_validate(context)
    if isinstance(parser, ParseResult):
        if context is None:
            raise ValueError("Parser reconciliation requires original source context")
        parser_facts = normalize_parser_facts(parser, context)
    else:
        parser_facts = list(parser)
    ai = ai if isinstance(ai, ValidationReport) else ValidationReport.model_validate(ai)
    report = ReconciliationReport(rejected=list(ai.rejected), unresolved=list(ai.unresolved))
    parser_by_key = {fact_key(fact, context): fact for fact in parser_facts}
    ai_by_key = {fact_key(fact, context): fact for fact in ai.accepted}
    for key in dict.fromkeys([*parser_by_key, *ai_by_key]):
        local, model = parser_by_key.get(key), ai_by_key.get(key)
        if local is not None and model is not None:
            fact = local.model_copy(deep=True, update={"origin": "both", "candidate_id": model.candidate_id})
            if mode == "ai" and fact.status == "verified":
                fact.status = "inferred"
            report.agreed.append(stable_id(json.dumps(key)))
        elif local is not None:
            report.parser_only.append(local)
            report.omissions.append({"kind": local.kind, "evidence_key": local.evidence_key,
                                     "reason": "ai_omission"})
            if mode == "ai":
                continue
            fact = local.model_copy(deep=True)
        else:
            fact = model.model_copy(deep=True, update={"origin": "ai"})
            if fact.status == "verified":
                fact.status = "inferred"
            report.ai_only.append(fact)
        report.facts.append(fact)
        fact_id = stable_id(json.dumps(key))
        for origin, support in (("parser", local), ("ai", model)):
            if support is not None:
                report.supports.append({"fact_id": fact_id, "kind": fact.kind, "origin": origin,
                                        "candidate_id": support.candidate_id,
                                        "evidence_key": fact.evidence_key,
                                        "evidence": support.evidence.model_dump()})
    # Only incompatible, locally supported derivations in one exact output slot are contradictions.
    slots = defaultdict(list)
    for fact in [*parser_facts, *ai.accepted]:
        if fact.kind == "derivation" and fact.status != "unresolved":
            slots[_slot(fact, context)].append(fact)
    for items in slots.values():
        if len({fact_key(fact, context) for fact in items}) > 1:
            report.conflicts.append({"evidence_key": items[0].evidence_key,
                                     "table": items[0].table, "column": items[0].column,
                                     "reason": "locally_established_semantic_conflict"})
            for fact in report.facts:
                if fact.kind == "derivation" and _slot(fact, context) == _slot(items[0], context):
                    fact.status = "unresolved"
                    fact.detail["conflict"] = True
    report.operations = _publication_operations(report.facts, mode, context)
    existing_keys = {operation.evidence_key for operation in report.operations}
    locations = {fact.evidence_key: fact.detail['operation_span'][0] for fact in report.facts}
    if mode == 'hybrid' and isinstance(parser, ParseResult):
        declaration_indexes = {record.get('operation_index') for record in parser.metadata.get('declared_schemas', [])}
        declaration_ids = {id(operation) for index, operation in enumerate(parser.operations) if index in declaration_indexes}
        for operation, start, _, key in operation_contexts(context, parser):
            locations[key] = start
            if id(operation) in declaration_ids and key not in existing_keys:
                report.operations.append(Operation(operation.kind, list(operation.sources), list(operation.targets),
                    operation.code, operation.start, operation.end, method=operation.method,
                    confidence=operation.confidence, evidence_key=key, table_pairs=[]))
                existing_keys.add(key)
    for asset in ai.assets:
        key, host = asset.get('evidence_key'), asset.get('operation')
        if key and host and key not in existing_keys:
            targets = [AssetRef(**ref) for ref in host['targets']
                       if _norm(ref['name'], context) == _norm(asset['name'], context)]
            report.operations.append(Operation(host['kind'], [], targets, host['code'], host['start'], host['end'],
                method='ai-project' if mode == 'ai' else host.get('method', 'parser'),
                confidence=.8 if mode == 'ai' else host.get('confidence', 1.0), evidence_key=key, table_pairs=[]))
            locations[key] = asset['operation_span'][0]
            existing_keys.add(key)
    report.operations.sort(key=lambda operation: locations[operation.evidence_key])
    assets = list(ai.assets)
    if mode == "hybrid" and isinstance(parser, ParseResult):
        # Standalone parser assets (CSV/schema) are already local; SQL declarations have target refs.
        assets.extend(asdict(asset) for asset in parser.assets)
    report.assets = list({(asset["name"], asset.get("temporary", False), asset.get("kind", "table")):
                          AssetRef(asset['name'], asset.get('temporary', False), asset.get('kind', 'table'))
                          for asset in assets}.values())
    report.counts = {"accepted": sum(f.status != "unresolved" for f in report.facts), "agreed": len(report.agreed),
                     "parser_only": len(report.parser_only), "ai_only": len(report.ai_only),
                     "conflicts": len(report.conflicts), "rejected": len(report.rejected),
                     "unresolved": len(report.unresolved) + sum(f.status == "unresolved" for f in report.facts),
                     "omissions": len(report.omissions)}
    return report
