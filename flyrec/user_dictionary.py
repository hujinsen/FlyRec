"""用户词典替换。

用途：将用户维护的专有名词/固定写法在送入模型前做字符串替换。

设计：
- 长词优先：避免短词抢占长词的一部分。
- 返回命中明细：便于在日志中审计替换是否符合预期。
"""

from __future__ import annotations

from typing import Dict, List, Tuple


DictionaryHits = List[Tuple[str, str, int]]


def apply_user_dictionary(text: str, mapping: Dict[str, str] | None) -> tuple[str, DictionaryHits]:
    """按用户词典进行替换。

    参数：
    - text: 原始文本
    - mapping: {src: dst}

    返回：
    - new_text: 替换后的文本
    - hits: [(src, dst, count)] 仅包含发生实际替换的条目
    """

    if not mapping:
        return text, []

    hits: DictionaryHits = []

    for src in sorted(mapping.keys(), key=len, reverse=True):
        if not src:
            continue
        dst = mapping.get(src, "")
        try:
            count = text.count(src)
            if count > 0:
                text = text.replace(src, dst)
                hits.append((src, dst, count))
        except Exception:
            continue

    return text, hits
