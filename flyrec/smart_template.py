"""智能模板/场景切换（Windows）。

职责：
- 读取前台窗口的进程名/标题（依赖 psutil + pywin32）。
- 根据规则给出推荐“场景”（聊天/邮件/代码/文本）。

说明：
- 缺少依赖时应优雅降级：调用方可回退到用户手动选择的场景。
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple


try:
    import psutil  # type: ignore
    import win32gui  # type: ignore
    import win32process  # type: ignore

    SMART_TEMPLATE_AVAILABLE = True
except Exception:
    SMART_TEMPLATE_AVAILABLE = False


DEFAULT_APP_SCENE_MAPPING: Dict[str, str] = {
    # 聊天应用
    "wechat.exe": "聊天",
    "qq.exe": "聊天",
    "qqscm.exe": "聊天",
    "dingtalk.exe": "聊天",
    "teams.exe": "聊天",
    "slack.exe": "聊天",
    "telegram.exe": "聊天",
    "discord.exe": "聊天",

    # 邮件应用
    "outlook.exe": "邮件",
    "thunderbird.exe": "邮件",
    "foxmail.exe": "邮件",
    "mailmaster.exe": "邮件",

    # 代码编辑器
    "code.exe": "代码",
    "devenv.exe": "代码",
    "pycharm64.exe": "代码",
    "idea64.exe": "代码",
    "notepad++.exe": "代码",
    "sublime_text.exe": "代码",
    "atom.exe": "代码",
    "webstorm64.exe": "代码",
    "phpstorm64.exe": "代码",
    "codebuddy.exe": "代码",

    # 常见默认
    "notepad.exe": "默认",
    "wordpad.exe": "默认",
    "winword.exe": "默认",
    "excel.exe": "默认",
    "powerpnt.exe": "默认",
}


def get_active_window_process() -> Tuple[Optional[str], Optional[str]]:
    """获取前台窗口的 (process_name, window_title)。

    返回：
    - process_name: 小写进程名（如 code.exe），失败为 None
    - window_title: 窗口标题，失败为 None
    """

    if not SMART_TEMPLATE_AVAILABLE:
        return None, None

    try:
        hwnd = win32gui.GetForegroundWindow()
        if hwnd == 0:
            return None, None

        window_title = win32gui.GetWindowText(hwnd)
        _, process_id = win32process.GetWindowThreadProcessId(hwnd)

        try:
            process = psutil.Process(process_id)
            return process.name().lower(), window_title
        except Exception:
            return None, window_title

    except Exception:
        return None, None


def suggest_scene(
    process_name: Optional[str],
    window_title: Optional[str],
    mapping: Dict[str, str] | None = None,
    fallback: str = "文本",
) -> str:
    """根据 (process_name, window_title) 推荐场景。

    规则：
    - 优先按进程名映射。
    - 再按标题关键词兜底。
    - 映射中的 "默认" 会转换为 "文本"。
    """

    mapping = mapping or DEFAULT_APP_SCENE_MAPPING

    if process_name:
        scene = mapping.get(process_name)
        if scene:
            return "文本" if scene == "默认" else scene

    if window_title:
        title = window_title.lower()
        if any(k in title for k in ["微信", "wechat", "qq", "钉钉"]):
            return "聊天"
        if any(k in title for k in ["邮件", "mail", "outlook", "邮箱"]):
            return "邮件"
        if any(k in title for k in ["code", "visual studio", "pycharm", "idea"]):
            return "代码"

    return fallback
