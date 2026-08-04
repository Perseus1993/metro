"""Discover compiler diagnostics and their concrete emission sites.

This is a repository test tool, not a portable runtime API.  The compiler owns
the diagnostic strings; the testkit derives its coverage target from the
installed compiler sources so a new code or emitter makes the acceptance gate
fail until an executable adversarial probe is added.
"""

from __future__ import annotations

import ast
import importlib.util
import re
from dataclasses import dataclass
from pathlib import Path


CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


def _compilation_source_dir() -> Path:
    spec = importlib.util.find_spec(
        "metro_station.adapters.simulation.compilation"
    )
    locations = () if spec is None else tuple(spec.submodule_search_locations or ())
    if not locations:
        raise FileNotFoundError(
            "installed metro_station compilation package has no source directory"
        )
    source_dir = Path(locations[0]).resolve()
    if not source_dir.is_dir():
        raise FileNotFoundError(
            f"compilation source directory is missing: {source_dir}"
        )
    return source_dir


COMPILATION_SOURCE_DIR = _compilation_source_dir()


@dataclass(frozen=True)
class CompilationCodeSite:
    """One literal diagnostic code in compiler source."""

    code: str
    file: Path
    line: int
    column: int
    function: str

    @property
    def site_id(self) -> str:
        return (
            f"{self.file.name}:{self.function}:{self.line}:{self.column}:{self.code}"
        )


@dataclass(frozen=True)
class CompilationEmitterSite:
    """One call to ``issue``/``_issue``, including variable-code emitters."""

    file: Path
    line: int
    column: int
    function: str
    severity: str | None
    code: str | None

    @property
    def site_id(self) -> str:
        code = self.code or "<dynamic>"
        return f"{self.file.name}:{self.function}:{self.line}:{self.column}:{code}"


@dataclass(frozen=True)
class CompilationProducerSite:
    """One literal origin that feeds a later variable-code emitter."""

    code: str
    file: Path
    line: int
    column: int
    function: str

    @property
    def site_id(self) -> str:
        return (
            f"{self.file.name}:{self.function}:{self.line}:{self.column}:{self.code}"
        )


def compilation_source_files() -> tuple[Path, ...]:
    """Return all Python compiler sources in deterministic order."""

    return tuple(sorted(COMPILATION_SOURCE_DIR.rglob("*.py")))


def discover_literal_code_sites() -> tuple[CompilationCodeSite, ...]:
    """Return code-shaped AST string constants, independent of quote style."""

    sites: list[CompilationCodeSite] = []
    for source_file in compilation_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"),
            filename=str(source_file),
        )
        parents = _parents(tree)
        for node in ast.walk(tree):
            code = _literal_string(node)
            if code is None or CODE_PATTERN.fullmatch(code) is None:
                continue
            sites.append(
                CompilationCodeSite(
                    code=code,
                    file=source_file,
                    line=int(getattr(node, "lineno", 0)),
                    column=int(getattr(node, "col_offset", 0)),
                    function=_enclosing_function(node, parents),
                )
            )
    return tuple(
        sorted(sites, key=lambda site: (str(site.file), site.line, site.code))
    )


def discover_compilation_codes() -> frozenset[str]:
    """Return the compiler's distinct diagnostic-code contract."""

    return frozenset(site.code for site in discover_literal_code_sites())


def discover_emitter_sites() -> tuple[CompilationEmitterSite, ...]:
    """Find every concrete ``issue``/``_issue`` call, including dynamic codes."""

    sites: list[CompilationEmitterSite] = []
    for source_file in compilation_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"),
            filename=str(source_file),
        )
        parents = _parents(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _call_name(node) not in {
                "issue",
                "_issue",
            }:
                continue
            severity_node = _call_argument(node, 0, "severity")
            code_node = _call_argument(node, 1, "code")
            sites.append(
                CompilationEmitterSite(
                    file=source_file,
                    line=node.lineno,
                    column=node.col_offset,
                    function=_enclosing_function(node, parents),
                    severity=_literal_string(severity_node),
                    code=_literal_string(code_node),
                )
            )
    return tuple(sorted(sites, key=lambda site: (str(site.file), site.line)))


def discover_code_sites() -> tuple[CompilationEmitterSite, ...]:
    """Backward-compatible name for the stronger emitter-site inventory."""

    return discover_emitter_sites()


def discover_producer_sites() -> tuple[CompilationProducerSite, ...]:
    """Find literal code origins used outside direct diagnostic calls.

    Comparison-only literals are consumers, not producers.  A producer is a
    code-shaped constant returned or assigned before a later dynamic emitter.
    """

    sites: list[CompilationProducerSite] = []
    for source_file in compilation_source_files():
        tree = ast.parse(
            source_file.read_text(encoding="utf-8"),
            filename=str(source_file),
        )
        parents = _parents(tree)
        for node in ast.walk(tree):
            code = _literal_string(node)
            if code is None or CODE_PATTERN.fullmatch(code) is None:
                continue
            if _is_direct_emitter_code(node, parents) or _inside_compare(
                node,
                parents,
            ):
                continue
            sites.append(
                CompilationProducerSite(
                    code=code,
                    file=source_file,
                    line=int(getattr(node, "lineno", 0)),
                    column=int(getattr(node, "col_offset", 0)),
                    function=_enclosing_function(node, parents),
                )
            )
    return tuple(sorted(sites, key=lambda site: (str(site.file), site.line, site.column)))


def _parents(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    parents: dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def _enclosing_function(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> str:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return current.name
    return "<module>"


def _is_direct_emitter_code(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    current = node
    while current in parents:
        parent = parents[current]
        if isinstance(parent, ast.Call):
            if _call_name(parent) not in {"issue", "_issue"}:
                return False
            return _call_argument(parent, 1, "code") is node
        if isinstance(parent, ast.stmt):
            return False
        current = parent
    return False


def _inside_compare(
    node: ast.AST,
    parents: dict[ast.AST, ast.AST],
) -> bool:
    current = node
    while current in parents:
        current = parents[current]
        if isinstance(current, ast.Compare):
            return True
        if isinstance(current, ast.stmt):
            return False
    return False


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _call_argument(node: ast.Call, position: int, keyword: str) -> ast.AST | None:
    if len(node.args) > position:
        return node.args[position]
    return next(
        (item.value for item in node.keywords if item.arg == keyword),
        None,
    )


def _literal_string(node: ast.AST | None) -> str | None:
    return (
        node.value
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
        else None
    )


__all__ = [
    "CODE_PATTERN",
    "COMPILATION_SOURCE_DIR",
    "CompilationCodeSite",
    "CompilationEmitterSite",
    "CompilationProducerSite",
    "compilation_source_files",
    "discover_code_sites",
    "discover_compilation_codes",
    "discover_emitter_sites",
    "discover_literal_code_sites",
    "discover_producer_sites",
]
