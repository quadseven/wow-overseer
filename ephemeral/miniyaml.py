"""A strict YAML subset reader for decrees (standard library only).

The unit suite has no YAML parser, and a decree is data that must read the
same everywhere, so this reads exactly the subset decrees use and refuses
everything else with the line number:

- block mappings and block sequences, two-space or deeper indentation
- flow mappings and flow sequences on ONE line
- plain, single-quoted and double-quoted scalars; integers, true, false, null
- `|` block scalars
- `#` comments

Refused: tabs, anchors and aliases, tags, folded scalars, multiple documents,
duplicate keys, multi-line flow collections.
"""

import re

__all__ = ["YamlError", "loads"]


class YamlError(ValueError):
    """The text is not in the supported subset."""


_KEY = re.compile(
    r"""^("(?:[^"\\]|\\.)*"|'(?:[^']|'')*'|[A-Za-z0-9_][A-Za-z0-9_.\-]*)\s*:(?:\s+(.*))?$"""
)
_INT = re.compile(r"^-?\d+$")
_FLOAT = re.compile(r"^-?\d+\.\d+$")


def _opens_quote(text, i):
    """A quote starts a quoted scalar only where a value or key can start.

    That is at the start of the text or right after `:`, `-`, `[`, `{` or `,`.
    A quote inside plain text (He said "hi # there") is just a character.
    """
    before = text[:i].rstrip(" 	")
    return before == "" or before[-1] in ":-[{,"


def _strip_comment(text):
    """Drop a trailing ` #...` that is outside quotes."""
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if quote:
            if quote == '"' and ch == "\\":
                i += 2
                continue
            if ch == quote:
                quote = None
        elif ch in "\"'" and _opens_quote(text, i):
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " 	"):
            return text[:i].rstrip()
        i += 1
    return text.rstrip()


_ESC = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0"}


def _unquote_double(s, line):
    out = []
    i = 0
    while i < len(s):
        if s[i] == "\\":
            i += 1
            if i >= len(s) or s[i] not in _ESC:
                raise YamlError(
                    f"line {line}: unsupported escape in double-quoted string"
                )
            out.append(_ESC[s[i]])
        else:
            out.append(s[i])
        i += 1
    return "".join(out)


def _closes_double(text):
    """True when text is a complete double-quoted scalar."""
    i = 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i == len(text) - 1
        i += 1
    return False


def _scalar(text, line):
    text = text.strip()
    if text == "":
        return None
    if text[0] == '"':
        if not _closes_double(text):
            raise YamlError(f"line {line}: unterminated double quote")
        return _unquote_double(text[1:-1], line)
    if text[0] == "'":
        if len(text) < 2 or text[-1] != "'":
            raise YamlError(f"line {line}: unterminated single quote")
        return text[1:-1].replace("''", "'")
    if text[0] in "&*":
        raise YamlError(f"line {line}: anchors and aliases are not supported")
    if text[0] == "!":
        raise YamlError(f"line {line}: tags are not supported")
    if text[0] == ">":
        raise YamlError(f"line {line}: folded scalars are not supported")
    if text in ("true", "false"):
        return text == "true"
    if text in ("null", "~"):
        return None
    if _INT.match(text):
        return int(text)
    if _FLOAT.match(text):
        return float(text)
    return text


class _Flow:
    """One-line flow collections: {a: b, c: [1, 2]}."""

    def __init__(self, text, line):
        self.s = text
        self.i = 0
        self.line = line

    def err(self, why):
        return YamlError(f"line {self.line}: bad flow collection ({why})")

    def ws(self):
        while self.i < len(self.s) and self.s[self.i] == " ":
            self.i += 1

    def value(self):
        self.ws()
        if self.i >= len(self.s):
            raise self.err("unexpected end")
        ch = self.s[self.i]
        if ch == "{":
            return self.mapping()
        if ch == "[":
            return self.sequence()
        return self.plain()

    def plain(self):
        start = self.i
        if self.i >= len(self.s):
            raise self.err("unexpected end")
        ch = self.s[self.i]
        if ch in "\"'":
            self.i += 1
            while self.i < len(self.s):
                if ch == '"' and self.s[self.i] == "\\":
                    self.i += 2
                    continue
                if self.s[self.i] == ch:
                    if ch == "'" and self.s[self.i + 1 : self.i + 2] == "'":
                        self.i += 2
                        continue
                    break
                self.i += 1
            else:
                raise self.err("unterminated quote")
            self.i += 1
            return _scalar(self.s[start : self.i], self.line)
        while self.i < len(self.s) and self.s[self.i] not in ",}]":
            if self.s[self.i] == ":" and self.s[self.i + 1 : self.i + 2] in (" ", ""):
                break
            self.i += 1
        return _scalar(self.s[start : self.i], self.line)

    def key(self):
        self.ws()
        v = self.plain()
        return v if isinstance(v, str) else str(v)

    def mapping(self):
        self.i += 1
        out = {}
        self.ws()
        if self.s[self.i : self.i + 1] == "}":
            self.i += 1
            return out
        while True:
            k = self.key()
            self.ws()
            if self.s[self.i : self.i + 1] != ":":
                raise self.err("expected ':'")
            self.i += 1
            v = self.value()
            if k in out:
                raise YamlError(f"line {self.line}: duplicate key {k!r}")
            out[k] = v
            self.ws()
            ch = self.s[self.i : self.i + 1]
            self.i += 1
            if ch == "}":
                return out
            if ch != ",":
                raise self.err("expected ',' or '}'")

    def sequence(self):
        self.i += 1
        out = []
        self.ws()
        if self.s[self.i : self.i + 1] == "]":
            self.i += 1
            return out
        while True:
            out.append(self.value())
            self.ws()
            ch = self.s[self.i : self.i + 1]
            self.i += 1
            if ch == "]":
                return out
            if ch != ",":
                raise self.err("expected ',' or ']'")


