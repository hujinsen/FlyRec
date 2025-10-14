"""Service 层抽象：统一封装 ASR 与 LLM 调用，便于后续替换/扩展。

设计目标：
- GUI 等上层仅依赖抽象接口，不直接感知具体后端 (DashScope / 离线 Whisper / 其它)。
- 支持最小配置化：config.json 可指定 backend 及模型。
- 便于注入 mock / 离线占位以做本地测试。

接口概览：
- ASRService
  * start() -> None: 开始采集/会话
  * stop() -> ASRResult: 结束并返回最终文本（或中间分段列表）
  * is_running() -> bool
  * shutdown() -> None
  * on_partial(callback: Callable[[str], None])  # 可选：流式部分结果

- LLMService
  * generate(messages: list[dict], **kwargs) -> dict  # 原始结构（与 text_format.TextGenerator 保持兼容）
  * simple_refine(system_prompt: str, user_text: str) -> str  # 便捷封装，返回最终 content

占位离线实现：
- 返回简单回声/伪处理，方便无网络时验证 UI 流程。
"""
from __future__ import annotations
from typing import Callable, List, Dict, Any, Optional, Protocol
import threading
import time
import os

# ===================== 抽象协议 =====================
class ASRService(Protocol):
    def start(self) -> None: ...
    def stop(self) -> "ASRResult": ...
    def is_running(self) -> bool: ...
    def shutdown(self) -> None: ...
    def on_partial(self, callback: Callable[[str], None]) -> None: ...

class LLMService(Protocol):
    def generate(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]: ...
    def simple_refine(self, system_prompt: str, user_text: str, **kwargs) -> str: ...

class ASRResult(Dict[str, Any]):
    """键约定：
    - text: 最终整合文本(str)
    - segments: List[str] 原始分段
    - duration: float 录音时长秒
    - raw: Any 底层返回对象（可选）
    """
    pass

# ===================== DashScope 实现 =====================
try:
    import dashscope  # type: ignore
    from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult  # type: ignore
    import pyaudio  # type: ignore
    DASH_SCOPE_AVAILABLE = True
except Exception:
    DASH_SCOPE_AVAILABLE = False

SAMPLE_RATE = 16000
CHANNELS = 1
FORMAT_PCM = 'pcm'
BLOCK_SIZE = 3200

class DashScopeASR(ASRService):
    def __init__(self, model: str = 'fun-asr-realtime', api_key: Optional[str] = None):
        if not DASH_SCOPE_AVAILABLE:
            raise RuntimeError("DashScope 依赖不可用，无法使用 DashScopeASR")
        dashscope.api_key = api_key or os.getenv('DASHSCOPE_API_KEY')
        if not dashscope.api_key:
            raise RuntimeError("缺少 DASHSCOPE_API_KEY")
        self.model = model
        self._mic = None
        self._stream = None
        self._recognition: Optional[Recognition] = None
        self._audio_thread: Optional[threading.Thread] = None
        self._callback: Optional[RecognitionCallback] = None
        self._running = False
        self._results: List[str] = []
        self._results_lock = threading.Lock()
        self._partial_cb: Optional[Callable[[str], None]] = None
        self._start_time = 0.0

    # ---- 内部 Callback ----
    class _CB(RecognitionCallback):
        def __init__(self, outer: 'DashScopeASR'):
            super().__init__()
            self.o = outer
        def on_open(self) -> None:
            import pyaudio  # 延迟导入
            mic = pyaudio.PyAudio()
            stream = mic.open(format=pyaudio.paInt16, channels=CHANNELS, rate=SAMPLE_RATE, input=True)
            self.o._mic = mic  # type: ignore[assignment]
            self.o._stream = stream  # type: ignore[assignment]
        def on_close(self) -> None:
            if self.o._stream:
                try: self.o._stream.stop_stream(); self.o._stream.close()
                except Exception: pass
            if self.o._mic:
                try: self.o._mic.terminate()
                except Exception: pass
            self.o._stream = None; self.o._mic = None
        def on_error(self, message) -> None:
            print("ASR error:", getattr(message, 'message', message))
            self.o._running = False
        def on_event(self, result: RecognitionResult) -> None:
            try:
                sentence = result.get_sentence()
                if sentence is None: return
                text = None
                if isinstance(sentence, dict) and 'text' in sentence:
                    text = sentence['text']
                elif isinstance(sentence, list):
                    for item in sentence:
                        if isinstance(item, dict) and 'text' in item:
                            text = item['text']; break
                if text is None: return
                if isinstance(sentence, dict) and RecognitionResult.is_sentence_end(sentence):
                    with self.o._results_lock:
                        self.o._results.append(text)
                else:
                    if self.o._partial_cb:
                        self.o._partial_cb(text)
            except Exception as e:
                print("ASR on_event exception", e)

    def _audio_loop(self):
        while self._running:
            try:
                if self._stream:
                    data = self._stream.read(BLOCK_SIZE, exception_on_overflow=False)
                    if self._recognition:
                        self._recognition.send_audio_frame(data)
                else:
                    time.sleep(0.01)
            except Exception as e:
                print("ASR read/send error", e)
                if not self._running:
                    break
                time.sleep(0.05)

    # ---- 接口实现 ----
    def start(self) -> None:
        if self._running:
            return
        self._callback = DashScopeASR._CB(self)
        self._recognition = Recognition(model=self.model, format=FORMAT_PCM, sample_rate=SAMPLE_RATE, semantic_punctuation_enabled=False, callback=self._callback)
        self._recognition.start()
        with self._results_lock:
            self._results = []
        self._running = True
        self._start_time = time.time()
        self._audio_thread = threading.Thread(target=self._audio_loop, daemon=True).start()

    def stop(self) -> ASRResult:
        if not self._running:
            return ASRResult(text="", segments=[], duration=0.0)
        self._running = False
        if self._audio_thread and isinstance(self._audio_thread, threading.Thread):
            self._audio_thread = None
        if self._recognition:
            try: self._recognition.stop()
            except Exception: pass
        # gather results
        with self._results_lock:
            segs = list(self._results)
            self._results.clear()
        duration = max(0.0, time.time() - self._start_time)
        text = ' '.join(segs)
        # ensure resources closed via callback's on_close
        return ASRResult(text=text, segments=segs, duration=duration)

    def is_running(self) -> bool:
        return self._running

    def shutdown(self) -> None:
        if self._running:
            self.stop()

    def on_partial(self, callback: Callable[[str], None]) -> None:
        self._partial_cb = callback

