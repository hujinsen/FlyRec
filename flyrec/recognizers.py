"""识别器封装（连接 ASR + LLM + GUI）。

目标：
- 将“录音结果 -> 提示词选择 -> LLM 调用 -> 自动粘贴 -> GUI 回调”从 GUI 文件中抽离。
- 保持旧接口：对外暴露 start_session/stop_session，便于 GUI 最小改动。

说明：
- `CustomRecognizer`：基于 legacy 的 `legacy_hold_to_talk.HoldToTalkRecognizer`（兼容保留）。
- `ServiceRecognizer`：基于统一 service 层（推荐）。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol

from flyrec.user_dictionary import apply_user_dictionary

try:
    from legacy_hold_to_talk import HoldToTalkRecognizer as _HoldToTalkRecognizer
except Exception:
    _HoldToTalkRecognizer = object  # type: ignore[assignment]


class _VarLike(Protocol):
    def get(self) -> Any: ...


class _RootLike(Protocol):
    def after(self, delay_ms: int, callback) -> Any: ...


class GUIProtocol(Protocol):
    root: _RootLike
    runtime: Any

    language_mode_var: _VarLike
    auto_paste_var: _VarLike

    prompts: Dict[str, Any]
    builtin_scene_prompts: Dict[str, str]
    builtin_default_prompt: str

    user_dict: Dict[str, str]
    last_recording_duration: int

    def get_smart_template(self) -> str: ...

    def on_recognition_complete(self, original_text: str, formatted_text: str, word_count: int) -> Any: ...


_LANG_EN = {"英语", "外语", "英文", "English"}


def _english_enforcer() -> str:
    return (
        "IMPORTANT: You must output ONLY English text.\n"
        "Task: Understand the user's spoken intent (may be Chinese) and produce a concise, natural English sentence or short paragraph conveying exactly the same meaning.\n"
        "Rules:\n"
        "1. Do NOT include ANY Chinese characters.\n"
        "2. Preserve key factual details (names, numbers, times).\n"
        "3. Do NOT add explanations, apologies, or meta commentary.\n"
        "4. If the input is already English, just lightly polish it.\n"
        "5. Output only the final English text, no labels or prefixes."
    )


def _select_system_prompt(gui_app: GUIProtocol, scene: str) -> str:
    """按优先级选择 system prompt：场景 > 默认 > 内置场景 > 内置默认。"""

    prompts_cfg = getattr(gui_app, "prompts", {}) or {}
    scenes_cfg = prompts_cfg.get("scenes", {}) if isinstance(prompts_cfg, dict) else {}
    user_default = prompts_cfg.get("default") if isinstance(prompts_cfg, dict) else None

    if scene in scenes_cfg and scenes_cfg.get(scene):
        return str(scenes_cfg.get(scene))

    if user_default:
        return str(user_default)

    builtin_scenes = getattr(gui_app, "builtin_scene_prompts", {}) or {}
    if scene in builtin_scenes and builtin_scenes.get(scene):
        return str(builtin_scenes.get(scene))

    return str(getattr(gui_app, "builtin_default_prompt", ""))


def _maybe_force_english(system_prompt: str, lang_mode: str) -> str:
    if lang_mode in _LANG_EN:
        return system_prompt.strip() + "\n" + _english_enforcer()
    return system_prompt


def _count_words_like_gui(text: str) -> int:
    return len([c for c in text if c.isalnum()])


def _auto_paste_if_enabled(gui_app: GUIProtocol, text: str) -> None:
    try:
        if not getattr(gui_app, "auto_paste_var", None) or not gui_app.auto_paste_var.get():
            return
        import time

        import pyautogui  # type: ignore
        import pyperclip  # type: ignore

        pyperclip.copy(text)
        time.sleep(0.1)
        pyautogui.hotkey("ctrl", "v")
    except Exception as e:
        print(f"自动粘贴失败: {e}")


def _llm_generate_with_english_retry(
    llm: Any,
    system_prompt: str,
    user_text: str,
    lang_mode: str,
) -> str:
    """调用 LLM 并在英文模式下做一次“含中文则重试”的降级。

    返回最终 content；失败时回退到 user_text。
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    try:
        resp = llm.generate(messages)
        content = (
            resp.get("output", {})
            .get("choices", [])[0]
            .get("message", {})
            .get("content", "")
            if resp
            else ""
        )
    except Exception as e:
        print(f"格式化失败: {e}")
        return user_text

    if lang_mode not in _LANG_EN:
        return content or user_text

    # 英文模式：若仍含中文字符，重试一次
    try:
        import re

        if content and re.search(r"[\u4e00-\u9fff]", content):
            retry_messages = [
                {
                    "role": "system",
                    "content": (
                        "You previously returned non-English content. Now STRICTLY output ONLY English. "
                        "Translate and refine the user's intent. No Chinese characters. No explanations."
                    ),
                },
                {"role": "user", "content": user_text},
            ]
            retry_resp = llm.generate(retry_messages)
            retry_content = (
                retry_resp.get("output", {})
                .get("choices", [])[0]
                .get("message", {})
                .get("content", "")
                if retry_resp
                else ""
            )
            if retry_content and not re.search(r"[\u4e00-\u9fff]", retry_content):
                return retry_content
    except Exception as e:
        print(f"英文回退重试失败: {e}")

    return content or user_text