def _inline(text, line):
    text = text.strip()
    if text[:1] in ("{", "["):
        flow = _Flow(text, line)
        value = flow.value()
        flow.ws()
        if flow.i != len(text):
            raise flow.err("trailing text")
        return value
    return _scalar(text, line)


class _Parser:
    def __init__(self, text):
        self.raw = text.replace("\r\n", "\n").split("\n")
        self.lines = []  # [lineno, indent, text without comment] or None
        for n, raw in enumerate(self.raw, 1):
            body = raw.lstrip(" ")
            if body.startswith("\t"):
                raise YamlError(f"line {n}: tab in indentation")
            if not body.strip() or body.startswith("#"):
                self.lines.append(None)
                continue
            self.lines.append([n, len(raw) - len(body), _strip_comment(body)])
        self.pos = 0

    def peek(self):
        while self.pos < len(self.lines) and self.lines[self.pos] is None:
            self.pos += 1
        return self.lines[self.pos] if self.pos < len(self.lines) else None

    def block(self, min_indent):
        cur = self.peek()
        if cur is None or cur[1] < min_indent:
            return None
        if cur[2] == "-" or cur[2].startswith("- "):
            return self.sequence(cur[1])
        return self.mapping(cur[1])

    def mapping(self, indent):
        out = {}
        while True:
            cur = self.peek()
            if cur is None or cur[1] < indent:
                return out
            n, ind, text = cur
            if ind > indent:
                raise YamlError(f"line {n}: unexpected indent")
            if text == "-" or text.startswith("- "):
                raise YamlError(f"line {n}: sequence item inside a mapping")
            m = _KEY.match(text)
            if not m:
                raise YamlError(f"line {n}: expected 'key: value'")
            key = m.group(1)
            if key[0] in "\"'":
                key = str(_scalar(key, n))
            rest = (m.group(2) or "").strip()
            if key in out:
                raise YamlError(f"line {n}: duplicate key {key!r}")
            self.pos += 1
            if rest == "":
                nxt = self.peek()
                out[key] = self.block(indent + 1) if nxt and nxt[1] > indent else None
            elif rest[0] == "|":
                out[key] = self.block_scalar(rest, indent, n)
            else:
                out[key] = _inline(rest, n)

    def sequence(self, indent):
        out = []
        while True:
            cur = self.peek()
            if cur is None or cur[1] < indent:
                return out
            n, ind, text = cur
            if ind > indent:
                raise YamlError(f"line {n}: unexpected indent")
            if not (text == "-" or text.startswith("- ")):
                raise YamlError(f"line {n}: expected '- ' item")
            rest = text[1:]
            lead = len(rest) - len(rest.lstrip(" "))
            rest = rest.strip()
            if rest == "":
                self.pos += 1
                nxt = self.peek()
                out.append(self.block(indent + 1) if nxt and nxt[1] > indent else None)
            elif rest[0] not in "{[" and _KEY.match(rest):
                cur[1] = indent + 1 + lead
                cur[2] = rest
                out.append(self.mapping(indent + 1 + lead))
            else:
                self.pos += 1
                out.append(_inline(rest, n))

    def block_scalar(self, head, indent, n):
        if head not in ("|", "|-"):
            raise YamlError(f"line {n}: unsupported block scalar header {head!r}")
        body = []
        base = None
        while self.pos < len(self.raw):
            raw = self.raw[self.pos]
            if not raw.strip():
                body.append("")
                self.pos += 1
                continue
            ind = len(raw) - len(raw.lstrip(" "))
            if ind <= indent:
                break
            if base is None:
                base = ind
            if ind < base:
                raise YamlError(f"line {self.pos + 1}: bad indent in block scalar")
            body.append(raw[base:])
            self.pos += 1
        while body and body[-1] == "":
            body.pop()
        text = "\n".join(body)
        return text if head == "|-" else text + "\n"


def loads(text):
    """Parse a decree document into plain dicts, lists and scalars."""
    if text.startswith("---") or "\n---" in text:
        raise YamlError("multiple documents and '---' markers are not supported")
    p = _Parser(text)
    cur = p.peek()
    if cur is None:
        return {}
    if cur[1] != 0:
        raise YamlError(f"line {cur[0]}: bad indent at document start")
    value = p.block(0)
    extra = p.peek()
    if extra is not None:
        raise YamlError(f"line {extra[0]}: unexpected content")
    return value
