"""Conservative SAS static analysis, with unresolved runtime constructs surfaced."""
from __future__ import annotations

import re

from dataforge.models import AssetRef, Diagnostic, Operation, ParseResult, Usage, file_asset, statements
from dataforge.parsers.sas_sql import parse_proc_sql
from dataforge.parsers.sas_transformations import data_step_derivations, proc_derivations

IDENT = r"[A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)?"


def strip_comments(text: str) -> str:
    """Replace SAS comments with spaces while preserving quoted text and line breaks.

    Args:
        text: SAS source text.

    Returns:
        Source with comment characters blanked out.
    """
    # Preserve quoted text and line positions, replacing comment bodies with spaces.
    return re.sub(r"('(?:''|[^'])*'|\"(?:\"\"|[^\"])*\")|/\*.*?\*/",
                  lambda m: m.group(1) if m.group(1) else re.sub(r"[^\n]", " ", m.group()), text, flags=re.S)


def resolve_macros(text: str, variables: dict[str, str]) -> tuple[str, list[str]]:
    """Substitute safe known macro values in one pass and collect unresolved tokens.

    Args:
        text: SAS text to scan.
        variables: Known macro variable values keyed case-insensitively.

    Returns:
        Resolved text and references that could not be safely substituted.
    """
    unresolved = []
    size = len(text)
    references = r"&+[A-Za-z_]\w*\.?|%[A-Za-z_]\w*"

    def replace(match: re.Match[str]) -> str:
        """Replace one safe macro reference while updating the size bound.

        Args:
            match: Regular-expression match for the current token.

        Returns:
            Safe replacement text or the original unresolved token.
        """
        nonlocal size
        token = match.group()
        if token.startswith("'"):
            return token
        if token.startswith('"'):
            return '"' + re.sub(references, replace, token[1:-1]) + '"'
        key = token[1:].rstrip(".").casefold()
        value = variables.get(key) if token.startswith("&") and not token.startswith("&&") else None
        if value is None or ";" in value or re.search(references, value):
            unresolved.append(token)
            if value is not None and re.search(r"%[A-Za-z_]", value):
                unresolved.append("%runtime")
            return token
        size += len(value) - len(token)
        if size > 1024 * 1024:
            unresolved.append(token)
            return token
        return value

    resolved = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"|" + references, replace, text)
    return resolved, unresolved


