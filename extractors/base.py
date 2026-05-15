"""BaseExtractor: abstract interface for language-specific knowledge graph extractors."""
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass
class OneFileResult:
    """Result of extracting constructs from a single source file.

    All fields are lists of dicts matching the extractor_output.schema.json.
    Each language extractor fills these in extract_file().
    """
    modules: list[dict] = field(default_factory=list)
    classes: list[dict] = field(default_factory=list)
    methods: list[dict] = field(default_factory=list)
    functions: list[dict] = field(default_factory=list)
    imports: list[dict] = field(default_factory=list)
    compositions: list[dict] = field(default_factory=list)
    signals: list[dict] = field(default_factory=list)
    call_sites: list[dict] = field(default_factory=list)
    error_handlers: list[dict] = field(default_factory=list)
    raises: list[dict] = field(default_factory=list)
    conditions: list[dict] = field(default_factory=list)
    returns: list[dict] = field(default_factory=list)
    withs: list[dict] = field(default_factory=list)
    signal_emits: list[dict] = field(default_factory=list)
    attr_assignments: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


_EXCLUDED_DIRS = {
    "__pycache__", ".venv", "venv", "dist", "build", ".git",
    ".pytest_cache", ".ruff_cache", "node_modules", ".mypy_cache",
    ".egg-info", ".sisyphus", ".claude", ".github",
}
_EXCLUDED_FILES = {"__init__.py", "setup.py", "conftest.py"}  # skip init-only files