class CustomRecognizer(_HoldToTalkRecognizer):
    """兼容识别器：继承 legacy_hold_to_talk.HoldToTalkRecognizer 并接入 GUI 回调。

    注意：必须重写 stop_session，避免 legacy 实现里自带的粘贴/打印副作用重复触发。
    """

    def __init__(self, gui_app: GUIProtocol):
        if _HoldToTalkRecognizer is object:
            raise RuntimeError(
                "legacy 识别器依赖不可用：请安装 legacy_hold_to_talk.py 所需依赖（dashscope/pyaudio 等）"
            )
        super().__init__()  # type: ignore[misc]
        self.gui_app = gui_app
        self.start_time: Optional[float] = None

    def start_session(self) -> None:
        import time

        self.start_time = time.time()
        super().start_session()  # type: ignore[misc]

    def stop_session(self) -> None:
        # 复刻 flyrec_gui.py 里的逻辑：清理资源 + LLM 调用 + 自动粘贴 + GUI 回调
        if not getattr(self, "_running", False):
            return

        import time

        recording_duration = int(time.time() - self.start_time) if self.start_time else 0
        self.gui_app.last_recording_duration = recording_duration

        print("Stop recognition session")
        self._running = False  # type: ignore[attr-defined]

        if getattr(self, "_audio_thread", None) is not None:
            try:
                self._audio_thread.join()  # type: ignore[attr-defined]
            except Exception:
                pass

        if getattr(self, "_recognition", None) is not None:
            try:
                self._recognition.stop()  # type: ignore[attr-defined]
            except Exception:
                pass

        # 清理资源
        if getattr(self, "_stream", None) is not None:
            try:
                self._stream.stop_stream()  # type: ignore[attr-defined]
                self._stream.close()  # type: ignore[attr-defined]
            except Exception:
                pass

        if getattr(self, "_mic", None) is not None:
            try:
                self._mic.terminate()  # type: ignore[attr-defined]
            except Exception:
                pass

        self._stream = None  # type: ignore[attr-defined]
        self._mic = None  # type: ignore[attr-defined]
        self._recognition = None  # type: ignore[attr-defined]
        self._audio_thread = None  # type: ignore[attr-defined]
        self._callback = None  # type: ignore[attr-defined]

        # 处理结果
        results = []
        try:
            with self._results_lock:  # type: ignore[attr-defined]
                results = list(getattr(self, "_results", []))
        except Exception:
            results = list(getattr(self, "_results", []))

        if not results:
            print("No final recognition result.")
            self.gui_app.root.after(0, lambda: self.gui_app.on_recognition_complete("", "", 0))
            return

        final_text = " ".join(results)
        print("Final recognition result:\n" + final_text)

        scene = self.gui_app.get_smart_template()
        lang_mode = str(self.gui_app.language_mode_var.get())
        print(f"当前语言模式: {lang_mode}, 场景: {scene}")

        processed_for_model = final_text
        try:
            if hasattr(self.gui_app, "user_dict") and isinstance(self.gui_app.user_dict, dict):
                processed_for_model, hits = apply_user_dictionary(processed_for_model, self.gui_app.user_dict)
                if hits:
                    hits_str = "; ".join([f"{s}->{d}({c}处)" for s, d, c in hits])
                    print(f"用户词典替换明细: {hits_str}")
        except Exception as e:
            print(f"应用用户词典失败: {e}")

        system_prompt = _select_system_prompt(self.gui_app, scene)
        system_prompt = _maybe_force_english(system_prompt, lang_mode)

        try:
            if getattr(self.gui_app, "runtime", None):
                llm = self.gui_app.runtime.llm
            else:
                llm = getattr(self, "_format_text")  # type: ignore[attr-defined]

            formatted_content = _llm_generate_with_english_retry(
                llm, system_prompt, processed_for_model, lang_mode
            )
        except Exception as e:
            print(f"格式化文本失败: {e}")
            formatted_content = final_text

        _auto_paste_if_enabled(self.gui_app, formatted_content)

        word_count = _count_words_like_gui(final_text)
        self.gui_app.root.after(
            0,
            lambda: self.gui_app.on_recognition_complete(final_text, formatted_content, word_count),
        )

        # 清空结果
        try:
            setattr(self, "_results", [])
        except Exception:
            pass


