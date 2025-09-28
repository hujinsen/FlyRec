#!/usr/bin/env python3
# -*- coding: utf-8 -*-

# 实时录音+实时出字 MVP
# 依赖：pip install pyaudio aliyun-python-sdk-core dashscope websocket-client

import pyaudio, threading, json, dashscope
from dashscope.audio.asr import Recognition
from collections import deque

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
    p = pyaudio.PyAudio()
    stream = p.open(format=FORMAT, channels=CHANNELS, rate=SAMPLE_RATE,
                    input=True, frames_per_buffer=CHUNK)
    while True:
        data = stream.read(CHUNK, exception_on_overflow=False)
        audio_q.append(data)

def asr_thread():
    """后台线程：流式识别，把结果塞进 result_q"""
    # 阿里云免费额度：每月 2 小时
    dashscope.api_key = 'YOUR_API_KEY'      # ← 换成自己的
    recognizer = Recognition(model='paraformer-realtime-v2',
                             format='pcm',
                             sample_rate=SAMPLE_RATE)
    # 构造一个「生成器」给 SDK
    def gen():
        while True:
            if audio_q:
                yield audio_q.popleft()
            else:
                import time
                time.sleep(0.01)

    for rsp in recognizer.stream_call(gen):
        if rsp.status_code == 200:
            sentence = rsp.output['sentence']
            if sentence['end_time']:          # 整句
                result_q.append(('fix', sentence['text']))
            else:                              # 半句
                result_q.append(('live', sentence['text']))
        else:
            print('ASR error:', rsp.message)

########################################
# 极简 UI（tkinter，单 Text 一直追加）
import tkinter as tk
def ui_loop():
    root = tk.Tk()
    root.title('飞记-实时')
    text = tk.Text(root, height=8, width=50, font=('微软雅黑', 14))
    text.pack()
    live_start = '1.0'
    def refresh():
        while result_q:
            flag, txt = result_q.popleft()
            if flag == 'live':          # 半句：原地覆盖
                text.delete(live_start, 'end')
                text.insert(live_start, txt)
            else:                       # 整句：换行
                text.insert('end', '\n'+txt)
                live_start = text.index('end')      # 更新半句插入点
        text.see('end')
        root.after(100, refresh)
    refresh()
    root.mainloop()

########################################
# 启动
if __name__ == '__main__':
    threading.Thread(target=audio_capture, daemon=True).start()
    # threading.Thread(target=asr_thread,    daemon=True).start()
    ui_loop()


