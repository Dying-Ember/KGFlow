"""Extractor registry and language detection."""

from pathlib import Path
from typing import Optional

from extractors.base import BaseExtractor

EXTRACTORS: dict[str, type[BaseExtractor]] = {}

def register(language: str):
    """Decorator to register an extractor class."""
    def decorator(cls):
        EXTRACTORS[language] = cls
        return cls
    return decorator


def detect_language(project_root: Path, kgflow_config: Optional[dict] = None) -> str:
    """Detect project language.

    Priority:
    1. kgflow.toml [project.languages] (explicit)
    2. Heuristic: check which file suffixes are present
    3. Fallback: "python"
    """
    if kgflow_config and "languages" in kgflow_config.get("project", {}):
        langs = kgflow_config["project"]["languages"]
        if len(langs) == 1:
            return langs[0]
        # Multiple languages configured; not yet supported
        return langs[0]

    # Heuristic: scan for file types
    counts = {}
    for ext in _SUFFIX_MAP:
        count = len(list(project_root.rglob(f"*{ext}")))
        if count > 0:
            counts[_SUFFIX_MAP[ext]] = counts.get(_SUFFIX_MAP[ext], 0) + count

    if not counts:
        return "python"
    return max(counts, key=counts.get)


_SUFFIX_MAP = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".jsx": "javascript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".cs": "csharp",
    ".rb": "ruby",
    ".kt": "kotlin",
    ".swift": "swift",
}


def create_extractor(language: str, project_root: Path) -> BaseExtractor:
    """Factory: create an extractor for the given language."""
    cls = EXTRACTORS.get(language)
    if cls is None:
        raise ValueError(f"No extractor registered for language: {language}. "
                         f"Available: {list(EXTRACTORS.keys())}")
    return cls(project_root)


# Import AFTER registry definition to avoid circular imports
# (extractors import base, python_extractor imports base+register)
# Lazy imports happen at the end of this file

def _load_extractors():
    """Lazy-import all available extractors so they register themselves."""
    try:
        from extractors.python_extractor import PythonAstExtractor  # noqa: F401
    except ImportError:
        pass
    # Future: from extractors.go_extractor import GoExtractor
    # Future: from extractors.javascript_extractor import JavaScriptExtractor

_load_extractors()
