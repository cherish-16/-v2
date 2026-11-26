"""分层依赖检查：下层模块不得反向依赖编排层，SQL 只能出现在存储层。"""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "daily_report"
LAYERED = ("collectors", "generation", "publishers", "render", "storage", "net")
FORBIDDEN = "orchestration"


def test_lower_layers_do_not_import_orchestration():
    offenders = []
    for name in LAYERED:
        target = SRC / name
        paths = [target] if target.is_file() else list(target.rglob("*.py"))
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and FORBIDDEN in node.module:
                    offenders.append(f"{path.name}: {node.module}")
                elif isinstance(node, ast.Import):
                    offenders += [
                        f"{path.name}: {alias.name}"
                        for alias in node.names
                        if FORBIDDEN in alias.name
                    ]
    assert offenders == []


def test_sql_only_in_storage_layer():
    offenders = []
    for path in SRC.rglob("*.py"):
        if path.parent.name == "storage":
            continue
        text = path.read_text(encoding="utf-8").upper()
        if "INSERT INTO" in text or ("SELECT " in text and " FROM " in text):
            offenders.append(str(path))
    assert offenders == []