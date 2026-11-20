# SPDX-FileCopyrightText: 2026 DX Band
# SPDX-License-Identifier: GPL-3.0-only

import ast
from pathlib import Path


def test_core_modules_do_not_import_desktop_ui() -> None:
    source_root = Path("src/dxband")
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        if relative.parts[0] == "ui" or relative == Path("app.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.ImportFrom):
                module = node.module or ""
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("dxband.ui"):
                        violations.append(f"{relative}:{node.lineno}: {alias.name}")
                continue
            if module.startswith("dxband.ui"):
                violations.append(f"{relative}:{node.lineno}: {module}")

    assert violations == []
