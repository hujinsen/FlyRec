#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 实时录音+实时出字 MVP
# 依赖：pip install pyaudio aliyun-python-sdk-core dashscope websocket-client

import pyaudio, threading, json, dashscope
from dashscope.audio.asr import Recognition, RecognitionCallback, RecognitionResult
from collections import deque
import time
########################################
# 0 参数
SAMPLE_RATE   = 16000
CHUNK         = 1024          # 0.064 s
FORMAT        = pyaudio.paInt16
CHANNELS      = 1
QUEUE_MAXLEN  = 300           # 最多缓存 19 s 音频
########################################

audio_q = deque(maxlen=QUEUE_MAXLEN)   # 线程安全「双端队列」
result_q = deque()                     # 给 UI 线程的文本队列

def audio_capture():
    """后台线程：不断往 audio_q 塞 PCM 数据"""
    # 该函数保留为备用（不直接用于 RecognitionCallback 模式）。
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
                    input=True, frames_per_buffer=CHUNK)
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        audio_q.append(data)


class ASRCallback(RecognitionCallback):
    """把识别事件转为放入 result_q 的任务"""
    def on_open(self) -> None:
        # 当识别会话打开时，没必要做额外处理。
        print('RecognitionCallback open.')

    def on_close(self) -> None:
        print('RecognitionCallback close.')

    def on_event(self, result: RecognitionResult) -> None:
        # result.get_sentence() 返回类似 dict 的结构或对象，尽量兼容 demo.py 的用法
        try:
            sentence = result.get_sentence()
        except Exception:
            # 回退到直接使用 result.sentence
            sentence = getattr(result, 'sentence', None)
        if not sentence:
            return
        # 兼容不同 SDK 返回结构
        text = sentence.get('text') if isinstance(sentence, dict) else getattr(sentence, 'text', str(sentence))
        end_time = sentence.get('end_time') if isinstance(sentence, dict) else getattr(sentence, 'end_time', None)
        if end_time:
            result_q.append(('fix', text))
        else:
            result_q.append(('live', text))

def asr_thread():
    """使用 Recognition + 回调进行识别，会在回调中把结果放入 result_q"""
    # 请把下面的 api_key 换成你自己的密钥，或事先通过环境变量配置
    dashscope.api_key = 'sk-2d627fbbc4fa491db207c632a77f2852'
    callback = ASRCallback()
    recognizer = Recognition(model='paraformer-realtime-v2',
                             format='pcm',
                             sample_rate=SAMPLE_RATE,
                             callback=callback)

    # 启动识别，会触发 on_open
    recognizer.start()

    # 在本线程中打开本地麦克风，读取帧并发送给 recognizer
    mic = pyaudio.PyAudio()
    stream = mic.open(format=FORMAT,
                      channels=CHANNELS,
                      rate=SAMPLE_RATE,
                      input=True,
                      frames_per_buffer=CHUNK)
    try:
        while True:
            data = stream.read(CHUNK, exception_on_overflow=False)
            # 直接发送原始 PCM 帧
            recognizer.send_audio_frame(data)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            recognizer.stop()
        except Exception:
            pass
        stream.stop_stream()
        stream.close()
        mic.terminate()

########################################
# 极简 UI（tkinter，单 Text 一直追加）
import tkinter as tk
def ui_loop():
    root = tk.Tk()
    root.title('飞记-实时')
    text = tk.Text(root, height=8, width=50, font=('微软雅黑', 14))
    text.pack()
    # 使用可变容器保存 live_start 与 current_live，避免闭包中赋值导致的 UnboundLocalError
    live_start = ['1.0']
    current_live = ['']  # 当前半句文本（字符串），用于在收到 'fix' 时替换而不是重复追加
    def refresh():
        while result_q:
            flag, txt = result_q.popleft()
            if flag == 'live':          # 半句：增量更新（只插入/删除差异部分）
                # 当前 UI 中 live 部分的文本
                try:
                    curr = text.get(live_start[0], 'end-1c')
                except Exception:
                    curr = ''
                new = txt or ''
                # 保存当前 live 文本状态
                current_live[0] = new
                # 计算最长公共前缀（按字符）
                prefix_len = 0
                max_pref = min(len(curr), len(new))
                while prefix_len < max_pref and curr[prefix_len] == new[prefix_len]:
                    prefix_len += 1
                # 如果当前比公共前缀长，删除多余尾部
                if prefix_len < len(curr):
                    # 删除从 live_start + prefix_len 到 end 的多余字符
                    text.delete(f"{live_start[0]}+{prefix_len}c", 'end')
                # 如果新文本比公共前缀长，插入差异部分
                if prefix_len < len(new):
                    to_insert = new[prefix_len:]
                    text.insert('end', to_insert)
            else:                       # 整句：换行
                # 收到最终句时，先删除当前的 live 部分（若存在），再以整句形式插入，避免重复
                # 删除 live 部分
                try:
                    # 删除 live_start 到 end（移除半句）
                    text.delete(live_start[0], 'end')
                except Exception:
                    pass
                # 如果文本剩余部分非空且不以换行结束，先插入换行以分隔句子
                before = text.get('1.0', 'end-1c')
                if before.strip():
                    # 如果最后一行已经等于要插入的句子（避免重复），跳过插入
                    last_line = before.splitlines()[-1] if before.splitlines() else ''
                    if last_line.strip() == (txt or '').strip():
                        # 已存在相同句子，清空 current_live 并更新插入点
                        current_live[0] = ''
                        live_start[0] = text.index('end')
                    else:
                        text.insert('end', '\n' + (txt or ''))
                        # 更新半句插入点到当前文本末尾
                        live_start[0] = text.index('end')
                        current_live[0] = ''
                else:
                    # 文本为空，直接插入最终句
                    text.insert('end', (txt or ''))
                    live_start[0] = text.index('end')
                    current_live[0] = ''
        text.see('end')
        root.after(100, refresh)
    refresh()
    root.mainloop()

########################################
# 启动
if __name__ == '__main__':
    # 可选的本地音频采集线程（未直接用于 Recognition 回调方案），保留以备调试
    # threading.Thread(target=audio_capture, daemon=True).start()
    # 启动 ASR 后台线程（会打开麦克风并把音频帧送到 recognizer）
    threading.Thread(target=asr_thread, daemon=True).start()
    ui_loop()


