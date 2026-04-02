"""ファイル編集後に自動でフォーマッターを実行する Hook"""

import json
import subprocess
import sys
from pathlib import Path


def format_python(file_path: str) -> None:
    """Ruff でフォーマット"""
    subprocess.run(
        ["uv", "run", "ruff", "format", "-q", file_path],
        capture_output=True,
        timeout=30,
    )
    subprocess.run(
        ["uv", "run", "ruff", "check", "-q", "--fix", file_path],
        capture_output=True,
        timeout=30,
    )


def format_javascript(file_path: str) -> None:
    """Prettier でフォーマット"""
    subprocess.run(
        ["npx", "prettier", "--log-level", "error", "--write", file_path],
        capture_output=True,
        timeout=30,
    )


def main():
    # Claude CodeからHooksに送られるコンテキスト情報を受け取る
    # c.f. WindowsはUTF-8形式の標準入力に対応していないため、バイナリとして読み込む必要がある
    stdin = sys.stdin.buffer.read().strip()
    input_data = json.loads(stdin)

    # Write/Editツールが呼ばれたときのみ実行
    tool_name = input_data.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        return

    # 編集されたファイルのパスを取得
    file_path = input_data.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return

    path = Path(file_path)

    try:
        if path.suffix == ".py":
            format_python(file_path)
        elif path.suffix in (".js", ".ts", ".jsx", ".tsx", ".json"):
            format_javascript(file_path)

        print(f"Formatted: {file_path}")
    except Exception:
        # Do nothing on error
        pass


if __name__ == "__main__":
    main()
