from __future__ import annotations

import ast
from pathlib import Path


def test_wallet_scripts_do_not_import_private_helpers_across_modules():
    scripts_dir = Path(__file__).resolve().parents[2] / "scripts"
    checked_scripts = [
        scripts_dir / "run_wallet_cluster_backtest.py",
        scripts_dir / "run_wallet_walkforward.py",
    ]
    violations: list[str] = []

    for script in checked_scripts:
        tree = ast.parse(script.read_text(encoding="utf-8"), filename=str(script))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.module is None:
                continue
            if not node.module.endswith(
                ("run_wallet_reverse_backtest", "run_wallet_cluster_backtest")
            ):
                continue
            for alias in node.names:
                if alias.name.startswith("_"):
                    violations.append(f"{script.name}: {node.module}.{alias.name}")

    assert violations == []
