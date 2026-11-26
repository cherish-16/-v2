"""规范守护：改了代码却没改规范 → 失败。

检查范围：与给定基准（默认 HEAD~1）比较，若 ``src/**/*.py`` 有改动
但 ``specs/**`` 与 ``docs/`` 均无改动，则判定为规范漂移。

退出码：0 无漂移；1 有漂移。
"""

from __future__ import annotations

import argparse
import subprocess
import sys

CODE_PREFIX = "src/"
SPEC_PREFIXES = ("specs/", "docs/")


def changed_files(base: str) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--name-only", base, "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        raise SystemExit(f"git diff failed: {result.stderr.strip()}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    # Windows 控制台默认非 UTF-8，显式设置避免中文输出乱码
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, OSError):
        pass

    parser = argparse.ArgumentParser(description="检查代码改动是否伴随规范改动")
    parser.add_argument("--base", default="HEAD~1", help="比较基准（默认 HEAD~1）")
    args = parser.parse_args(argv)

    files = changed_files(args.base)
    code = [f for f in files if f.startswith(CODE_PREFIX) and f.endswith(".py")]
    specs = [f for f in files if f.startswith(SPEC_PREFIXES)]

    if code and not specs:
        print(f"规范漂移：{len(code)} 个代码文件有改动，但 specs/ 与 docs/ 均未更新：")
        for name in code:
            print(f"  - {name}")
        print("\n请先更新 specs/design.md 或 specs/proposal.md，再提交代码。")
        return 1

    print(f"检查通过：代码改动 {len(code)} 个，规范/文档改动 {len(specs)} 个。")
    return 0


if __name__ == "__main__":
    sys.exit(main())