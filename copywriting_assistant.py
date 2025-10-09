import threading
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox
from typing import Callable, List, Dict, Any
import json, os

try:
    from text_format import TextGenerator  # 复用已有封装
except ImportError:  # 兜底占位，避免在未安装依赖时报错
    TextGenerator = None  # type: ignore

# 全局单例生成器（简单懒加载）
_generator = None

def call_llm(prompt: str) -> str:
    """调用大模型，返回生成文本。必要时可扩展多消息结构。"""
    global _generator
    if TextGenerator is None:
        return "[占位返回 - 未找到 TextGenerator]" + prompt[:120]
    if _generator is None:
        _generator = TextGenerator()  # 使用默认模型 qwen-plus
    messages = [
        {"role": "system", "content": "你是资深新媒体编辑，负责将用户素材生成符合中文自媒体风格的成品文案。"},
        {"role": "user", "content": prompt}
    ]
    try:
        resp = _generator.generate(messages)
        return resp.get("output", {}).get("choices", [])[0].get("message", {}).get("content", "") or ""
    except Exception as e:
        return f"[生成失败]: {e}"


EMOTIONS = ["共鸣→疗愈", "焦虑→笃定", "犀利", "俏皮", "冷静专业", "逆转", "燃"]
STYLES = ["走心叙事", "干货清单", "拆穿认知", "剧情式", "俏皮槽点", "结构分析", "极简刀锋"]
FRAMEWORKS = ["自动", "PAS", "AIDA", "FAB", "三幕", "五段升级", "问题拆解"]
CTA_OPTIONS = ["关注", "评论关键词", "私信领取", "收藏", "点赞", "转发"]
CTA_TEMPLATES = {
    "关注": "结尾一句引导关注账号，并给出后续持续分享的价值理由",
    "评论关键词": "引导读者评论指定关键词（例如“资料”）以获取清单或模板",
    "私信领取": "引导读者私信发送指定关键词领取相关资料",
    "收藏": "提醒内容具备复用价值，自然引导收藏",
    "点赞": "一句轻量化引导点赞，强调反馈会促进继续输出",
    "转发": "点出适合转给哪类朋友并自然引导转发"
}
PLATFORMS = [
    "通用", "微信公众号", "小红书", "抖音短视频", "B站", "知乎", "视频号"
]
PLATFORM_RULES = {
    "通用": "保持易读、逻辑清晰、首段抓人，中间递进，结尾有余味。",
    "微信公众号": "首段 2~3 句制造强相关痛点或逆转；中段分段不超过 4 行，适度使用小标题；结尾可有温度与再关注引导。",
    "小红书": "前 2 行钩子，使用符号/数字提升停留；多用换行留白与表情符号点缀（适度，不堆砌）；结尾鼓励互动。",
    "抖音短视频": "脚本形式：按镜头/段落分条（如【画面1】/【镜头2】），开头 3 秒强钩子，语言口语化、短句，适度留悬念。",
    "B站": "偏知识/故事混合，可使用分节“前情 / 展开 / 总结”结构，语言兼具亲和与信息量，适度二次元/社区文化梗。",
    "知乎": "标题与开头突出问题/冲突；正文采用“提出问题→分析→结论”逻辑，段落首句点主题，避免花哨。",
    "视频号": "节奏略快，适度本地化/生活感；比抖音更体面自然，避免过度营销。"
}
CONFIG_PATH = "config.json"


