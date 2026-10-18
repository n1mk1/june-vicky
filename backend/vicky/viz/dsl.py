"""A small, safe expression language for dashboard series.

Expressions are tokenized and parsed by hand into an AST (Pratt parser). Nothing is ever
passed to `eval`, `exec` or `compile`; the evaluator in `evaluate.py` walks the AST.

Grammar (precedence low → high):

    expr    := term (("+" | "-" | "−") term)*
    term    := unary (("*" | "×" | "/" | "÷") unary)*
    unary   := ("-" | "−" | "+") unary | atom
    atom    := NUMBER | NAME | NAME "(" args? ")" | "raw" "(" STRING ")" | "(" expr ")"
    args    := expr ("," expr)*
    NAME    := canonical field id (revenue.recurring, opex.s_and_m, net_income, ...)
             | derived helper (burn, burn_ex_non_dilutive, revenue, mrr, arr, gross_margin, gross_margin_incl_cs)
             | metric id giving one number (cmgr_12m, runway_months, ...) or fact.<name>

Functions: sum avg min max (one series → one number over the window; several → per period),
abs, rolling(x, n), cmgr(x, months), pct_of(a, b), yoy(x), mom(x), cumsum(x), lag(x, n).
"""

import keyword
import math
import re
from dataclasses import dataclass

from vicky.model.canonical import FIELDS, OPEX_CATEGORIES
from vicky.model.metrics import RECURRING_IDS

MAX_LENGTH = 500
MAX_NODES = 200


