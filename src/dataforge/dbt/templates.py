"""Inspect Jinja expressions and dbt blocks without rendering imported templates."""
from dataclasses import dataclass, field

from jinja2 import Environment, TemplateSyntaxError, nodes


@dataclass(frozen=True)
class ReferenceCall:
    name: str
    args: tuple
    kwargs: dict
    start: int
    end: int
    conditional: bool = False
    owner: str = ''


@dataclass
class Definition:
    name: str
    kind: str
    start: int
    end: int


@dataclass
class TemplateFacts:
    calls: list[ReferenceCall] = field(default_factory=list)
    definitions: list[Definition] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    tags: list[tuple[int, int, str]] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def constant(node, variables=None):
    if isinstance(node, nodes.Const):
        return node.value
    if isinstance(node, (nodes.List, nodes.Tuple)):
        return [constant(n, variables) for n in node.items]
    if isinstance(node, nodes.Dict):
        return {constant(p.key, variables): constant(p.value, variables) for p in node.items}
    if isinstance(node, nodes.Call) and function_name(node.node) == 'var' and node.args:
        key = constant(node.args[0])
        if variables is not None and key in variables:
            return variables[key]
        if len(node.args) > 1:
            return constant(node.args[1], variables)
    raise ValueError('Dynamic Jinja expression')


def function_name(node):
    if isinstance(node, nodes.Name):
        return node.name
    if isinstance(node, nodes.Getattr):
        return function_name(node.node) + '.' + node.attr
    return '<dynamic>'


def scan_template(text, source=None, limits=None, variables=None):
    facts, stack, i, quote, comment = TemplateFacts(), [], 0, None, None
    environment = Environment()
    while i < len(text):
        if comment == 'line':
            if text[i] == '\n':
                comment = None
            i += 1
            continue
        if comment == 'block':
            if text.startswith('*/', i):
                comment, i = None, i + 2
            else:
                i += 1
            continue
        if quote:
            if text[i] == quote:
                if i + 1 < len(text) and text[i + 1] == quote:
                    i += 2
                    continue
                quote = None
            i += 1
            continue
        if text.startswith('--', i) and not text[i:].startswith('-- depends_on:'):
            comment, i = 'line', i + 2
            continue
        if text.startswith('/*', i):
            comment, i = 'block', i + 2
            continue
        opening = text[i:i + 2]
        if opening not in {'{{', '{%', '{#'}:
            if text[i] in "'\"`":
                quote = text[i]
            i += 1
            continue
        start, closing = i, {'{{': '}}', '{%': '%}', '{#': '#}'}[opening]
        j, inner_quote = i + 2, None
        while j < len(text):
            if inner_quote:
                if text[j] == '\\':
                    j += 2
                    continue
                if text[j] == inner_quote:
                    inner_quote = None
            elif text.startswith(closing, j):
                break
            elif text[j] in "'\"":
                inner_quote = text[j]
            j += 1
        if j >= len(text):
            facts.diagnostics.append('Unclosed template block')
            break
        end, body = j + 2, text[i + 2:j].strip().strip('-').strip()
        facts.tags.append((start, end, body))
        i = end
        if opening == '{#':
            continue
        parts = body.split()
        command = parts[0] if parts else ''
        if opening == '{%' and command == 'raw':
            stop = text.find('{% endraw %}', i)
            if stop < 0:
                facts.diagnostics.append('Unclosed raw block')
                break
            i = stop + len('{% endraw %}')
            continue
        if opening == '{%' and command in {'macro', 'snapshot', 'test', 'materialization', 'docs'}:
            name = parts[1].split('(')[0].strip(',') if len(parts) > 1 else '<unknown>'
            definition = Definition(name, command, start, end)
            facts.definitions.append(definition)
            stack.append((command, definition))
            if len(stack) > 64:
                raise ValueError('Template nesting budget exceeded')
            continue
        if opening == '{%' and command in {'if', 'for', 'call', 'set'}:
            facts.diagnostics.append('Dynamic or conditional template structure; source-only SQL coverage is partial')
            if command != 'set' or '=' not in body:
                stack.append((command, None))
            continue
        if opening == '{%' and command.startswith('end'):
            if stack:
                kind, definition = stack.pop()
                if command != 'end' + kind:
                    facts.diagnostics.append('Mismatched template blocks')
                if definition:
                    definition.end = end
            continue
        if opening != '{{':
            continue
        try:
            tree = environment.parse('{{ ' + body + ' }}')
            root_expression = tree.body[0].nodes[0]
            calls = list(tree.find_all(nodes.Call))
            if len(calls) > 100000:
                raise ValueError('Template call budget exceeded')
            for node in calls:
                try:
                    args = tuple(constant(n, variables) for n in node.args)
                    kwargs = {p.key: constant(p.value, variables) for p in node.kwargs}
                except ValueError:
                    args, kwargs = (), {}
                owner = next((d.name for _, d in reversed(stack) if d is not None), '')
                conditional = any(k in {'if', 'for', 'call'} for k, _ in stack) or node is not root_expression
                if conditional and function_name(node.node) in {'ref', 'source'}:
                    facts.diagnostics.append('Nested or conditional reference is a candidate; generated relation is unresolved')
                call = ReferenceCall(function_name(node.node), args, kwargs, start, end, conditional, owner)
                facts.calls.append(call)
                if call.name == 'config' and not owner and not conditional:
                    facts.config.update(kwargs)
        except (TemplateSyntaxError, RecursionError):
            facts.diagnostics.append('Unsupported template expression')
    if stack:
        facts.diagnostics.append('Unclosed template definition')
    return facts