class ServiceRecognizer:
    """推荐识别器：基于 services.FlyRecRuntime 的 ASR + LLM。"""

    def __init__(self, gui_app: GUIProtocol):
        if not getattr(gui_app, "runtime", None):
            raise RuntimeError("runtime 未初始化")

        runtime = gui_app.runtime
        if runtime is None or not hasattr(runtime, "asr") or not hasattr(runtime, "llm"):
            raise RuntimeError("runtime 不完整，缺少 asr/llm")

        self.gui_app = gui_app
        self.asr = runtime.asr
        self.llm = runtime.llm
        self.start_time: Optional[float] = None

        try:
            self.asr.on_partial(self._on_partial)
        except Exception:
            pass

    def _on_partial(self, piece: str) -> None:
        # 预留：可在 GUI 中展示实时 partial 文本
        return

    def start_session(self) -> None:
        import time

        if self.asr.is_running():
            return
        self.start_time = time.time()
        self.asr.start()

    def stop_session(self) -> None:
        if not self.asr.is_running():
            return

        result = self.asr.stop()
        final_text = str(result.get("text", "") or "")
        if not final_text:
            self.gui_app.root.after(0, lambda: self.gui_app.on_recognition_complete("", "", 0))
            return

        duration = float(result.get("duration") or 0)
        self.gui_app.last_recording_duration = int(duration)

        scene = self.gui_app.get_smart_template()
        lang_mode = str(self.gui_app.language_mode_var.get())

        processed_for_model = final_text
        try:
            if hasattr(self.gui_app, "user_dict") and isinstance(self.gui_app.user_dict, dict):
                processed_for_model, hits = apply_user_dictionary(processed_for_model, self.gui_app.user_dict)
                if hits:
                    hits_str = "; ".join([f"{s}->{d}({c})" for s, d, c in hits])
                    print(f"用户词典替换明细: {hits_str}")
        except Exception as e:
            print(f"用户词典应用失败: {e}")

        system_prompt = _select_system_prompt(self.gui_app, scene)
        system_prompt = _maybe_force_english(system_prompt, lang_mode)

        formatted_content = _llm_generate_with_english_retry(
            self.llm, system_prompt, processed_for_model, lang_mode
        )

        _auto_paste_if_enabled(self.gui_app, formatted_content)

        word_count = _count_words_like_gui(final_text)
        self.gui_app.root.after(
            0,
            lambda: self.gui_app.on_recognition_complete(final_text, formatted_content, word_count),
        )

    def is_running(self) -> bool:
        return bool(self.asr.is_running())
