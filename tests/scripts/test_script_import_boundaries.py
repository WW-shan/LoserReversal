from __future__ import annotations

import ast
from pathlib import Path


def test_no_underscore_prefix_cross_script_imports():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    script_stems = {script.stem for script in scripts_dir.glob("*.py") if script.name != "__init__.py"}
    violations: list[str] = []

    for script in sorted(scripts_dir.glob("*.py")):
        if script.name == "__init__.py":
            continue
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue

            module_parts = node.module.split(".")
            imported_script = module_parts[1] if module_parts[0] == "scripts" else module_parts[0]
            if imported_script not in script_stems or imported_script == script.stem:
                continue

            for alias in node.names:
                if alias.name.startswith("_"):
                    violations.append(f"{script.name}: {node.module}.{alias.name}")

    assert violations == []