class CopywritingAssistantWindow:
    """自媒体文案助手独立窗口。
    通过 on_select_callback 将选中的结果返回主界面。
    """
    def __init__(self, master: tk.Tk, source_text: str = "", on_select_callback: Callable[[str], None] | None = None):
        self.master = master
        self.source_text = source_text.strip()
        self.on_select_callback = on_select_callback
        self.top = tk.Toplevel(master)
        self.top.title("文案助手")
        self.top.geometry("860x760")
        self.top.transient(master)
        self.top.grab_set()
        self._loaded_state = self._load_state()
        self._build_ui()
        self.top.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI ----------------
    def _build_ui(self):
        params = ttk.LabelFrame(self.top, text="生成参数", padding=8)
        params.pack(fill="x", padx=10, pady=8)

        # 多选：情绪 / 风格 / 结构
        self.emotion_vars: List[tk.BooleanVar] = []
        self.style_vars: List[tk.BooleanVar] = []
        self.framework_vars: List[tk.BooleanVar] = []
        # 状态初值（若加载到历史配置则覆盖默认）
        state = self._loaded_state
        self.platform_var = tk.StringVar(value=state.get('platform', '通用'))
        self.var_length = tk.StringVar(value=state.get('length', "500±50"))
        self.var_versions = tk.IntVar(value=state.get('versions', 2))
        self.var_expand = tk.BooleanVar(value=state.get('expand', True))
        self.var_gold = tk.BooleanVar(value=state.get('gold', True))
        self.var_parallel = tk.BooleanVar(value=state.get('parallel', False))
        # CTA 多选
        self.cta_vars: List[tk.BooleanVar] = []
        row = 0
        # 平台单选
        ttk.Label(params, text="平台").grid(row=row, column=0, sticky="nw")
        plat_frame = ttk.Frame(params)
        plat_frame.grid(row=row, column=1, columnspan=6, sticky="w")
        for i, p in enumerate(PLATFORMS):
            ttk.Radiobutton(plat_frame, text=p, value=p, variable=self.platform_var).grid(row=0, column=i, padx=4, sticky="w")
        row += 1
        # 情绪多选
        ttk.Label(params, text="情绪").grid(row=row, column=0, sticky="nw")
        emo_frame = ttk.Frame(params)
        emo_frame.grid(row=row, column=1, columnspan=6, sticky="w")
        emo_selected = set(state.get('emotions', [])) if state else set()
        for i, emo in enumerate(EMOTIONS):
            var = tk.BooleanVar(value=(emo in emo_selected) if emo_selected else (i == 0))
            self.emotion_vars.append(var)
            ttk.Checkbutton(emo_frame, text=emo, variable=var).grid(row=0, column=i, padx=2, sticky="w")

        # 风格多选
        row += 1
        ttk.Label(params, text="风格").grid(row=row, column=0, sticky="nw", pady=(4,0))
        style_frame = ttk.Frame(params)
        style_frame.grid(row=row, column=1, columnspan=6, sticky="w", pady=(4,0))
        style_selected = set(state.get('styles', [])) if state else set()
        for i, sty in enumerate(STYLES):
            var = tk.BooleanVar(value=(sty in style_selected) if style_selected else (i < 2))
            self.style_vars.append(var)
            ttk.Checkbutton(style_frame, text=sty, variable=var).grid(row=0, column=i, padx=2, sticky="w")

        # 结构多选
        row += 1
        ttk.Label(params, text="结构").grid(row=row, column=0, sticky="nw", pady=(4,0))
        fw_frame = ttk.Frame(params)
        fw_frame.grid(row=row, column=1, columnspan=6, sticky="w", pady=(4,0))
        fw_selected = set(state.get('frameworks', [])) if state else set()
        for i, fw in enumerate(FRAMEWORKS):
            var = tk.BooleanVar(value=(fw in fw_selected) if fw_selected else (fw == "自动"))
            self.framework_vars.append(var)
            ttk.Checkbutton(fw_frame, text=fw, variable=var).grid(row=0, column=i, padx=2, sticky="w")

        # CTA 复选平铺 (在长度行之上)
        row += 1
        ttk.Label(params, text="CTA").grid(row=row, column=0, sticky="nw", pady=(6,0))
        cta_frame = ttk.Frame(params)
        cta_frame.grid(row=row, column=1, columnspan=6, sticky="w", pady=(6,0))
        cta_selected = set(state.get('ctas', [])) if state else set()
        for i, cta in enumerate(CTA_OPTIONS):
            var = tk.BooleanVar(value=(cta in cta_selected) if cta_selected else (i == 0))
            self.cta_vars.append(var)
            ttk.Checkbutton(cta_frame, text=cta, variable=var).grid(row=0, column=i, padx=2, sticky="w")

        # 其他参数行（移动到 CTA 下方）
        row += 1
        ttk.Label(params, text="长度").grid(row=row, column=0, sticky="w", pady=(6,0))
        ttk.Entry(params, textvariable=self.var_length, width=10).grid(row=row, column=1, padx=4, sticky="w", pady=(6,0))
        ttk.Label(params, text="版本数").grid(row=row, column=2, sticky="w", pady=(6,0))
        ttk.Spinbox(params, from_=1, to=6, textvariable=self.var_versions, width=5).grid(row=row, column=3, padx=4, sticky="w", pady=(6,0))
        ttk.Checkbutton(params, text="可扩写", variable=self.var_expand).grid(row=row, column=4, sticky="w", pady=(6,0))
        ttk.Checkbutton(params, text="金句", variable=self.var_gold).grid(row=row, column=5, sticky="w", pady=(6,0))
        ttk.Checkbutton(params, text="排比", variable=self.var_parallel).grid(row=row, column=6, sticky="w", pady=(6,0))

        # 操作按钮行
        row += 1
        ttk.Button(params, text="生成文案", command=self.generate).grid(row=row, column=5, padx=4, pady=(6,0))
        ttk.Button(params, text="清空结果", command=self.clear_results).grid(row=row, column=6, padx=4, pady=(6,0))

        # 素材编辑
        src_frame = ttk.LabelFrame(self.top, text="素材 (可编辑)", padding=6)
        src_frame.pack(fill="both", expand=False, padx=10, pady=(0,8))
        self.src_text = scrolledtext.ScrolledText(src_frame, height=8, wrap="word")
        self.src_text.pack(fill="both", expand=True)
        if self.source_text:
            self.src_text.insert("1.0", self.source_text)

        # 结果
        result_frame = ttk.LabelFrame(self.top, text="候选结果", padding=6)
        result_frame.pack(fill="both", expand=True, padx=10, pady=(0,8))
        self.result_box = scrolledtext.ScrolledText(result_frame, wrap="word")
        self.result_box.pack(fill="both", expand=True)

        # 底部操作
        bottom = ttk.Frame(self.top)
        bottom.pack(fill="x", padx=10, pady=6)
        ttk.Button(bottom, text="选中插入主窗口", command=self.insert_selected).pack(side="left")
        ttk.Button(bottom, text="关闭", command=self.top.destroy).pack(side="right")
        ttk.Label(self.top, text="提示: 拖选某一版本文本后点击“选中插入主窗口”。", foreground="#666").pack(fill="x", padx=10, pady=(0,8))

    # ---------------- Prompt 构建 ----------------
    def _build_prompts(self, raw: str) -> List[str]:
        emotions_sel = [e for e, v in zip(EMOTIONS, self.emotion_vars) if v.get()]
        styles_sel = [s for s, v in zip(STYLES, self.style_vars) if v.get()]
        frameworks_sel = [f for f, v in zip(FRAMEWORKS, self.framework_vars) if v.get()]
        if not emotions_sel:
            emotions_sel = [EMOTIONS[0]]
        if not styles_sel:
            styles_sel = [STYLES[0]]
        if not frameworks_sel:
            frameworks_sel = ["自动"]

        # 结构描述
        if len(frameworks_sel) == 1:
            fw_desc = f"{frameworks_sel[0]}（若=自动，自行择最优但不显式说明）"
        else:
            fw_desc = f"在以下结构中择最优并内化呈现：{', '.join(frameworks_sel)}（不显式写出结构名称）"

        # CTA 组合
        ctas_sel = [c for c, v in zip(CTA_OPTIONS, self.cta_vars) if v.get()]
        if not ctas_sel:
            ctas_sel = [CTA_OPTIONS[0]]
        if len(ctas_sel) == 1:
            single = ctas_sel[0]
            tmpl = CTA_TEMPLATES.get(single, "自然加入即可")
            cta_desc = f"围绕“{single}”设计主 CTA，自然融入（{tmpl}）。"
        else:
            tmpl_list = [f"{c}:{CTA_TEMPLATES.get(c,'')}" for c in ctas_sel]
            cta_desc = (
                f"从以下候选中择 1 个主 CTA（可轻度暗示第二个，不要全部列出）：{', '.join(ctas_sel)}。每个说明：" + ' | '.join(tmpl_list)
            )

        platform = getattr(self, 'platform_var', tk.StringVar(value='通用')).get()
        platform_rule = PLATFORM_RULES.get(platform, PLATFORM_RULES.get('通用'))
        base_common = (
            f"你是资深新媒体编辑。\n任务：将素材改写为适合 {platform} 的高质量中文自媒体文案。\n平台特殊规则：{platform_rule}\n统一写作要求：\n"
            f"- 情绪基调：{'、'.join(emotions_sel)}（可融合过渡）\n"
            f"- 结构：{fw_desc}\n"
            f"- 字数：{self.var_length.get()}\n"
            f"- 扩写：{'允许加入1处贴近生活的细节例子' if self.var_expand.get() else '禁止新增与素材无关的事实例子'}\n"
            f"- 增强：{'加入一句可引用金句' if self.var_gold.get() else ''} {'适度一次排比' if self.var_parallel.get() else ''}\n"
            f"- CTA：{cta_desc}\n"
            f"- 不要杜撰具体数字。\n- 只输出成品，不要写分析说明。\n素材：\n{raw}\n"
        )

        versions = self.var_versions.get()
        # 为多版本挑选不同风格（循环使用已选风格）
        prompts = []
        for i in range(versions):
            style_used = styles_sel[i % len(styles_sel)]
            prompt = (
                f"{base_common}- 风格：{style_used}\n"
                "输出：先正文，最后单独一行以“标题建议：”开头给 3 个 12~18 字标题，用 | 分隔，不要句号。"
            )
            prompts.append(prompt)
        return prompts

    # ---------------- 生成逻辑 ----------------
    def generate(self):
        raw = self.src_text.get("1.0", "end").strip()
        if not raw:
            messagebox.showinfo("提示", "素材为空")
            return
        # 保存当前状态（即时）
        self._save_state()
        self._set_busy(True)
        self.result_box.delete("1.0", "end")
        self.result_box.insert("end", "生成中，请稍候...\n")
        threading.Thread(target=self._worker, args=(raw,), daemon=True).start()

    def _worker(self, raw: str):
        try:
            prompts = self._build_prompts(raw)
            outputs = []
            for i, prompt in enumerate(prompts, 1):
                out = call_llm(prompt)
                outputs.append((i, out.strip()))
            self.top.after(0, lambda: self._show(outputs))
        except Exception as e:
            self.top.after(0, lambda: messagebox.showerror("生成失败", str(e)))
        finally:
            self.top.after(0, lambda: self._set_busy(False))

    def _show(self, outputs):
        self.result_box.delete("1.0", "end")
        for i, text in outputs:
            self.result_box.insert("end", f"【版本 {i}】\n{text}\n\n---\n\n")

    def clear_results(self):
        self.result_box.delete("1.0", "end")

    def insert_selected(self):
        try:
            selected = self.result_box.get(tk.SEL_FIRST, tk.SEL_LAST)
        except tk.TclError:
            messagebox.showinfo("提示", "请先选中文案内容")
            return
        if not selected.strip():
            messagebox.showinfo("提示", "所选为空")
            return
        if self.on_select_callback:
            self.on_select_callback(selected.strip())
            messagebox.showinfo("完成", "已插入主窗口")
        else:
            messagebox.showinfo("提示", "未设置回调")

    def _set_busy(self, busy: bool):
        state = "disabled" if busy else "normal"
        SUPPORTED = (ttk.Entry, ttk.Button, ttk.Checkbutton, ttk.Spinbox, ttk.Radiobutton)
        for child in self.top.winfo_children():
            if isinstance(child, ttk.LabelFrame) and child.cget("text") == "生成参数":
                for sub in child.winfo_children():
                    if isinstance(sub, SUPPORTED):
                        try:
                            sub.configure(state=state)
                        except Exception:
                            pass
        if busy:
            self.top.config(cursor="watch")
        else:
            self.top.config(cursor="")

    # ---------------- 状态持久化 ----------------
    def _load_state(self) -> Dict[str, Any]:
        if not os.path.exists(CONFIG_PATH):
            return {}
        try:
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                cfg = json.load(f) or {}
            return cfg.get('copywriting_assistant', {}) or {}
        except Exception:
            return {}

    def _save_state(self):
        # 采集当前勾选状态
        state = {
            'emotions': [e for e, v in zip(EMOTIONS, self.emotion_vars) if v.get()],
            'styles': [s for s, v in zip(STYLES, self.style_vars) if v.get()],
            'frameworks': [f for f, v in zip(FRAMEWORKS, self.framework_vars) if v.get()],
            'ctas': [c for c, v in zip(CTA_OPTIONS, self.cta_vars) if v.get()],
            'length': self.var_length.get(),
            'versions': self.var_versions.get(),
            'expand': self.var_expand.get(),
            'gold': self.var_gold.get(),
            'parallel': self.var_parallel.get()
        }
        # 写入 config.json 合并
        data = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            except Exception:
                data = {}
        # 平台
        state['platform'] = self.platform_var.get()
        data['copywriting_assistant'] = state
        try:
            with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _on_close(self):
        try:
            self._save_state()
        finally:
            self.top.destroy()

    # _set_group 已移除（全选/清空按钮删除）

__all__ = ["CopywritingAssistantWindow", "call_llm"]