class BaseExtractor(ABC):
    """Abstract base for all language extractors.

    Subclasses MUST implement extract_file().
    extract() is shared: it walks the project, delegates to extract_file per file,
    then runs cross-file resolution passes.
    """

    def __init__(self, project_root: Path, language: str):
        self.project_root = Path(project_root).resolve()
        self.language = language
        self.extractor_version = "1.0.0"
        self.file_suffixes: set[str] = set()  # e.g. {".py"}, subclasses must set
        self.schema_version = "1.0.0"

    # ── Subclass responsibility ──

    @abstractmethod
    def extract_file(self, source: str, file_path: str, mod_name: str) -> OneFileResult:
        """Parse one source file and return all constructs found.

        Args:
            source: Raw source code as string.
            file_path: Repo-relative path (POSIX '/') e.g. 'engine/foo.py'.
            mod_name: Dotted module name e.g. 'engine.foo'.
        Returns:
            OneFileResult with all discovered constructs.
        """
        ...

    # ── Shared extraction pipeline ──

    def extract(self) -> dict:
        """Main entry: walk project, parse all files, resolve cross-references."""
        coverage = {
            "files_scanned": 0, "files_parsed_ok": 0, "parse_errors": 0,
            "parse_error_files": [], "functions_found": 0, "calls_found": 0,
            "imports_found": 0, "classes_found": 0, "conditions_found": 0,
            "error_handlers_found": 0,
        }

        merged = OneFileResult()

        for filepath in self._walk_project():
            coverage["files_scanned"] += 1
            rel_path = self._relative_path(filepath)
            mod_name = self._compute_module_name(rel_path)

            try:
                source = self._read_file(filepath)
            except Exception:
                continue

            result = self.extract_file(source, rel_path, mod_name)
            if result.errors:
                coverage["parse_errors"] += 1
                coverage["parse_error_files"].append(rel_path)
            else:
                coverage["files_parsed_ok"] += 1

            # Merge all lists
            merged.modules.append({"name": mod_name, "path": rel_path, "lines": source.count("\n") + 1})
            merged.classes.extend(result.classes)
            merged.methods.extend(result.methods)
            merged.functions.extend(result.functions)
            merged.imports.extend(result.imports)
            merged.compositions.extend(result.compositions)
            merged.signals.extend(result.signals)
            merged.call_sites.extend(result.call_sites)
            merged.error_handlers.extend(result.error_handlers)
            merged.raises.extend(result.raises)
            merged.conditions.extend(result.conditions)
            merged.returns.extend(result.returns)
            merged.withs.extend(result.withs)
            merged.signal_emits.extend(result.signal_emits)
            merged.attr_assignments.extend(result.attr_assignments)

        # Resolve compositions and call targets (second pass)
        all_class_names = {c["name"] for c in merged.classes}
        all_class_fqns = {c["fqn"] for c in merged.classes}
        resolved_compositions = self._filter_compositions(merged.compositions, all_class_names)
        resolved_call_sites = self._resolve_calls(merged.call_sites, list(merged.methods), all_class_fqns)

        # Coverage stats
        coverage["functions_found"] = len(merged.functions)
        coverage["calls_found"] = len(merged.call_sites)
        coverage["imports_found"] = len(merged.imports)
        coverage["classes_found"] = len(merged.classes)
        coverage["conditions_found"] = len(merged.conditions)
        coverage["error_handlers_found"] = len(merged.error_handlers)

        return {
            "schema_version": self.schema_version,
            "language": self.language,
            "extractor_version": self.extractor_version,
            "project_root": str(self.project_root),
            "data": {
                "modules": merged.modules,
                "classes": merged.classes,
                "methods": merged.methods,
                "functions": merged.functions,
                "imports": merged.imports,
                "compositions": resolved_compositions,
                "signals": merged.signals,
                "call_sites": resolved_call_sites,
                "error_handlers": merged.error_handlers,
                "raises": merged.raises,
                "conditions": merged.conditions,
                "returns": merged.returns,
                "withs": merged.withs,
                "signal_emits": merged.signal_emits,
                "attr_assignments": merged.attr_assignments,
            },
            "coverage": coverage,
        }

    # ── Shared helpers ──

    def _walk_project(self):
        """Yield all source files in the project directory matching file_suffixes."""
        for suffix in self.file_suffixes:
            for p in self.project_root.rglob(f"*{suffix}"):
                if self._is_excluded(p):
                    continue
                yield p

    def _is_excluded(self, path: Path) -> bool:
        """Check if a path should be excluded."""
        for part in path.parts:
            if part in _EXCLUDED_DIRS:
                return True
            if part.startswith(".") and part not in (".",):
                return True
        if path.name in _EXCLUDED_FILES:
            return True
        return False

    def _relative_path(self, path: Path) -> str:
        """Convert absolute path to repo-relative POSIX path."""
        return str(path.relative_to(self.project_root)).replace("\\", "/")

    def _compute_module_name(self, rel_path: str) -> str:
        """Convert relative file path to dotted module name.
        e.g. 'engine/foo.py' → 'engine.foo'
        Override for languages with different namespace rules.
        """
        name = rel_path.replace("/", ".").replace("\\", ".")
        for suffix in self.file_suffixes:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return name

    def _read_file(self, filepath: Path) -> str:
        """Read source file, trying utf-8 first then latin-1."""
        try:
            return filepath.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return filepath.read_text(encoding="latin-1")

    def _filter_compositions(self, compositions: list[dict], all_class_names: set[str]) -> list[dict]:
        """Keep only compositions whose target matches a known class."""
        return [c for c in compositions if c.get("composes") in all_class_names]

    def _resolve_calls(self, call_sites: list[dict], methods: list[dict],
                       all_class_fqns: set[str]) -> list[dict]:
        """Resolve call targets: try to match self.X.method() patterns.
        This is a generic version. Python may need a richer version in its subclass.
        """
        resolved = []
        for cs in call_sites:
            item = dict(cs)
            if item.get("resolved_target"):
                # Already resolved by the extractor
                if item["resolved_target"] and item["resolved_target"] not in {m["fqn"] for m in methods}:
                    item["resolution"] = "heuristic"
                else:
                    item["resolution"] = "exact"
                    item["confidence"] = "high"
            else:
                item["confidence"] = "low"
                item["resolution"] = "unresolved"
            resolved.append(item)
        return resolved


def _build_method_fqn_map(methods: list[dict]) -> dict[str, dict]:
    return {m["fqn"]: m for m in methods}
