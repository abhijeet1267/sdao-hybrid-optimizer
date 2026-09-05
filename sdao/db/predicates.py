"""Safe translation of the current pandas-style workload predicates to SQL."""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

ALLOWED_COLUMNS = frozenset({"category", "brand", "price", "rating", "stock"})
_TOKEN = re.compile(r"\s*(?:(?P<string>'(?:[^'\\]|\\.)*')|(?P<number>\d+(?:\.\d+)?)|(?P<op>==|!=|<=|>=|<|>)|(?P<paren>[()])|(?P<word>[A-Za-z_][A-Za-z0-9_]*))")


class PredicateError(ValueError):
    pass


@dataclass(frozen=True)
class SQLPredicate:
    sql: str
    params: tuple[Any, ...]


def _tokens(text: str) -> list[tuple[str, str]]:
    position, out = 0, []
    while position < len(text):
        match = _TOKEN.match(text, position)
        if not match:
            raise PredicateError(f"Unsupported predicate syntax near: {text[position:position + 20]!r}")
        position = match.end()
        kind = next(name for name, value in match.groupdict().items() if value is not None)
        out.append((kind, match.group(kind)))
    if not out:
        raise PredicateError("Predicate cannot be empty")
    return out


class _Parser:
    def __init__(self, tokens: list[tuple[str, str]]) -> None:
        self.tokens, self.position, self.params = tokens, 0, []

    def take(self, kind: str | None = None, value: str | None = None) -> tuple[str, str]:
        if self.position >= len(self.tokens):
            raise PredicateError("Unexpected end of predicate")
        token = self.tokens[self.position]
        if (kind and token[0] != kind) or (value and token[1].lower() != value):
            raise PredicateError(f"Expected {value or kind}, got {token[1]!r}")
        self.position += 1
        return token

    def expression(self) -> str:
        left = self.conjunction()
        while self.position < len(self.tokens) and self.tokens[self.position] == ("word", "or"):
            self.position += 1
            left = f"({left} OR {self.conjunction()})"
        return left

    def conjunction(self) -> str:
        left = self.term()
        while self.position < len(self.tokens) and self.tokens[self.position] == ("word", "and"):
            self.position += 1
            left = f"({left} AND {self.term()})"
        return left

    def term(self) -> str:
        if self.position < len(self.tokens) and self.tokens[self.position] == ("paren", "("):
            self.position += 1
            expression = self.expression()
            self.take("paren", ")")
            return f"({expression})"
        _, column = self.take("word")
        if column not in ALLOWED_COLUMNS:
            raise PredicateError(f"Column {column!r} is not allowed")
        _, operator = self.take("op")
        kind, raw = self.take()
        if kind == "string":
            value: Any = bytes(raw[1:-1], "utf-8").decode("unicode_escape")
        elif kind == "number":
            value = float(raw) if "." in raw else int(raw)
        elif kind == "word" and raw in {"True", "False"}:
            value = raw == "True"
        else:
            raise PredicateError("Predicate values must be quoted strings, numbers, or True/False")
        self.params.append(value)
        return f'"{column}" {"=" if operator == "==" else operator} %s'


def translate_predicate(predicate: str) -> SQLPredicate:
    parser = _Parser(_tokens(predicate))
    sql = parser.expression()
    if parser.position != len(parser.tokens):
        raise PredicateError(f"Unexpected token {parser.tokens[parser.position][1]!r}")
    return SQLPredicate(sql, tuple(parser.params))
