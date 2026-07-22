"""Minimal KiCad s-expression parser/writer."""


class Sym(str):
    """Bare (unquoted) symbol token."""


def tokenize(text):
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield c
            i += 1
        elif c == '"':
            j = i + 1
            out = []
            while j < n:
                if text[j] == "\\" and j + 1 < n:
                    out.append(text[j:j + 2])
                    j += 2
                elif text[j] == '"':
                    break
                else:
                    out.append(text[j])
                    j += 1
            yield ("STR", "".join(out))
            i = j + 1
        else:
            j = i
            while j < n and not text[j].isspace() and text[j] not in "()":
                j += 1
            yield ("SYM", text[i:j])
            i = j


def parse(text):
    stack = [[]]
    for tok in tokenize(text):
        if tok == "(":
            stack.append([])
        elif tok == ")":
            done = stack.pop()
            stack[-1].append(done)
        else:
            kind, val = tok
            stack[-1].append(val if kind == "STR" else Sym(val))
    return stack[0]


def _esc(s):
    return s.replace("\\", "\\\\").replace('"', '\\"')


def dump(node, indent=0):
    """Serialize a parsed node back to s-expression text."""
    if isinstance(node, Sym):
        return str(node)
    if isinstance(node, str):
        return '"%s"' % _esc(node)
    if isinstance(node, (int,)):
        return str(node)
    if isinstance(node, float):
        return fmt_num(node)
    # list
    pad = "\t" * indent
    # decide single-line vs multi-line: single-line if no sub-lists
    if not any(isinstance(x, list) for x in node):
        return "(" + " ".join(dump(x) for x in node) + ")"
    parts = []
    head = []
    idx = 0
    while idx < len(node) and not isinstance(node[idx], list):
        head.append(dump(node[idx]))
        idx += 1
    out = "(" + " ".join(head)
    for x in node[idx:]:
        out += "\n" + pad + "\t" + dump(x, indent + 1)
    out += "\n" + pad + ")"
    return out


def fmt_num(v):
    if isinstance(v, float):
        s = ("%.6f" % v).rstrip("0").rstrip(".")
        return s if s not in ("-0", "") else "0"
    return str(v)


def find(node, key):
    """First child list whose head symbol == key."""
    for x in node:
        if isinstance(x, list) and x and isinstance(x[0], Sym) and str(x[0]) == key:
            return x
    return None


def find_all(node, key):
    return [x for x in node
            if isinstance(x, list) and x and isinstance(x[0], Sym) and str(x[0]) == key]


def atom(node, idx, default=None):
    try:
        v = node[idx]
        return v
    except (IndexError, TypeError):
        return default


def num(x, default=0.0):
    try:
        return float(str(x))
    except (TypeError, ValueError):
        return default
