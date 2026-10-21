"""Bounded follow-up extraction; only host-validated new facts can make progress."""
from __future__ import annotations


def plan_resolution(report):
    if report.resolution_done or report.resolution_rounds >= 2 or not report.unresolved:
        return None
    return {'round': report.resolution_rounds + 1,
            'candidate_ids': [d.candidate_id for d in report.unresolved[:100]],
            'reasons': sorted({d.reason for d in report.unresolved[:100]}),
            'instruction': 'Resolve only these uncertainties using the original unit and declared context. Abstain where no source proof exists.'}


def apply_resolution(previous, validated):
    result = previous.model_copy(deep=True)
    known = {f.candidate_id for f in result.accepted}
    added = [f for f in validated.accepted if f.candidate_id not in known]
    result.accepted.extend(added)
    resolved = {f.candidate_id for f in validated.accepted}
    result.unresolved = [d for d in result.unresolved if d.candidate_id not in resolved]
    result.resolution_rounds = min(2, result.resolution_rounds + 1)
    result.resolution_done = not added or not result.unresolved or result.resolution_rounds >= 2
    # A follow-up model cannot certify missing coverage or retract established facts.
    return result, bool(added)