def parse_sas(content: str, library_mappings: dict[str, str] | None = None,
              macros: dict[str, str] | None = None,
              sql_dialect: str = "") -> ParseResult:
    """Extract conservative SAS data and PROC dependencies without running SAS code.

    Args:
        content: SAS source text.
        library_mappings: Optional SAS library names mapped to canonical namespaces.
        macros: Optional static macro variable values.
        sql_dialect: SQLGlot dialect used for PROC SQL blocks.

    Returns:
        Operations and diagnostics found by the static parser.
    """
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

    def ref(name: str) -> AssetRef:
        """Normalize a SAS dataset or file reference into an asset record.

        Args:
            name: Dataset or file reference from the source.

        Returns:
            Asset reference with library mappings and WORK identity applied.
        """
        if name.startswith("file:"):
            return AssetRef(name, kind="file")
        name = name.strip().rstrip(";")
        parts = name.split(".")
        if len(parts) == 1:
            name = "work." + name
        elif parts[0].casefold() in libraries:
            name = libraries[parts[0].casefold()] + "." + ".".join(parts[1:])
        return AssetRef(name, temporary=name.casefold().startswith("work."))

    def dataset_list(text: str) -> list[AssetRef]:
        """Parse a conservative list of SAS dataset names from a block header.

        Args:
            text: Dataset-list portion of the block header.

        Returns:
            Parsed dataset asset references.
        """
        if re.search(r"(['\"]).*?\1n\b", text, re.I | re.S):
            result.diagnostics.append(Diagnostic("SAS name literal is unresolved; dataset references were not guessed", block[0][1] if block else 1))
            return []
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.split(r"\b\w+\s*=|/", text, maxsplit=1)[0]
        return [ref(n) for n in re.findall(IDENT, text) if n.casefold() != "_null_"]

    def option(text: str, key: str, is_file: bool = False) -> list[AssetRef]:
        """Read one supported PROC dataset option from its block text.

        Args:
            text: PROC block text to search.
            key: Option name to locate.
            is_file: Whether the value identifies a file rather than a dataset.

        Returns:
            Zero or one asset reference for the option value.
        """
        pattern = rf"\b{key}\s*=\s*(?:'([^']*)'|\"([^\"]*)\"|({IDENT}))"
        m = re.search(pattern, text, re.I)
        if not m:
            return []
        name = next(v for v in m.groups() if v is not None)
        return [ref(file_asset(name) if is_file else name)]

    def flush() -> None:
        """Convert the buffered DATA or PROC block into operations and diagnostics."""
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
                sql_source = raw if statement == strip_comments(raw).strip() else statement
                parsed = parse_proc_sql(sql_source, sql_dialect)
                for d in parsed.diagnostics:
                    d.line += line - 1
                result.diagnostics.extend(parsed.diagnostics)
                for op in parsed.operations:
                    op.sources = [ref(r.name) for r in op.sources]
                    op.targets = [ref(r.name) for r in op.targets]
                    for u in op.usages:
                        u.table = ref(u.table).name
                    for derivation in op.derivations:
                        if not derivation.get("scope"):
                            derivation["target_table"] = ref(derivation["target_table"]).name
                        for dependency in derivation["inputs"]:
                            if not dependency.get("scope"):
                                dependency["table"] = ref(dependency["table"]).name
                        if re.search(r"[&%]", strip_comments(raw)):
                            derivation["expression"] = raw
                            derivation["status"] = "unresolved"
                            derivation["coverage"].append("SAS macro expansion cannot replace original expression evidence")
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
            operation = Operation("DATA" if block_type == "data" else "PROC " + block_type.upper(),
                list({s.name: s for s in sources}.values()), list({t.name: t for t in targets}.values()),
                raw_code, start, end, "sas-rules", usages=usages)
            if block_type == "data":
                operation.derivations, diagnostics = data_step_derivations(operation, block)
                result.diagnostics.extend(diagnostics)
            else:
                operation.derivations = proc_derivations(operation)
            result.operations.append(operation)
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
            variables.clear()
            if block:
                block_bad = True
            flush()
            if re.search(r"%do\b", clean, re.I):
                control_depth = 1
            result.diagnostics.append(Diagnostic("SAS macro control flow is unresolved; conditional block not analyzed", line))
            continue
        assignment = re.fullmatch(r"%let\s+([A-Za-z_]\w*)\s*=\s*(.*?);?", clean, re.I | re.S)
        if assignment:
            name = assignment.group(1).casefold()
            value, unresolved = resolve_macros(assignment.group(2).strip(), variables)
            if unresolved:
                variables.pop(name, None)
                if any(token.startswith("%") for token in unresolved):
                    variables.clear()
                result.diagnostics.append(Diagnostic("Unresolved SAS %LET assignment; previous value invalidated", line, symbol=name))
            else:
                variables[name] = value
            continue
        clean, unresolved = resolve_macros(clean, variables)
        if unresolved:
            if any(token.startswith("%") for token in unresolved):
                variables.clear()
            result.diagnostics.append(Diagnostic("Unresolved SAS macro: " + ", ".join(unresolved), line,
                                                  symbol=",".join(unresolved)))
            block_bad = True
        if re.match(r"%", clean):
            variables.clear()
            result.diagnostics.append(Diagnostic("Dynamic SAS macro invocation/control flow is unresolved", line))
            block_bad = True
            continue
        unquoted = re.sub(r"'(?:''|[^'])*'|\"(?:\"\"|[^\"])*\"", " ", clean)
        if re.search(r"\bcall\s+(symputx?|execute)\s*\(", unquoted, re.I):
            variables.clear()
            result.diagnostics.append(Diagnostic("Runtime SAS macro mutation is unresolved; known variable values invalidated", line))
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
