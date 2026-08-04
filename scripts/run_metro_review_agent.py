from __future__ import annotations

import argparse
import ast
import csv
import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = ROOT / "output" / "metro_review_agent"
AGENT_NAME = "Metro Review Agent"
DEFAULT_SCAN_PATHS = (
    ROOT / "sandbox" / "metro_station_sandbox",
    ROOT / "scripts" / "run_metro_boundary_hack_agent.py",
    ROOT / "scripts" / "run_metro_stress_matrix.py",
    ROOT / "scripts" / "analyze_metro_tracks.py",
    ROOT / "tests",
)
SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
KEYWORD_RULES = {
    "smoke": ("high", "forbidden_smoke_reference"),
    "fallback": ("medium", "fallback_reference"),
    "legacy": ("medium", "legacy_reference"),
    "mock": ("medium", "mock_reference"),
    "simple": ("low", "simple_reference"),
    "linear": ("low", "linear_reference"),
    "straight": ("low", "straight_reference"),
}


@dataclass(frozen=True)
class Finding:
    rule_id: str
    severity: str
    category: str
    path: str
    line: int
    symbol: str
    message: str
    recommendation: str
    evidence: str = ""


@dataclass(frozen=True)
class PythonSource:
    path: Path
    rel_path: str
    text: str
    tree: ast.AST

    @property
    def lines(self) -> list[str]:
        return self.text.splitlines()


@dataclass(frozen=True)
class OutputPaths:
    csv_path: Path
    json_path: Path
    markdown_path: Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Static architecture review agent for metro simulation code. "
            "Checks redundancy, fallback risk, and unreasonable coupling."
        )
    )
    parser.add_argument(
        "--path",
        action="append",
        dest="paths",
        type=Path,
        help="File or directory to scan. Can be repeated. Defaults to metro simulation paths.",
    )
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--output-stem", default="metro_review_agent")
    parser.add_argument("--csv-out", type=Path, default=None)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--md-out", type=Path, default=None)
    parser.add_argument(
        "--fail-on",
        choices=("none", "high", "medium", "low"),
        default="none",
        help="Return exit code 1 when findings at or above this severity are present.",
    )
    parser.add_argument("--quiet", action="store_true")
    return parser


def output_paths(args: argparse.Namespace) -> OutputPaths:
    return OutputPaths(
        csv_path=args.csv_out or args.out_dir / f"{args.output_stem}.csv",
        json_path=args.json_out or args.out_dir / f"{args.output_stem}.json",
        markdown_path=args.md_out or args.out_dir / f"{args.output_stem}.md",
    )


def collect_python_sources(paths: Sequence[Path], *, root: Path = ROOT) -> list[PythonSource]:
    sources: list[PythonSource] = []
    for raw_path in paths:
        path = raw_path if raw_path.is_absolute() else root / raw_path
        if not path.exists():
            continue
        candidates = [path] if path.is_file() else sorted(path.rglob("*.py"))
        for candidate in candidates:
            if _is_excluded(candidate):
                continue
            try:
                text = candidate.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            rel_path = _relative_path(candidate, root)
            sources.append(PythonSource(candidate, rel_path, text, tree))
    return _dedupe_sources(sources)


def review_sources(sources: Sequence[PythonSource]) -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(_large_file_findings(sources))
    findings.extend(_large_symbol_findings(sources))
    findings.extend(_duplicate_body_findings(sources))
    findings.extend(_broad_exception_findings(sources))
    findings.extend(_keyword_findings(sources))
    findings.extend(_coupling_findings(sources))
    findings.extend(_test_private_api_findings(sources))
    return sorted(
        findings,
        key=lambda item: (SEVERITY_ORDER[item.severity], item.category, item.path, item.line),
    )


def write_outputs(
    paths: OutputPaths,
    *,
    args: argparse.Namespace,
    sources: Sequence[PythonSource],
    findings: Sequence[Finding],
) -> None:
    for path in (paths.csv_path, paths.json_path, paths.markdown_path):
        path.parent.mkdir(parents=True, exist_ok=True)

    rows = [asdict(finding) for finding in findings]
    with paths.csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(Finding.__dataclass_fields__))
        writer.writeheader()
        writer.writerows(rows)

    payload = {
        "generated_by": "scripts.run_metro_review_agent",
        "agent_name": AGENT_NAME,
        "generated_at": datetime.now(UTC).isoformat(),
        "parameters": {key: str(value) for key, value in vars(args).items()},
        "summary": _summary(sources, findings),
        "findings": rows,
    }
    paths.json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    paths.markdown_path.write_text(_markdown_report(payload), encoding="utf-8")