class DSLError(ValueError):
    """A user-facing message about why an expression was rejected."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------- vocabulary

# Derived per-period series, computed from canonical fields. Value: fields they need.
HELPERS: dict[str, list[str]] = {
    "burn": ["net_income"],
    "burn_ex_non_dilutive": ["net_income", "non_dilutive_income"],
    "revenue": ["revenue.total"],
    "mrr": ["revenue.recurring"],
    "arr": ["revenue.recurring"],
    "gross_margin": ["revenue.total", "cogs"],
    "gross_margin_incl_cs": ["revenue.total", "cogs", "opex.customer_success"],
}

HELPER_LABELS: dict[str, str] = {
    "burn": "burn",
    "burn_ex_non_dilutive": "burn ex non-dilutive",
    "revenue": "revenue",
    "mrr": "MRR",
    "arr": "ARR",
    "gross_margin": "gross margin",
    "gross_margin_incl_cs": "gross margin incl. CS",
}

GENERIC_METRIC_IDS = [
    "revenue",
    "revenue_growth",
    "revenue_growth_yoy",
    "gross_margin",
    "gross_margin_incl_cs",
    "gross_margin_incl_cs_l12m",
    "burn",
    "burn_incl_credits",
    "cash_balance",
    "runway_months",
    "top_customer_share",
] + [f"opex_share_{c.split('.')[-1]}" for c in OPEX_CATEGORIES]
METRIC_IDS: frozenset[str] = frozenset(GENERIC_METRIC_IDS) | frozenset(RECURRING_IDS)

# name → (min args, max args or None, indexes of args that must be positive integer literals)
FUNCTIONS: dict[str, tuple[int, int | None, tuple[int, ...]]] = {
    "sum": (1, None, ()),
    "avg": (1, None, ()),
    "min": (1, None, ()),
    "max": (1, None, ()),
    "abs": (1, 1, ()),
    "rolling": (2, 2, (1,)),
    "cmgr": (2, 2, (1,)),
    "pct_of": (2, 2, ()),
    "yoy": (1, 1, ()),
    "mom": (1, 1, ()),
    "cumsum": (1, 1, ()),
    "lag": (2, 2, (1,)),
}

_FACT_RE = re.compile(r"^fact\.[a-z0-9_]+$")


def name_kind(name: str) -> str | None:
    """'field' | 'helper' | 'metric' | None for an identifier."""
    if name in HELPERS:
        return "helper"
    if name in FIELDS:
        return "field"
    if name in METRIC_IDS or _FACT_RE.match(name):
        return "metric"
    return None


# ---------------------------------------------------------------- AST


@dataclass(frozen=True)
class Num:
    value: float


@dataclass(frozen=True)
class Name:
    id: str


@dataclass(frozen=True)
class Raw:
    key: str


@dataclass(frozen=True)
class Neg:
    operand: "Node"


@dataclass(frozen=True)
class Bin:
    op: str  # one of + - * /
    left: "Node"
    right: "Node"


@dataclass(frozen=True)
class Call:
    fn: str
    args: tuple["Node", ...]


Node = Num | Name | Raw | Neg | Bin | Call


# ---------------------------------------------------------------- tokenizer


@dataclass(frozen=True)
class Token:
    kind: str  # num | name | str | op | end
    text: str
    pos: int


_OPS = {"+": "+", "-": "-", "−": "-", "*": "*", "×": "*", "/": "/", "÷": "/", "(": "(", ")": ")", ",": ","}
_NAME_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)*")
_NUM_RE = re.compile(r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_FORBIDDEN = {
    "[": "subscripts are not allowed",
    "]": "subscripts are not allowed",
    ".": "attribute access is not allowed",
    "=": "assignment and comparison are not allowed",
    ";": "only one expression is allowed",
    ":": "':' is only allowed inside raw(\"dataset:column\")",
    "{": "braces are not allowed",
    "}": "braces are not allowed",
    "@": "decorators and matrix operators are not allowed",
    "`": "backticks are not allowed",
    "\\": "escapes are not allowed",
}


MAX_LITERAL = 1e15  # no real figure is larger; blocks 1e999 / overflow tricks
MAX_WINDOW = 240  # periods for rolling/lag windows


def _check_name(name: str) -> None:
    if "__" in name:
        raise DSLError(f"'{name}' is not allowed: double-underscore names are reserved")
    for part in name.split("."):
        if keyword.iskeyword(part) or keyword.issoftkeyword(part):
            raise DSLError(
                f"'{part}' is a Python keyword; only arithmetic and the listed functions are allowed"
            )


def tokenize(src: str) -> list[Token]:
    if len(src) > MAX_LENGTH:
        raise DSLError(f"expression is too long ({len(src)} characters; the limit is {MAX_LENGTH})")
    out: list[Token] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c.isspace():
            i += 1
            continue
        if c == "*" and src.startswith("**", i):
            raise DSLError(f"'**' at position {i} is not supported; use cmgr() for compound growth")
        if c in _OPS:
            out.append(Token("op", _OPS[c], i))
            i += 1
            continue
        if c in "\"'":
            end = src.find(c, i + 1)
            if end < 0:
                raise DSLError(f"unterminated string starting at position {i}")
            out.append(Token("str", src[i + 1 : end], i))
            i = end + 1
            continue
        m = _NUM_RE.match(src, i)
        if m and (c.isdigit() or c == "."):
            out.append(Token("num", m.group(0), i))
            i = m.end()
            if i < n and (src[i].isalpha() or src[i] == "_"):
                raise DSLError(f"unexpected '{src[i]}' after the number at position {m.start()}")
            continue
        m = _NAME_RE.match(src, i)
        if m:
            _check_name(m.group(0))
            out.append(Token("name", m.group(0), i))
            i = m.end()
            if i < n and src[i] == ".":
                raise DSLError(f"attribute access is not allowed (position {i})")
            continue
        why = _FORBIDDEN.get(c) or f"unexpected character {c!r}"
        raise DSLError(f"{why} (position {i})")
    out.append(Token("end", "", n))
    return out


# ---------------------------------------------------------------- parser

_BINARY_BP = {"+": 10, "-": 10, "*": 20, "/": 20}
_PREFIX_BP = 30


class _Parser:
    def __init__(self, src: str):
        self.src = src
        self.toks = tokenize(src)
        self.i = 0
        self.nodes = 0

    def peek(self) -> Token:
        return self.toks[self.i]

    def next(self) -> Token:
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, text: str) -> Token:
        t = self.next()
        if t.kind != "op" or t.text != text:
            got = "the end of the expression" if t.kind == "end" else repr(t.text)
            raise DSLError(f"expected '{text}' at position {t.pos}, found {got}")
        return t

    def count(self) -> None:
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise DSLError(f"expression is too complex (more than {MAX_NODES} parts)")

    def parse(self) -> Node:
        node = self.expr(0)
        t = self.peek()
        if t.kind != "end":
            raise DSLError(f"unexpected {t.text!r} at position {t.pos}")
        return node

    def expr(self, rbp: int) -> Node:
        left = self.nud(self.next())
        while True:
            t = self.peek()
            bp = _BINARY_BP.get(t.text, 0) if t.kind == "op" else 0
            if t.kind in ("num", "name", "str"):
                raise DSLError(f"missing operator before {t.text!r} at position {t.pos}")
            if bp <= rbp:
                return left
            self.next()
            self.count()
            left = Bin(t.text, left, self.expr(bp))

    def nud(self, t: Token) -> Node:
        self.count()
        if t.kind == "num":
            v = float(t.text)
            if not math.isfinite(v) or abs(v) > MAX_LITERAL:
                raise DSLError(f"number at position {t.pos} is too large (limit {MAX_LITERAL:g})")
            return Num(v)
        if t.kind == "str":
            raise DSLError(f'strings are only allowed inside raw("dataset:column") (position {t.pos})')
        if t.kind == "end":
            raise DSLError(
                "the expression ended too early" if self.toks[0].kind != "end" else "the expression is empty"
            )
        if t.kind == "op":
            if t.text == "(":
                node = self.expr(0)
                self.expect(")")
                return node
            if t.text == "-":
                operand = self.expr(_PREFIX_BP)
                return Num(-operand.value) if isinstance(operand, Num) else Neg(operand)
            if t.text == "+":
                return self.expr(_PREFIX_BP)
            raise DSLError(f"unexpected {t.text!r} at position {t.pos}")
        return self.name(t)

    def name(self, t: Token) -> Node:
        name = t.text
        is_call = self.peek().kind == "op" and self.peek().text == "("
        if is_call:
            if name == "raw":
                return self.raw()
            if name not in FUNCTIONS:
                raise DSLError(f"unknown function '{name}'. Allowed: raw, {', '.join(sorted(FUNCTIONS))}")
            return self.call(name)
        if name in FUNCTIONS or name == "raw":
            raise DSLError(f"'{name}' is a function; call it like {name}(...)")
        if name_kind(name) is None:
            if "." in name and not any(name.startswith(f + ".") for f in FIELDS):
                raise DSLError(f"'{name}' is not a canonical field, and attribute access is not allowed")
            if "." in name:
                raise DSLError(f"attribute access is not allowed ('{name}')")
            raise DSLError(
                f"unknown name '{name}'. Use a canonical field (e.g. revenue.recurring), a helper "
                f'({", ".join(HELPERS)}), a metric id, or raw("dataset:column")'
            )
        return Name(name)

    def raw(self) -> Node:
        self.expect("(")
        t = self.next()
        if t.kind != "str":
            raise DSLError('raw() takes one quoted "dataset:column" string')
        if ":" not in t.text or not t.text.strip():
            raise DSLError('raw() needs a "dataset:column" string, e.g. raw("income_statement:cogs_hosting")')
        self.expect(")")
        return Raw(t.text)

    def call(self, fn: str) -> Node:
        self.expect("(")
        args: list[Node] = []
        if not (self.peek().kind == "op" and self.peek().text == ")"):
            while True:
                args.append(self.expr(0))
                if self.peek().kind == "op" and self.peek().text == ",":
                    self.next()
                    continue
                break
        self.expect(")")
        lo, hi, int_args = FUNCTIONS[fn]
        if len(args) < lo or (hi is not None and len(args) > hi):
            want = f"{lo}" if lo == hi else f"{lo}+" if hi is None else f"{lo}-{hi}"
            raise DSLError(f"{fn}() takes {want} argument{'s' if want != '1' else ''}, got {len(args)}")
        for k in int_args:
            a = args[k]
            if not (isinstance(a, Num) and a.value == int(a.value) and 1 <= a.value <= MAX_WINDOW):
                raise DSLError(f"argument {k + 1} of {fn}() must be a whole number from 1 to {MAX_WINDOW}")
        return Call(fn, tuple(args))


def parse(src: str) -> Node:
    """Parse an expression into an AST or raise DSLError with a clear message."""
    if not isinstance(src, str):
        raise DSLError("expression must be text")
    return _Parser(src).parse()


# ---------------------------------------------------------------- helpers over the AST


def names(node: Node) -> list[Name | Raw]:
    """Every identifier and raw column the expression reads, in order, without duplicates."""
    out: list[Name | Raw] = []

    def walk(n: Node) -> None:
        if isinstance(n, Name | Raw):
            if n not in out:
                out.append(n)
        elif isinstance(n, Neg):
            walk(n.operand)
        elif isinstance(n, Bin):
            walk(n.left)
            walk(n.right)
        elif isinstance(n, Call):
            for a in n.args:
                walk(a)

    walk(node)
    return out


def _fmt_num(v: float) -> str:
    return str(int(v)) if v == int(v) else repr(v)


def to_source(node: Node, parent_bp: int = 0) -> str:
    """Canonical text for an AST (ASCII operators)."""
    if isinstance(node, Num):
        s = _fmt_num(node.value)
        return f"({s})" if node.value < 0 and parent_bp else s
    if isinstance(node, Name):
        return node.id
    if isinstance(node, Raw):
        return f'raw("{node.key}")'
    if isinstance(node, Neg):
        return f"-{to_source(node.operand, _PREFIX_BP)}"
    if isinstance(node, Bin):
        bp = _BINARY_BP[node.op]
        s = f"{to_source(node.left, bp - 1)} {node.op} {to_source(node.right, bp)}"
        return f"({s})" if bp <= parent_bp else s
    return f"{node.fn}({', '.join(to_source(a) for a in node.args)})"
