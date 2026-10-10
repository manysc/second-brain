"""Enforces the Clean Architecture dependency rule (see architecture.md) by scanning imports with `ast`.

- app.domain          -> stdlib, numpy, app.domain
- app.application     -> stdlib, numpy, app.domain, app.application
- app.infrastructure  -> anything except app.presentation
- app.presentation    -> anything except app.infrastructure (only composition roots wire infrastructure in)
- composition roots (app.main, app.container, app.presentation.mcp.__main__) may import every layer.
Every module under app/ belongs to a layer or is a composition root: there are no flat modules beside them."""
from __future__ import annotations

import ast
import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent / "app"
LAYERS = ("domain", "application", "infrastructure", "presentation")
COMPOSITION_ROOTS = {"app.main", "app.presentation.mcp.__main__", "app.container"}
PURE_THIRD_PARTY = {"numpy"}

# (importing module, imported module) pairs tolerated while a migration is in flight; must stay empty.
ALLOWED_VIOLATIONS: set[tuple[str, str]] = set()


def _module_name(path: Path) -> str:
    rel = path.relative_to(APP_DIR.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports(path: Path, module: str) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    package = module if path.name == "__init__.py" else module.rpartition(".")[0]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package.split(".")
                base = base[: len(base) - (node.level - 1)] if node.level > 1 else base
                prefix = ".".join(base)
                target = f"{prefix}.{node.module}" if node.module else prefix
            else:
                target = node.module or ""
            found.add(target)
            # `from app.application import dtos` imports the submodule app.application.dtos
            for alias in node.names:
                candidate = f"{target}.{alias.name}"
                if (APP_DIR.parent / Path(*candidate.split("."))).with_suffix(".py").exists() or (
                    APP_DIR.parent / Path(*candidate.split("."))
                ).is_dir():
                    found.add(candidate)
    return found


def _layer(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[0] == "app" and parts[1] in LAYERS else None


def _is_within(imported: str, package: str) -> bool:
    return imported == package or imported.startswith(package + ".")


def _violation(module: str, imported: str) -> str | None:
    layer = _layer(module)
    if layer is None or module in COMPOSITION_ROOTS:
        return None
    top = imported.split(".")[0]
    if layer in ("domain", "application"):
        allowed_app = ("app.domain",) if layer == "domain" else ("app.domain", "app.application")
        if top == "app":
            return None if any(_is_within(imported, p) for p in allowed_app) else f"{layer} may not import {imported}"
        if top in sys.stdlib_module_names or top in PURE_THIRD_PARTY:
            return None
        return f"{layer} may not depend on third-party package {top}"
    if layer == "infrastructure" and _is_within(imported, "app.presentation"):
        return "infrastructure may not import presentation"
    if layer == "presentation" and _is_within(imported, "app.infrastructure"):
        return "presentation may not import infrastructure (wire it in a composition root)"
    return None


def _all_violations() -> set[tuple[str, str, str]]:
    found = set()
    for path in APP_DIR.rglob("*.py"):
        module = _module_name(path)
        for imported in _imports(path, module):
            reason = _violation(module, imported)
            if reason:
                found.add((module, imported, reason))
    return found


def test_layers_respect_the_dependency_rule():
    violations = {(m, i, r) for m, i, r in _all_violations() if (m, i) not in ALLOWED_VIOLATIONS}
    assert not violations, "\n".join(f"{m} -> {i}: {r}" for m, i, r in sorted(violations))


def test_nothing_is_exempt_from_the_dependency_rule():
    assert not ALLOWED_VIOLATIONS, sorted(ALLOWED_VIOLATIONS)


def test_every_module_belongs_to_a_layer_or_is_a_composition_root():
    stray = sorted(
        module
        for module in (_module_name(path) for path in APP_DIR.rglob("*.py"))
        if module != "app" and _layer(module) is None and module not in COMPOSITION_ROOTS
    )
    assert not stray, f"modules outside the layer packages: {stray}"


def test_every_layer_holds_code():
    for layer in LAYERS:
        assert any((APP_DIR / layer).rglob("*.py")), f"app/{layer} is empty"


def test_rule_checker_catches_violations():
    assert _violation("app.domain.entities.topic", "sqlalchemy.orm")
    assert _violation("app.domain.entities.topic", "app.infrastructure.persistence.database")
    assert _violation("app.domain.entities.topic", "app.application.dtos")
    assert _violation("app.application.use_cases.topics", "pydantic")
    assert _violation("app.application.use_cases.topics", "app.infrastructure.persistence.database")
    assert _violation("app.application.use_cases.topics", "app.presentation.api.schemas")
    assert _violation("app.infrastructure.persistence.database", "app.presentation.api.schemas")
    assert _violation("app.presentation.api.routers.topics", "app.infrastructure.persistence.database")
    assert _violation("app.presentation.mcp.service", "app.infrastructure.persistence.database")
    assert _violation("app.main", "app.infrastructure.persistence.database") is None
    assert _violation("app.presentation.mcp.__main__", "app.infrastructure.persistence.database") is None
    assert _violation("app.domain.services.similarity", "numpy") is None
    assert _violation("app.application.use_cases.topics", "app.domain.entities.topic") is None
    assert _violation("app.presentation.api.routers.topics", "app.application.dtos") is None
