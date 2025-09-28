#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
流式 ASR ttk/Tkinter 演示
特性：
- buffers 按 sentence_id 管理，增量更新
- 最长前缀优先，Levenshtein 做回退对齐
- finished_text (只读) + active Treeview + live preview
- UI 更新通过 root.after 调度，线程安全
"""

import tkinter as tk
from tkinter import ttk
import threading
import time
from typing import List

# ---------- 辅助算法 ----------
def common_prefix_len(a: List[str], b: List[str]) -> int:
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    return i

def levenshtein(a: List[str], b: List[str]) -> int:
    # 返回编辑距离（基于词单元）
    n, m = len(a), len(b)
    if n == 0: return m
    if m == 0: return n
    prev = list(range(m + 1))
    for i in range(1, n + 1):
        cur = [i] + [0] * m
        ai = a[i - 1]
        for j in range(1, m + 1):
            cost = 0 if ai == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
        prev = cur
    return prev[m]

# ---------- UI 类 ----------
class StreamingASRApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("流式 ASR 演示 (ttk + Tk)")

        # 顶层布局
        main = ttk.Frame(root, padding=(8,8))
        main.pack(fill=tk.BOTH, expand=True)

        # 已完成句子（只读）
        lbl_finished = ttk.Label(main, text="已完成句子：")
        lbl_finished.pack(anchor="w")
        self.finished_text = tk.Text(main, height=12, wrap=tk.WORD, state=tk.DISABLED)
        self.finished_text.pack(fill=tk.BOTH, expand=False)

        # 活动句子列表
        lbl_active = ttk.Label(main, text="活动句子（实时）：")
        lbl_active.pack(anchor="w", pady=(8,0))

        columns = ("sid", "text", "time")
        self.active_tree = ttk.Treeview(main, columns=columns, show="headings", height=6)
        self.active_tree.heading("sid", text="sid")
        self.active_tree.heading("text", text="实时内容")
        self.active_tree.heading("time", text="时间(ms)")
        self.active_tree.column("sid", width=50, anchor="center")
        self.active_tree.column("text", width=500, anchor="w")
        self.active_tree.column("time", width=90, anchor="center")
        self.active_tree.pack(fill=tk.BOTH, expand=False)

        # 选中活动句子的预览（大字、淡色用于表示临时）
        self.preview_var = tk.StringVar(value="")
        self.preview_label = ttk.Label(main, textvariable=self.preview_var, font=("Arial", 16), foreground="#666666", anchor="w", wraplength=800)
        self.preview_label.pack(fill=tk.X, pady=(6,0))

        # 底部控制
        ctrl_frame = ttk.Frame(main)
        ctrl_frame.pack(fill=tk.X, pady=(8,0))
        self.pause_btn = ttk.Button(ctrl_frame, text="暂停更新", command=self.toggle_pause)
        self.pause_btn.pack(side=tk.LEFT)
        ttk.Button(ctrl_frame, text="清空已完成", command=self.clear_finished).pack(side=tk.LEFT, padx=(8,0))
        ttk.Button(ctrl_frame, text="清空活动", command=self.clear_active).pack(side=tk.LEFT, padx=(8,0))

        # 状态
        self.paused = False

        # 内部缓冲
        # buffers: sid -> {'words': [unit], 'text': str, 'begin_time': int, 'end_time': int or None, 'sentence_end': bool, 'stable_count': int}
        self.buffers = {}
        # map sid -> tree item id
        self._tree_items = {}

        # 事件绑定
        self.active_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.config(text="继续更新" if self.paused else "暂停更新")

    def clear_finished(self):
        self.finished_text.config(state=tk.NORMAL)
        self.finished_text.delete("1.0", tk.END)
        self.finished_text.config(state=tk.DISABLED)

    def clear_active(self):
        self.buffers.clear()
        for item in self.active_tree.get_children():
            self.active_tree.delete(item)
        self._tree_items.clear()
        self.preview_var.set("")

    def _on_tree_select(self, _evt=None):
        sel = self.active_tree.selection()
        if not sel:
            self.preview_var.set("")
            return
        item = sel[0]
        sid = self.active_tree.set(item, "sid")
        buf = self.buffers.get(int(sid))
        if buf:
            # 临时文本使用淡色显示（preview_label 预设）
            self.preview_var.set(buf['text'])

    # 外部调用接口（可在任何线程中调用）
    def on_new_result(self, result: dict):
        if self.paused:
            return

        sid = int(result.get('sentence_id', 0))
        # 构造词单元（把词与标点合并）
        new_words = []
        for w in result.get('words', []):
            txt = w.get('text', '') or ''
            p = w.get('punctuation') or ''
            new_words.append(txt + p)

        # 获取或创建 buffer
        buf = self.buffers.get(sid)
        if buf is None:
            buf = {'words': [], 'text': '', 'begin_time': result.get('begin_time'),
                   'end_time': result.get('end_time'), 'sentence_end': False,
                   'stable_count': 0}
            self.buffers[sid] = buf

        prev_words = buf['words']

        # 优先尝试最长前缀更新，避免全量替换导致闪烁
        prefix = common_prefix_len(prev_words, new_words)
        # 决策阈值：如果前缀很短且 edit distance 也大，就全量替换；否则尝试局部替换
        use_full_replace = False
        if prefix < max(1, min(len(prev_words), len(new_words)) // 2):
            # 回退检查：若编辑距离相对较小，则仍可合并，否则全量替换
            dist = levenshtein(prev_words, new_words)
            maxlen = max(1, max(len(prev_words), len(new_words)))
            if dist / maxlen > 0.5:
                use_full_replace = True

        if use_full_replace:
            buf['words'] = new_words
            buf['stable_count'] = 0
        else:
            # 保留前缀，仅替换后缀
            buf['words'] = prev_words[:prefix] + new_words[prefix:]
            # 如果文本相同，stable_count++，用于判断是否稳定
            new_text = ''.join(buf['words'])
            if new_text == buf['text']:
                buf['stable_count'] = buf.get('stable_count', 0) + 1
            else:
                buf['stable_count'] = 0

        buf['text'] = ''.join(buf['words'])
        buf['end_time'] = result.get('end_time')
        buf['sentence_end'] = bool(result.get('sentence_end'))

        # 安全地调度 UI 更新
        self.root.after(0, self._update_ui_for_sid, sid)

        # 如果句子完成，调度 finalize
        if buf['sentence_end']:
            self.root.after(0, self._finalize_sentence, sid)

    # ---------- UI 更新方法（仅在主线程运行） ----------
    def _update_ui_for_sid(self, sid: int):
        buf = self.buffers.get(sid)
        if not buf:
            return
        # 更新或创建 tree item
        if sid in self._tree_items:
            item = self._tree_items[sid]
            self.active_tree.set(item, "text", buf['text'])
            self.active_tree.set(item, "time", buf['end_time'] or buf['begin_time'] or "")
        else:
            item = self.active_tree.insert("", tk.END, values=(sid, buf['text'], buf['end_time'] or buf['begin_time'] or ""))
            self._tree_items[sid] = item

        # 若选中项是当前 sid，则更新 preview
        sel = self.active_tree.selection()
        if sel and sel[0] == self._tree_items[sid]:
            self.preview_var.set(buf['text'])

    def _finalize_sentence(self, sid: int):
        buf = self.buffers.pop(sid, None)
        item = self._tree_items.pop(sid, None)
        if item:
            try:
                self.active_tree.delete(item)
            except Exception:
                pass
        if not buf:
            return
        line = buf['text']
        # 附加时间戳（可按需格式化）
        # bt = buf.get('begin_time')
        # et = buf.get('end_time')
        # if bt is not None or et is not None:
        #     line = f"[{bt or ''}-{et or ''}] " + line
        line = line + " "

        self.finished_text.config(state=tk.NORMAL)
        self.finished_text.insert(tk.END, line)
        self.finished_text.see(tk.END)
        self.finished_text.config(state=tk.DISABLED)

        # 如果 preview 正显示该句，清理
        current_preview = self.preview_var.get()
        if current_preview == buf['text']:
            self.preview_var.set("")

# ---------- 模拟流数据（示例） ----------
def simulate_streaming(app: StreamingASRApp):
    samples = [
        {'sentence_id': 1, 'begin_time': 680, 'end_time': None, 'text': '今',
         'words': [{'begin_time': 680, 'end_time': 1200, 'text': '今', 'punctuation': ''}],
         'sentence_end': False},
        {'sentence_id': 1, 'begin_time': 680, 'end_time': None, 'text': '今天，',
         'words': [{'begin_time': 680, 'end_time': 1920, 'text': '今天', 'punctuation': '，'}],
         'sentence_end': False},
        {'sentence_id': 1, 'begin_time': 680, 'end_time': 2420, 'text': '今天下午。',
         'words': [{'begin_time': 680, 'end_time': 1550, 'text': '今天'}, {'begin_time': 1550, 'end_time': 2420, 'text': '下午', 'punctuation': '。'}],
         'sentence_end': True},
        {'sentence_id': 2, 'begin_time': 3760, 'end_time': None, 'text': '不，',
         'words': [{'begin_time': 3760, 'end_time': 4240, 'text': '不', 'punctuation': '，'}], 'sentence_end': False},
        {'sentence_id': 2, 'begin_time': 3760, 'end_time': None, 'text': '布里给',
         'words': [{'begin_time': 3760, 'end_time': 4360, 'text': '布里'}, {'begin_time': 4360, 'end_time': 4960, 'text': '给'}], 'sentence_end': False},
        {'sentence_id': 2, 'begin_time': 3760, 'end_time': 5800, 'text': '部里给做了培训。',
         'words': [
             {'begin_time': 3760, 'end_time': 4270, 'text': '部里'},
             {'begin_time': 4270, 'end_time': 4780, 'text': '给做'},
             {'begin_time': 4780, 'end_time': 5290, 'text': '了培'},
             {'begin_time': 5290, 'end_time': 5800, 'text': '训', 'punctuation': '。'}
         ], 'sentence_end': True},
        {'sentence_id': 3, 'begin_time': 8100, 'end_time': None, 'text': '中',
         'words': [{'begin_time': 8100, 'end_time': 8640, 'text': '中'}], 'sentence_end': False},
        {'sentence_id': 3, 'begin_time': 8100, 'end_time': None, 'text': '整个培训的视频会转发到我们宁',
         'words': [
             {'begin_time': 8100, 'end_time': 8710, 'text': '整个'},
             {'begin_time': 8710, 'end_time': 9320, 'text': '培训'},
             {'begin_time': 9320, 'end_time': 9930, 'text': '的视'},
             {'begin_time': 9930, 'end_time': 10540, 'text': '频会'},
             {'begin_time': 10540, 'end_time': 11150, 'text': '转发'},
             {'begin_time': 11150, 'end_time': 11760, 'text': '到我'},
             {'begin_time': 11646, 'end_time': 12240, 'text': '们宁'}
         ], 'sentence_end': False},
    ]

    for r in samples:
        time.sleep(0.8)
        app.on_new_result(r)

# ---------- 启动 ----------
if __name__ == "__main__":
    root = tk.Tk()
    app = StreamingASRApp(root)
    # 模拟线程
    threading.Thread(target=simulate_streaming, args=(app,), daemon=True).start()
    root.mainloop()