def should_fail(findings: Sequence[Finding], fail_on: str) -> bool:
    if fail_on == "none":
        return False
    threshold = SEVERITY_ORDER[fail_on]
    return any(SEVERITY_ORDER[item.severity] <= threshold for item in findings)


def _is_excluded(path: Path) -> bool:
    parts = set(path.parts)
    return "__pycache__" in parts or ".ruff_cache" in parts or path.suffix != ".py"


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _dedupe_sources(sources: Sequence[PythonSource]) -> list[PythonSource]:
    deduped: dict[Path, PythonSource] = {}
    for source in sources:
        deduped[source.path.resolve()] = source
    return sorted(deduped.values(), key=lambda item: item.rel_path)


def _large_file_findings(sources: Sequence[PythonSource]) -> list[Finding]:
    findings: list[Finding] = []
    for source in sources:
        count = len(source.lines)
        if count < 500:
            continue
        severity = "high" if count >= 800 else "medium"
        findings.append(
            Finding(
                rule_id="large_file",
                severity=severity,
                category="redundancy",
                path=source.rel_path,
                line=1,
                symbol=source.path.stem,
                message=f"File has {count} lines, which makes unrelated behavior easy to couple.",
                recommendation="Split by stable responsibilities: data model, routing, process state, export, and CLI glue.",
            )
        )
    return findings


