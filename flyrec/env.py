"""环境变量加载工具。

目标：统一 .env 加载逻辑，避免在多个脚本里复制粘贴。

约定：
- 不在源码中硬编码密钥。
- 默认只尝试加载与调用者脚本同目录下的 `.env`。
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Union


PathLike = Union[str, Path]


def load_dotenv_next_to(file_path: PathLike, filename: str = ".env", override: bool = False) -> bool:
    """从 `file_path` 所在目录尝试加载 .env。

    返回：是否成功加载（找到文件且 load_dotenv 执行成功）。
    """

    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return False

    try:
        base_dir = Path(file_path).resolve().parent
        env_path = base_dir / filename
        if not env_path.exists():
            return False
        load_dotenv(dotenv_path=str(env_path), override=override)
        return True
    except Exception:
        return False
