"""Reviewable code artifacts and immutable source anchors."""
from collections import Counter, defaultdict

from dataforge.migration.engine import digest


def artifacts(project, revision, details=None, notes=()):
    """Index generated files and untranslated spans without reading source bodies."""
    plan = revision["plan"]
    details = details or {"findings": [], "active": {}, "tiers": {}}
    regions = {item["id"]: item for item in plan["regions"]}
    sources = {item["id"]: item for item in project["snapshot"]["sources"]}
    by_model, by_region = defaultdict(list), defaultdict(list)
    for item in details["findings"]:
        if item["model"]:
            by_model[item["model"]].append(item)
        elif item["region"]:
            by_region[item["region"]].append(item)
    open_notes = Counter(note["artifact"] for note in notes if note["status"] == "open")
    result = {}

    def add(key, model, region, findings):
        file = revision["files"].get(model)
        active = details["active"].get(model)
        confidence = details["tiers"].get(model, "blocked")
        path = (f"models/{model}.sql" if active else f"review/{model}.sql.txt") if model else source_path(region)
        result[key] = {
            "id": key, "model": model, "path": path, "region": region, "source": sources[region["source"]],
            "file": file, "confidence": confidence, "status": active or ("draft_candidate" if file else "comment_only"),
            "findings": findings, "open_notes": open_notes[key],
        }

    for model, output in plan["outputs"].items():
        if not output.get("excluded"):
            region = regions[output["region"]]
            add(model, model, region, by_model[model] + by_region[region["id"]])
    for region in regions.values():
        if region["gap"] and not region["outputs"] and region["disposition"] not in {"excluded", "preserved"}:
            add("region:" + region["id"], None, region, by_region[region["id"]])
    return result


def source_path(region):
    return f"review/sources/{region['id']}.sql.txt"


def source_location(entry):
    region = entry["region"]
    if region.get("start_line"):
        return f"{entry['source']['path']} lines {region['start_line']}–{region['end_line']}"
    return f"{entry['source']['path']} offsets {region['start']}–{region['end']}"


def _comment(text):
    # SQL comments are still visible to dbt's Jinja lexer. Escape its opening delimiters too.
    value = str(text).replace("{{", "{ {").replace("{%", "{ %").replace("{#", "{ #")
    return ["-- " + line for line in value.splitlines()] or ["--"]


def annotated(entry, *, redact=lambda text: text, include_source_path=True):
    """Render findings next to verified generated lines, or in a header with a source anchor."""
    findings = entry["findings"]
    file = entry["file"]
    if file and digest(file["sql"]) != file["hash"]:
        raise ValueError("Generated artifact failed its integrity check")
    raw = redact(file["sql"]).splitlines() if file else []
    inert = any(item["code"] == "unsafe_sql" for item in findings)
    heading = "MIGRATION REVIEW · Runtime equivalence unverified"
    if entry["status"] in {"draft_candidate", "comment_only"}:
        heading = "REVIEW REQUIRED · Incomplete conversion"
    lines = _comment(heading) + _comment(source_location(entry))
    if entry["status"] == "comment_only":
        lines += _comment("No verified target SQL exists for this section. Supply the missing behavior before handoff.")
    if include_source_path and (findings or not file):
        lines += _comment(f"Original source section: {source_path(entry['region'])}")
    anchors = {}
    generated_lines = {}
    by_line = defaultdict(list)

    def add_finding(item):
        anchors[item["id"]] = len(lines) + 1
        lines.extend(_comment(f"[{item['severity'].upper()} {item['code']}] {redact(item['message'])}"))

    for item in findings:
        line = item.get("generated_line")
        if isinstance(line, int) and 1 <= line <= len(raw):
            by_line[line].append(item)
        else:
            add_finding(item)
    for number, line in enumerate(raw, 1):
        for item in by_line[number]:
            add_finding(item)
        generated_lines[number] = len(lines) + 1
        lines.extend(_comment(line) if inert else [line])
    return "\n".join(lines) + "\n", anchors, generated_lines


def commented_source(entry, text, *, redact=lambda text: text):
    """Preserve the original section in inert review text with its original line numbers."""
    lines = _comment("SOURCE EVIDENCE · Original text retained for conversion review")
    lines += _comment(source_location(entry))
    reason = entry["region"].get("gap")
    if reason:
        lines.extend(_comment(redact(reason)))
    first = entry["region"].get("start_line")
    for offset, line in enumerate(redact(text).splitlines()):
        label = f"{first + offset:>5}" if first else f"excerpt line {offset + 1}"
        lines.extend(_comment(f"{label} | {line}"))
    return "\n".join(lines) + "\n"