# ===================== 占位离线实现 =====================
class DummyASR(ASRService):
    def __init__(self, scripted_result: str = "这是本地占位识别结果", latency: float = 1.2):
        self._running = False
        self._result = scripted_result
        self._latency = latency
        self._t0 = 0.0
        self._partial_cb: Optional[Callable[[str], None]] = None
    def start(self) -> None:
        self._running = True
        self._t0 = time.time()
        # 模拟分段回调
        def _sim():
            parts = [self._result[:max(1, len(self._result)//3)], self._result[max(1, len(self._result)//3):]]
            for p in parts:
                if not self._running: break
                time.sleep(self._latency/len(parts))
                if self._partial_cb:
                    self._partial_cb(p)
        threading.Thread(target=_sim, daemon=True).start()
    def stop(self) -> ASRResult:
        if not self._running:
            return ASRResult(text="", segments=[], duration=0.0)
        self._running = False
        duration = time.time() - self._t0
        return ASRResult(text=self._result, segments=[self._result], duration=duration)
    def is_running(self) -> bool:
        return self._running
    def shutdown(self) -> None:
        self._running = False
    def on_partial(self, callback: Callable[[str], None]) -> None:
        self._partial_cb = callback

# ===================== LLM 实现 =====================
from text_format import TextGenerator  # 复用现有封装

class DashScopeLLM(LLMService):
    def __init__(self, model: str = 'qwen-plus', api_key: Optional[str] = None):
        self._generator = TextGenerator(api_key=api_key, model=model)
    def generate(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        return self._generator.generate(messages, **kwargs)
    def simple_refine(self, system_prompt: str, user_text: str, **kwargs) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ]
        out = self.generate(messages, **kwargs)
        return out.get("output", {}).get("choices", [])[0].get("message", {}).get("content", "")

class DummyLLM(LLMService):
    def generate(self, messages: List[Dict[str, str]], **kwargs) -> Dict[str, Any]:
        # 简单回声结构，仿照真实返回
        combined = "\n".join([m.get('content','') for m in messages])
        content = f"[DummyLLM] {combined[:200]}"[:400]
        return {
            "output": {
                "choices": [
                    {"message": {"role": "assistant", "content": content}}
                ]
            }
        }
    def simple_refine(self, system_prompt: str, user_text: str, **kwargs) -> str:
        return f"[DummyRefine]{user_text}"[:400]

# ===================== 工厂方法 =====================
class ServiceFactory:
    @staticmethod
    def create_asr(kind: str, **kwargs) -> ASRService:
        k = (kind or 'dashscope').lower()
        if k in ('dashscope', 'online'):
            return DashScopeASR(**kwargs)
        if k in ('dummy', 'offline'):
            return DummyASR(**kwargs)
        raise ValueError(f"未知 ASR 后端: {kind}")

    @staticmethod
    def create_llm(kind: str, **kwargs) -> LLMService:
        k = (kind or 'dashscope').lower()
        if k in ('dashscope', 'online'):
            return DashScopeLLM(**kwargs)
        if k in ('dummy', 'offline'):
            return DummyLLM()
        raise ValueError(f"未知 LLM 后端: {kind}")

# ===================== 便捷组装 =====================
class FlyRecRuntime:
    """组合容器：集中管理 ASR + LLM，便于未来扩展状态/缓存。"""
    def __init__(self, asr: ASRService, llm: LLMService):
        self.asr = asr
        self.llm = llm

    @classmethod
    def from_config(cls, cfg: Dict[str, Any] | None) -> 'FlyRecRuntime':
        cfg = cfg or {}
        asr_cfg = cfg.get('asr', {}) if isinstance(cfg, dict) else {}
        llm_cfg = cfg.get('llm', {}) if isinstance(cfg, dict) else {}
        asr_backend = asr_cfg.get('backend', 'dashscope')
        llm_backend = llm_cfg.get('backend', 'dashscope')
        asr_model = asr_cfg.get('model', 'fun-asr-realtime')
        llm_model = llm_cfg.get('model', 'qwen-plus')
        api_key = llm_cfg.get('api_key') or os.getenv('DASHSCOPE_API_KEY')
        asr = ServiceFactory.create_asr(asr_backend, model=asr_model, api_key=api_key)
        llm = ServiceFactory.create_llm(llm_backend, model=llm_model, api_key=api_key)  # type: ignore[arg-type]
        return cls(asr=asr, llm=llm)

__all__ = [
    'ASRService','LLMService','ASRResult','DashScopeASR','DummyASR','DashScopeLLM','DummyLLM','ServiceFactory','FlyRecRuntime'
]
