"""Conservative SAS static analysis, with unresolved runtime constructs surfaced."""
from __future__ import annotations

import re

from dataforge.models import AssetRef, Diagnostic, Operation, ParseResult, Usage, file_asset, statements
from dataforge.parsers.sas_sql import parse_proc_sql

IDENT = r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?"


def strip_comments(text: str) -> str:
    # Preserve quoted text and line positions, replacing comment bodies with spaces.
    return re.sub(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")|/\*.*?\*/",
                  lambda m: m.group(1) if m.group(1) else re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)


def parse_sas(content: str, library_mappings: dict | None = None, macros: dict | None = None,
              sql_dialect: str = "") -> ParseResult:
    result = ParseResult()
    libraries = {k.casefold(): v for k, v in (library_mappings or {}).items()}
    variables = {k.casefold(): str(v) for k, v in (macros or {}).items()}
    tokens = list(statements(content, sas=True))
    line_offsets = [0, *(match.end() for match in re.finditer("\n", content))]
    cursor = 0
    macro_depth = 0
    control_depth = 0
    block = []
    block_type = ""
    block_bad = False

    def ref(name):
        if name.startswith("file:"):
            return AssetRef(name, kind="file")
        name = name.strip().rstrip(";")
        parts = name.split(".")
        if len(parts) == 1:
            name = "work." + name
        elif parts[0].casefold() in libraries:
            name = libraries[parts[0].casefold()] + "." + ".".join(parts[1:])
        return AssetRef(name, temporary=name.casefold().startswith("work."))

    def dataset_list(text):
        if re.search(r"(['\"]).*?\1n\b", text, re.I | re.S):
            result.diagnostics.append(Diagnostic("SAS name literal is unresolved; dataset references were not guessed", block[0][1] if block else 1))
            return []
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.split(r"\b\w+\s*=|/", text, maxsplit=1)[0]
        return [ref(n) for n in re.findall(IDENT, text) if n.casefold() != "_null_"]

    def option(text, key, is_file=False):
        pattern = rf"\b{key}\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|({IDENT}))"
        m = re.search(pattern, text, re.I)
        if not m:
            return []
        name = next(v for v in m.groups() if v is not None)
        return [ref(file_asset(name) if is_file else name)]

    def flush():
        nonlocal block, block_type, block_bad
        if not block:
            return
        raw_code = content[block[0][4]:block[-1][5]]
        clean = "\n".join(t[3] for t in block)
        start, end = block[0][1], block[-1][2]
        sources, targets, usages = [], [], []
        if block_bad:
            block, block_type, block_bad = [], "", False
            return
        if block_type == "data":
            header = re.sub(r"^\s*data\s+", "", block[0][3], flags=re.I).rstrip(";")
            targets = dataset_list(header)
            for raw, line, _, statement, _, _ in block[1:]:
                m = re.match(r"\s*(set|merge|update|modify)\s+(.+?);?$", statement, re.I | re.S)
                if m:
                    sources.extend(dataset_list(m.group(2)))
                m = re.match(r"\s*(infile|file)\s+(['\"])(.*?)\2", statement, re.I | re.S)
                if m:
                    (sources if m.group(1).lower() == "infile" else targets).append(ref(file_asset(m.group(3))))
            unique_sources = {s.name.casefold(): s for s in sources}
            # Only explicit variable lists with one source have reliable ownership.
            if len(unique_sources) == 1:
                source = next(iter(unique_sources.values()))
                for _, _, _, statement, _, _ in block[1:]:
                    m = re.match(r"\s*(keep|drop|by|rename)\s+(.+?);?$", statement, re.I | re.S)
                    if m:
                        items = m.group(2)
                        names = re.findall(r"\b(\w+)\s*=", items) if m.group(1).lower() == "rename" else re.findall(r"\b[A-Za-z_]\w*\b", items)
                        for name in names:
                            if name.casefold() not in {"descending", "_all_", "_numeric_", "_character_"}:
                                usages.append(Usage(source.name, name, m.group(1).upper(), expression=statement))
                    for keep in re.finditer(r"\b(keep|drop)\s*=\s*([^)]*)", statement, re.I):
                        for name in re.findall(r"\b[A-Za-z_]\w*\b", keep.group(2)):
                            usages.append(Usage(source.name, name, keep.group(1).upper(), expression=statement))
        elif block_type == "sql":
            for raw, line, last, statement, _, _ in block[1:]:
                if re.match(r"\s*(quit|run)\b", statement, re.I):
                    continue
                parsed = parse_proc_sql(statement, sql_dialect)
                for d in parsed.diagnostics:
                    d.line += line - 1
                result.diagnostics.extend(parsed.diagnostics)
                for op in parsed.operations:
                    op.sources = [ref(r.name) for r in op.sources]
                    op.targets = [ref(r.name) for r in op.targets]
                    for u in op.usages:
                        u.table = ref(u.table).name
                    op.code, op.start, op.end, op.method = raw, line, last, "sas-proc-sql"
                    result.operations.append(op)
            block, block_type = [], ""
            return
        else:
            sources = option(clean, "data")
            targets = option(clean, "out")
            if block_type == "import":
                sources = option(clean, "datafile", True)
            elif block_type == "export":
                targets = option(clean, "outfile", True)
            elif block_type == "append":
                targets = option(clean, "base")
            elif block_type == "sort" and not targets:
                targets = sources.copy()
            elif block_type not in {"sort", "summary", "means", "transpose", "freq", "rank", "standard", "copy", "datasets"}:
                result.diagnostics.append(Diagnostic(f"Unsupported PROC {block_type}; dependencies not guessed", start))
                sources, targets = [], []
            if len(sources) == 1:
                for m in re.finditer(r"\b(by|var|id)\s+([^;]+)", clean, re.I):
                    usages.extend(Usage(sources[0].name, n, m.group(1).upper(), expression=m.group())
                                  for n in re.findall(r"\b[A-Za-z_]\w*\b", m.group(2))
                                  if n.casefold() != "descending")
        if sources or targets:
            result.operations.append(Operation("DATA" if block_type == "data" else "PROC " + block_type.upper(),
                list({s.name: s for s in sources}.values()), list({t.name: t for t in targets}.values()),
                raw_code, start, end, "sas-rules", usages=usages))
        block, block_type, block_bad = [], "", False

    for raw, line, end in tokens:
        # Anchor at the original line as inline data may contain identical skipped tokens.
        offset = content.index(raw, max(cursor, line_offsets[line - 1]))
        cursor = offset + len(raw)
        clean = strip_comments(raw).strip()
        if not clean or clean.startswith(("*", "%*")):
            continue
        if re.match(r"(?:datalines|cards)4?\s*;", clean, re.I):
            result.diagnostics.append(Diagnostic("Inline SAS data retained as data, not parsed as code", line, "info"))
        if re.match(r"%macro\b", clean, re.I):
            flush()
            macro_depth += 1
            result.diagnostics.append(Diagnostic("Macro definition retained; runtime invocation is not statically expanded", line))
            continue
        if macro_depth:
            if re.match(r"%mend\b", clean, re.I):
                macro_depth -= 1
            continue
        if control_depth:
            if re.search(r"%do\b", clean, re.I):
                control_depth += 1
            if re.match(r"%end\b", clean, re.I):
                control_depth -= 1
            continue
        if re.match(r"%(if|else|do)\b", clean, re.I):
            if block:
                block_bad = True
            flush()
            if re.search(r"%do\b", clean, re.I):
                control_depth = 1
            result.diagnostics.append(Diagnostic("SAS macro control flow is unresolved; conditional block not analyzed", line))
            continue
        assignment = re.fullmatch(r"%let\s+(\w+)\s*=\s*([^;&%]*);?", clean, re.I)
        if assignment:
            variables[assignment.group(1).casefold()] = assignment.group(2).strip()
            continue
        unresolved = []

        def substitute(m):
            key = m.group(1).casefold()
            if key not in variables:
                unresolved.append(m.group(0))
                return m.group(0)
            return variables[key]

        clean = re.sub(r"&(\w+)\.?", substitute, clean)
        if unresolved:
            result.diagnostics.append(Diagnostic("Unresolved SAS macro: " + ", ".join(unresolved), line,
                                                  symbol=",".join(unresolved)))
            block_bad = True
        if re.match(r"%", clean):
            result.diagnostics.append(Diagnostic("Dynamic SAS macro invocation/control flow is unresolved", line))
            block_bad = True
            continue
        header = re.match(r"(data|proc)\s+(\w+)", clean, re.I)
        if header:
            previous_bad = block_bad
            flush()
            block_type = "data" if header.group(1).lower() == "data" else header.group(2).lower()
            block_bad = bool(unresolved) or (previous_bad and clean.startswith("%"))
            block = [(raw, line, end, clean, offset, cursor)]
        elif block:
            block.append((raw, line, end, clean, offset, cursor))
            if re.match(r"(run|quit)\b", clean, re.I):
                flush()
        elif re.match(r"libname\b", clean, re.I):
            result.diagnostics.append(Diagnostic("LIBNAME retained as namespace; physical library paths are not read", line, "info"))
        elif re.match(r"(set|merge|data|proc)\b", clean, re.I):
            result.diagnostics.append(Diagnostic("SAS statement outside a supported block", line))
    flush()
    return result