def _large_symbol_findings(sources: Sequence[PythonSource]) -> list[Finding]:
    findings: list[Finding] = []
    for source in sources:
        for node in ast.walk(source.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            end_line = getattr(node, "end_lineno", node.lineno)
            size = end_line - node.lineno + 1
            if size < 120:
                continue
            severity = "high" if size >= 300 else "medium"
            findings.append(
                Finding(
                    rule_id="large_symbol",
                    severity=severity,
                    category="redundancy",
                    path=source.rel_path,
                    line=node.lineno,
                    symbol=node.name,
                    message=f"{type(node).__name__} spans {size} lines.",
                    recommendation="Extract cohesive helpers or strategy objects behind an explicit boundary.",
                )
            )
    return findings


def _duplicate_body_findings(sources: Sequence[PythonSource]) -> list[Finding]:
    groups: dict[str, list[tuple[PythonSource, ast.AST, int]]] = {}
    for source in sources:
        for node in ast.walk(source.tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            end_line = getattr(node, "end_lineno", node.lineno)
            size = end_line - node.lineno + 1
            if size < 8:
                continue
            body = ast.dump(ast.Module(body=node.body, type_ignores=[]), include_attributes=False)
            digest = hashlib.sha1(body.encode("utf-8")).hexdigest()
            groups.setdefault(digest, []).append((source, node, size))

    findings: list[Finding] = []
    for group in groups.values():
        if len(group) < 2:
            continue
        first_source, first_node, first_size = group[0]
        evidence = "; ".join(
            f"{source.rel_path}:{node.lineno} {node.name}" for source, node, _size in group[:8]
        )
        findings.append(
            Finding(
                rule_id="duplicate_function_body",
                severity="medium",
                category="redundancy",
                path=first_source.rel_path,
                line=first_node.lineno,
                symbol=first_node.name,
                message=f"Exact duplicate function body appears {len(group)} times.",
                recommendation="Move shared logic into a small helper and keep callers responsible only for naming/IO differences.",
                evidence=f"lines={first_size}; duplicates={evidence}",
            )
        )
    return findings


def _broad_exception_findings(sources: Sequence[PythonSource]) -> list[Finding]:
    findings: list[Finding] = []
    for source in sources:
        for node in ast.walk(source.tree):
            if not isinstance(node, ast.ExceptHandler) or not _is_broad_exception(node):
                continue
            has_raise = any(isinstance(child, ast.Raise) for child in ast.walk(node))
            swallows = any(
                isinstance(child, (ast.Pass, ast.Return, ast.Continue, ast.Break))
                for child in ast.walk(node)
            )
            severity = "medium" if has_raise and not swallows else "high"
            message = (
                "Broad exception handler wraps and re-raises."
                if has_raise
                else ("Broad exception handler can swallow algorithmic failure.")
            )
            findings.append(
                Finding(
                    rule_id="broad_exception",
                    severity=severity,
                    category="fallback",
                    path=source.rel_path,
                    line=node.lineno,
                    symbol=_enclosing_symbol(source.tree, node.lineno),
                    message=message,
                    recommendation="Catch the concrete exception type. If degradation is intentional, log/audit it as an explicit diagnostic.",
                )
            )
    return findings


def _keyword_findings(sources: Sequence[PythonSource]) -> list[Finding]:
    findings: list[Finding] = []
    for source in sources:
        if not _is_relevant_metro_source(source.rel_path):
            continue
        seen_per_file: dict[str, int] = {}
        for line_number, line in enumerate(source.lines, start=1):
            lower = line.lower()
            for keyword, (severity, rule_id) in KEYWORD_RULES.items():
                if not re.search(rf"\b{re.escape(keyword)}\b", lower):
                    continue
                seen_per_file[keyword] = seen_per_file.get(keyword, 0) + 1
                if seen_per_file[keyword] > 5:
                    continue
                findings.append(
                    Finding(
                        rule_id=rule_id,
                        severity=severity,
                        category="fallback",
                        path=source.rel_path,
                        line=line_number,
                        symbol=_enclosing_symbol(source.tree, line_number),
                        message=f"Review keyword {keyword!r} appears in simulation code.",
                        recommendation="Confirm this is documented compatibility code. Remove if it bypasses the formal Mesa+JuPedSim path.",
                        evidence=line.strip()[:180],
                    )
                )
    return findings


def _coupling_findings(sources: Sequence[PythonSource]) -> list[Finding]:
    findings: list[Finding] = []
    for source in sources:
        if not _is_core_metro_source(source.rel_path):
            continue
        for node in ast.walk(source.tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            imported = _import_name(node)
            if "visual_demo" not in imported:
                continue
            findings.append(
                Finding(
                    rule_id="core_imports_visual_demo",
                    severity="high",
                    category="coupling",
                    path=source.rel_path,
                    line=node.lineno,
                    symbol=_enclosing_symbol(source.tree, node.lineno),
                    message="Core simulation module imports visual_demo code.",
                    recommendation="Move shared geometry/export data behind a core design/geometry provider; visual_demo should depend on core, not the reverse.",
                    evidence=imported,
                )
            )
        for line_number, line in enumerate(source.lines, start=1):
            if "visual_demo_station" not in line:
                continue
            findings.append(
                Finding(
                    rule_id="core_visual_template_branch",
                    severity="medium",
                    category="coupling",
                    path=source.rel_path,
                    line=line_number,
                    symbol=_enclosing_symbol(source.tree, line_number),
                    message="Core code has a visual_demo_station-specific branch.",
                    recommendation="Push template-specific behavior into StationDesignDocument data or a pluggable geometry/layout provider.",
                    evidence=line.strip()[:180],
                )
            )
    return findings


def _test_private_api_findings(sources: Sequence[PythonSource]) -> list[Finding]:
    findings: list[Finding] = []
    for source in sources:
        if not source.rel_path.startswith("tests/"):
            continue
        for node in ast.walk(source.tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr.startswith("_")
                and node.attr != "__dict__"
            ):
                findings.append(
                    Finding(
                        rule_id="test_private_api_access",
                        severity="low",
                        category="coupling",
                        path=source.rel_path,
                        line=node.lineno,
                        symbol=_enclosing_symbol(source.tree, node.lineno),
                        message=f"Test reaches into private member {node.attr!r}.",
                        recommendation="Prefer public behavior tests, or promote the helper to a documented testing seam.",
                    )
                )
            elif isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    if alias.name.startswith("_"):
                        findings.append(
                            Finding(
                                rule_id="test_private_api_import",
                                severity="low",
                                category="coupling",
                                path=source.rel_path,
                                line=node.lineno,
                                symbol=_enclosing_symbol(source.tree, node.lineno),
                                message=f"Test imports private symbol {alias.name!r}.",
                                recommendation="Prefer public behavior tests, or promote the helper to a documented testing seam.",
                            )
                        )
    return findings[:80]


def _is_broad_exception(node: ast.ExceptHandler) -> bool:
    if node.type is None:
        return True
    if isinstance(node.type, ast.Name):
        return node.type.id in {"Exception", "BaseException"}
    if isinstance(node.type, ast.Tuple):
        return any(isinstance(item, ast.Name) and item.id == "Exception" for item in node.type.elts)
    return False


def _import_name(node: ast.Import | ast.ImportFrom) -> str:
    if isinstance(node, ast.Import):
        return ",".join(alias.name for alias in node.names)
    prefix = "." * node.level
    names = ",".join(alias.name for alias in node.names)
    return f"{prefix}{node.module or ''}:{names}"


def _is_relevant_metro_source(rel_path: str) -> bool:
    return rel_path.startswith("sandbox/metro_station_sandbox/") or rel_path in {
        "scripts/run_metro_boundary_hack_agent.py",
        "scripts/run_metro_stress_matrix.py",
        "scripts/analyze_metro_tracks.py",
    }


def _is_core_metro_source(rel_path: str) -> bool:
    if not rel_path.startswith("sandbox/metro_station_sandbox/"):
        return False
    excluded = (
        "apps/station_visualizer/src/metro_station_visualizer/",
        "sandbox/metro_station_sandbox/app.py",
        "sandbox/metro_station_sandbox/record_video.py",
        "sandbox/metro_station_sandbox/render_html.py",
    )
    return not rel_path.startswith(excluded)


def _enclosing_symbol(tree: ast.AST, line_number: int) -> str:
    best: tuple[int, str] | None = None
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        end_line = getattr(node, "end_lineno", node.lineno)
        if node.lineno <= line_number <= end_line:
            span = end_line - node.lineno
            if best is None or span < best[0]:
                best = (span, node.name)
    return best[1] if best is not None else "<module>"


def _summary(sources: Sequence[PythonSource], findings: Sequence[Finding]) -> dict[str, object]:
    by_severity = {severity: 0 for severity in SEVERITY_ORDER}
    by_category: dict[str, int] = {}
    for finding in findings:
        by_severity[finding.severity] += 1
        by_category[finding.category] = by_category.get(finding.category, 0) + 1
    return {
        "files_scanned": len(sources),
        "findings": len(findings),
        "by_severity": by_severity,
        "by_category": by_category,
    }


def _markdown_report(payload: dict[str, object]) -> str:
    summary = payload["summary"]
    assert isinstance(summary, dict)
    findings = payload["findings"]
    assert isinstance(findings, list)
    lines = [
        "# Metro Review Agent",
        "",
        f"- agent: {payload['agent_name']}",
        f"- files_scanned: {summary['files_scanned']}",
        f"- findings: {summary['findings']}",
        f"- high: {summary['by_severity']['high']}",
        f"- medium: {summary['by_severity']['medium']}",
        f"- low: {summary['by_severity']['low']}",
        "",
        "| severity | category | rule | file | line | symbol | message | recommendation |",
        "| --- | --- | --- | --- | ---: | --- | --- | --- |",
    ]
    for finding in findings[:100]:
        lines.append(
            "| {severity} | {category} | {rule_id} | {path} | {line} | {symbol} | {message} | {recommendation} |".format(
                **finding
            )
        )
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    paths = output_paths(args)
    scan_paths = tuple(args.paths) if args.paths else DEFAULT_SCAN_PATHS
    sources = collect_python_sources(scan_paths)
    findings = review_sources(sources)
    write_outputs(paths, args=args, sources=sources, findings=findings)

    summary = _summary(sources, findings)
    if not args.quiet:
        print(
            "[REVIEW] "
            f"files={summary['files_scanned']} findings={summary['findings']} "
            f"high={summary['by_severity']['high']} medium={summary['by_severity']['medium']} "
            f"low={summary['by_severity']['low']}"
        )
    print(f"[REVIEW] wrote_csv={paths.csv_path.resolve()}")
    print(f"[REVIEW] wrote_json={paths.json_path.resolve()}")
    print(f"[REVIEW] wrote_markdown={paths.markdown_path.resolve()}")
    return 1 if should_fail(findings, args.fail_on) else 0


if __name__ == "__main__":
    raise SystemExit(main())
