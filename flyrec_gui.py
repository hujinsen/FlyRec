"""
语音识别工具图形界面 - 修复版
基于 tkinter.ttk 实现，提供统计信息、快捷键设置、识别历史等功能
修复了线程安全问题和智能模板切换功能
"""

import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
import threading
import time
import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Any
import pystray
from PIL import Image, ImageDraw
import keyboard
import sys
from text_format import TextGenerator  # 语义润色生成 (将被 services 层替换)
from services import FlyRecRuntime, ServiceFactory  # 新增: 统一服务层
from pynput import mouse  # 监听鼠标选择
import pyautogui  # 复制/粘贴辅助
import pyperclip  # 读取剪贴板内容

from flyrec.env import load_dotenv_next_to
from flyrec.smart_template import (
    SMART_TEMPLATE_AVAILABLE,
    DEFAULT_APP_SCENE_MAPPING,
    get_active_window_process as _get_active_window_process,
    suggest_scene as _suggest_scene,
)
from flyrec.recognizers import CustomRecognizer, ServiceRecognizer

# 导入播放音效库（新增）
import sounddevice as sd
try:
    import soundfile as sf  # 新增，用于读取wav
except ImportError:
    sf = None
    print("缺少 soundfile 库，音效功能不可用。安装: uv add soundfile  或  pip install soundfile")


# 注意：不要在源码中硬编码 DASHSCOPE_API_KEY。
# 请通过环境变量设置：$Env:DASHSCOPE_API_KEY="..."

# 支持从 .env 文件加载环境变量（优先加载脚本同目录的 .env）
load_dotenv_next_to(__file__, override=False)

class VoiceRecognitionGUI:
    """语音识别工具图形界面"""
    
    def __init__(self):
        self.root = tk.Tk()
        # 预加载音效缓存结构: { 'start': (data, samplerate), 'end': (data, samplerate) }
        self._sound_cache = {}
        # 标记是否已尝试预加载，避免重复磁盘IO
        self._sound_preloaded = False
        
        # 启动线程，预加载音效
        threading.Thread(target=self.preload_sounds).start()
        
        self.root.title("FlyRecDemo")
        self.root.geometry("850x850")
        
        # 数据存储
        self.stats_file = "voice_stats.json"
        self.transcripts_file = "transcripts.json"
        self.load_data()

        # 语音识别器与快捷键初始化
        self.recognizer = None
        self.is_recording = False
        #double_ctrl   ctrl+space
        self.current_hotkey = "ctrl+space"
        # 从配置文件加载快捷键及模式
        self.config_file = "config.json"
        loaded_hotkey, loaded_mode = self.load_hotkey_config()
        if loaded_hotkey:
            self.current_hotkey = loaded_hotkey
        # 加载提示词配置（中文默认 + 场景提示词）
        self.prompts = self.load_prompts_config()
        # 内置默认与场景提示词（改为从配置文件加载，可缺省回退到内置硬编码字典）
        self.builtin_default_prompt = ""
        self.builtin_scene_prompts = {}
        self.load_builtin_prompts_from_config()
        # 语言模式(中文/英语) + 场景(文本/聊天/邮件/代码) 默认中文, 之后尝试加载上次保存
        self.language_mode_var = tk.StringVar(value='中文')
        loaded_language = self.load_language_config()
        if loaded_language:
            self.language_mode_var.set(loaded_language)
        self.template_scene_var = tk.StringVar(value='文本')
        # 新增: 快捷键模式变量 (hold: 按住说话, double_ctrl: 双击Ctrl开始/单击结束)
        self.hotkey_mode_var = tk.StringVar(value=loaded_mode or "hold")
        self.double_ctrl_interval = 0.5  # 双击 Ctrl 判定最大间隔(秒)
        self._last_ctrl_release_time = 0.0
        
        # 按键监听相关
        self.hotkey_parts = []
        self.hotkey_thread = None
        
        # 系统托盘
        self.tray_icon = None
        
        # 录音提示窗口
        self.recording_indicator = None
        
        # 录音时长记录
        self.last_recording_duration = 0
        
        # 初始化设置变量
        self.auto_paste_var = tk.BooleanVar(value=True)
        self.minimize_to_tray_var = tk.BooleanVar(value=True)
        # 旧 template_var 废弃，改用 language_mode_var + template_scene_var
        self.smart_template_var = tk.BooleanVar(value=True)  # 智能模板切换开关

    # （已移除）选中文本 AI 润色功能相关变量删除
        # self._text_generator = TextGenerator()  # 旧直连方式
        # 初始化统一服务运行时（允许 config.json 中 future 字段控制后端）
        try:
            cfg = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as _cf:
                    cfg = json.load(_cf) or {}
            self.runtime = FlyRecRuntime.from_config(cfg.get('runtime'))
            self._text_generator = None  # 使用 runtime.llm
        except Exception as _rt_e:
            print(f"初始化服务层失败，回退到直接 TextGenerator: {_rt_e}")
            self.runtime = None
            self._text_generator = TextGenerator()
    # （选中文本润色功能已移除，鼠标监听不再启动）
        # 抑制 Ctrl 监听（防止程序内部 pyautogui.hotkey 触发双击Ctrl逻辑）
        self._suppress_ctrl_listener = False
        
        # 应用程序模板映射
        self.app_template_mapping = dict(DEFAULT_APP_SCENE_MAPPING)
        
        # 创建界面
        self.create_widgets()
        self.setup_hotkey()
        self.update_stats_display()
        self.update_transcripts_display()
        
        # 定时更新
        self.root.after(1000, self.update_timer)
        
        # 窗口关闭事件
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
    
    def load_data(self):
        """加载统计数据和转录历史"""
        # 加载统计数据
        if os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f)
            except:
                self.stats = self.default_stats()
        else:
            self.stats = self.default_stats()
        
        # 加载转录历史
        if os.path.exists(self.transcripts_file):
            try:
                with open(self.transcripts_file, 'r', encoding='utf-8') as f:
                    self.transcripts = json.load(f)
            except:
                self.transcripts = []
        else:
            self.transcripts = []
    
    def default_stats(self):
        """默认统计数据"""
        return {
            "total_words": 0,
            "total_time": 0,  # 秒
            "sessions_count": 0,
            "last_30_days": []
        }
    
    def save_data(self):
        """保存数据"""
        try:
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, ensure_ascii=False, indent=2)
            
            with open(self.transcripts_file, 'w', encoding='utf-8') as f:
                json.dump(self.transcripts, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存数据失败: {e}")
    
    def create_widgets(self):
        """创建界面组件"""
        # 主容器
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 左侧导航
        self.create_sidebar(main_frame)
        
        # 右侧内容区域
        self.create_content_area(main_frame)
    
    def create_sidebar(self, parent):
        """创建左侧导航栏"""
        sidebar = ttk.Frame(parent, width=200)
        sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        sidebar.pack_propagate(False)
        
        # 标题
        title_label = ttk.Label(sidebar, text="独白", font=('Arial', 16, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # 顶部主功能按钮（保持原顺序的前三个）
        top_buttons = [
            ("📊 仪表板", self.show_dashboard),
            ("🎤 转录记录", self.show_transcripts),
            ("📝 词典", self.show_user_dictionary)
        ]
        self.nav_buttons = {}
        for text, command in top_buttons:
            btn = ttk.Button(sidebar, text=text, command=command, width=20)
            btn.pack(pady=2, fill=tk.X)
            self.nav_buttons[text] = btn

        # 底部设置与帮助
        bottom_frame = ttk.Frame(sidebar)
        bottom_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(10,0))
        
        # ttk.Separator(bottom_frame, orient='horizontal').pack(fill=tk.X, pady=(0,10))
        self.status_label = ttk.Label(bottom_frame, text="状态: 待机", foreground='green')
        self.status_label.pack()
        
        self.hotkey_label = ttk.Label(bottom_frame, text=f"快捷键: {self.current_hotkey}")
        self.hotkey_label.pack(pady=(5, 0))
        
        ttk.Separator(bottom_frame, orient='horizontal').pack(fill=tk.X, pady=(0,6))
        settings_btn = ttk.Button(bottom_frame, text="⚙️ 设置", command=self.show_settings, width=20)
        settings_btn.pack(pady=2, fill=tk.X)
        help_btn = ttk.Button(bottom_frame, text="❓ 帮助", command=self.show_help, width=20)
        help_btn.pack(pady=2, fill=tk.X)
        # 记录引用
        self.nav_buttons["⚙️ 设置"] = settings_btn
        self.nav_buttons["❓ 帮助"] = help_btn
    
    def show_user_dictionary(self):
        """用户词典配置界面: 原词 -> 目标词语 (替换/标准化)"""
        self.clear_content()

        # 初始化内存结构
        if not hasattr(self, 'user_dict'):
            self.user_dict_file = 'user_dictionary.json'
            self.user_dict = self._load_user_dictionary()

        ttk.Label(self.content_frame, text="用户词典配置", font=('Arial', 18, 'bold')).pack(anchor=tk.W, pady=(0, 18))

        form_frame = ttk.Frame(self.content_frame)
        form_frame.pack(fill=tk.X, padx=10, pady=(0,10))

        ttk.Label(form_frame, text="原词").grid(row=0, column=0, sticky=tk.W)
        self.ud_src_var = tk.StringVar()
        src_entry = ttk.Entry(form_frame, textvariable=self.ud_src_var, width=15)
        src_entry.grid(row=0, column=1, padx=(6,20), sticky=tk.W)

        ttk.Label(form_frame, text="替换为").grid(row=0, column=2, sticky=tk.W)
        self.ud_dst_var = tk.StringVar()
        dst_entry = ttk.Entry(form_frame, textvariable=self.ud_dst_var, width=15)
        dst_entry.grid(row=0, column=3, padx=(6,20), sticky=tk.W)

        def add_or_update():
            src = self.ud_src_var.get().strip()
            dst = self.ud_dst_var.get().strip()
            if not src or not dst:
                messagebox.showwarning("提示", "原词与替换内容均不能为空")
                return
            existed = src in self.user_dict
            self.user_dict[src] = dst
            self._save_user_dictionary()
            self._refresh_user_dict_view()
            if existed:
                msg = f"已更新条目: {src} -> {dst}"
            else:
                msg = f"已新增条目: {src} -> {dst}"
            print(msg)
            self.ud_src_var.set("")
            self.ud_dst_var.set("")
            src_entry.focus_set()

        ttk.Button(form_frame, text="新增 / 更新", command=add_or_update).grid(row=0, column=4, sticky=tk.W)

        # 列表区域
        list_frame = ttk.Frame(self.content_frame, relief=tk.GROOVE, borderwidth=1)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=25, pady=(10,10))
        ttk.Label(list_frame, text="用户字典", foreground='gray').pack(anchor=tk.W, padx=6, pady=(4,2))

        # Treeview
        columns = ("原词", "目标词语")
        self.user_dict_tree = ttk.Treeview(list_frame, columns=columns, show='headings', height=12)
        for col in columns:
            self.user_dict_tree.heading(col, text=col)
            self.user_dict_tree.column(col, width=180 if col=="原词" else 320, anchor=tk.W)
        self.user_dict_tree.pack(fill=tk.BOTH, expand=True, padx=6, pady=(0,6))

        # 右键菜单
        menu = tk.Menu(self.user_dict_tree, tearoff=0)
        menu.add_command(label="删除", command=lambda: self._delete_selected_user_dict())
        menu.add_command(label="编辑到输入框", command=lambda: self._load_selected_into_form())
        self.user_dict_tree.bind('<Button-3>', lambda e: self._popup_user_dict_menu(e, menu))
        self.user_dict_tree.bind('<Double-1>', lambda e: self._load_selected_into_form())

        self._refresh_user_dict_view()

    # ================= 用户词典内部逻辑 =================
    def _load_user_dictionary(self):
        try:
            if os.path.exists(getattr(self, 'user_dict_file', 'user_dictionary.json')):
                with open(self.user_dict_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            print(f"读取用户词典失败: {e}")
        return {}

    def _save_user_dictionary(self):
        try:
            with open(self.user_dict_file, 'w', encoding='utf-8') as f:
                json.dump(self.user_dict, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存用户词典失败: {e}")

    def _refresh_user_dict_view(self):
        if not hasattr(self, 'user_dict_tree'):
            return
        for item in self.user_dict_tree.get_children():
            self.user_dict_tree.delete(item)
        # 排序展示
        for src, dst in sorted(self.user_dict.items(), key=lambda x: x[0].lower()):
            self.user_dict_tree.insert('', 'end', values=(src, dst))

    def _delete_selected_user_dict(self):
        if not hasattr(self, 'user_dict_tree'):
            return
        sel = self.user_dict_tree.selection()
        if not sel:
            return
        if not messagebox.askyesno("确认", "确定删除所选条目？"):
            return
        removed = 0
        for iid in sel:
            vals = self.user_dict_tree.item(iid, 'values')
            if vals and vals[0] in self.user_dict:
                self.user_dict.pop(vals[0], None)
                removed += 1
        if removed:
            self._save_user_dictionary()
            self._refresh_user_dict_view()
            print(f"已删除 {removed} 条词典记录")

    def _load_selected_into_form(self):
        if not hasattr(self, 'user_dict_tree'):
            return
        sel = self.user_dict_tree.selection()
        if not sel:
            return
        vals = self.user_dict_tree.item(sel[0], 'values')
        if not vals:
            return
        self.ud_src_var.set(vals[0])
        self.ud_dst_var.set(vals[1])

    def _popup_user_dict_menu(self, event, menu):
        iid = self.user_dict_tree.identify_row(event.y)
        if iid:
            self.user_dict_tree.selection_set(iid)
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

    # 导入/导出功能已移除（保留占位便于未来扩展）
      
    def create_content_area(self, parent):
        """创建右侧内容区域"""
        self.content_frame = ttk.Frame(parent)
        self.content_frame.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True)
        
        # 默认显示仪表板
        self.show_dashboard()
    
    def clear_content(self):
        """清空内容区域"""
        for widget in self.content_frame.winfo_children():
            widget.destroy()
    
    def show_dashboard(self):
        """显示仪表板"""
        self.clear_content()
        
        # 标题
        title = ttk.Label(self.content_frame, text="仪表板", font=('Arial', 18, 'bold'))
        title.pack(anchor=tk.W, pady=(0, 20))
        
        # 统计卡片
        stats_frame = ttk.Frame(self.content_frame)
        stats_frame.pack(fill=tk.X, pady=(0, 20))
        
        # 统计数据
        self.stats_cards = {}
        stats_data = [
            ("总字数", str(self.stats['total_words']), "words"),
            ("录音时长", self.format_time(self.stats['total_time']), "time"),
            ("平均CPM", str(self.calculate_wpm()), "wmp")
        ]
        
        for i, (label, value, key) in enumerate(stats_data):
            card = ttk.LabelFrame(stats_frame, text=label, padding=10)
            card.grid(row=0, column=i, padx=5, sticky="ew")
            stats_frame.grid_columnconfigure(i, weight=1)
            
            value_label = ttk.Label(card, text=value, font=('Arial', 24, 'bold'))
            value_label.pack()
            
            self.stats_cards[key] = value_label
        
        # 最近转录区（包含操作按钮）
        recent_frame = ttk.LabelFrame(self.content_frame, text="最近转录", padding=10)
        recent_frame.pack(fill=tk.BOTH, expand=True)

        self.recent_text = scrolledtext.ScrolledText(recent_frame, height=12, wrap=tk.WORD)
        self.recent_text.pack(fill=tk.BOTH, expand=True)

        ops_frame = ttk.Frame(recent_frame)
        ops_frame.pack(fill=tk.X, pady=(8,0))
        ttk.Button(ops_frame, text="清空统计", command=self.clear_stats).pack(side=tk.LEFT, padx=(0,6))
        ttk.Button(ops_frame, text="导出数据", command=self.export_data).pack(side=tk.LEFT)

        # 显示最近的转录
        self.update_recent_transcripts()
    
    def show_transcripts(self):
        """显示转录记录"""
        self.clear_content()
        
        title = ttk.Label(self.content_frame, text="转录记录", font=('Arial', 18, 'bold'))
        title.pack(anchor=tk.W, pady=(0, 20))
        
        # 搜索框
        search_frame = ttk.Frame(self.content_frame)
        search_frame.pack(fill=tk.X, pady=(0, 10))
        
        ttk.Label(search_frame, text="搜索:").pack(side=tk.LEFT)
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        search_entry.pack(side=tk.LEFT, padx=(5, 0), fill=tk.X, expand=True)
        search_entry.bind('<KeyRelease>', self.filter_transcripts)
        
        # 转录列表
        list_frame = ttk.Frame(self.content_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # 表格
        columns = ("时间", "原文", "处理后", "词数")
        self.transcript_tree = ttk.Treeview(list_frame, columns=columns, show="headings", height=15)
        
        for col in columns:
            self.transcript_tree.heading(col, text=col)
            self.transcript_tree.column(col, width=150)
        
        # 滚动条
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.transcript_tree.yview)
        self.transcript_tree.configure(yscrollcommand=scrollbar.set)
        
        self.transcript_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        self.update_transcripts_display()

        # 绑定双击与右键菜单
        self.transcript_tree.bind('<Double-1>', self.open_transcript_detail_event)
        self.transcript_tree.bind('<Button-3>', self.open_transcript_detail_event)  # 右键

        # 右键菜单（可扩展）
        self._transcript_menu = tk.Menu(self.transcript_tree, tearoff=0)
        self._transcript_menu.add_command(label="查看详情", command=self.open_selected_transcript_detail)
        # 可加入复制等功能

    def open_transcript_detail_event(self, event):
        """事件触发：双击或右键显示详情。右键先选中行。"""
        try:
            region = self.transcript_tree.identify('region', event.x, event.y)
            if region == 'cell' or event.num == 3:
                item_id = self.transcript_tree.identify_row(event.y)
                if item_id:
                    # 右键需要设置选中
                    if event.num == 3:
                        self.transcript_tree.selection_set(item_id)
                        try:
                            self._transcript_menu.tk_popup(event.x_root, event.y_root)
                        finally:
                            self._transcript_menu.grab_release()
                    else:
                        self.open_transcript_detail(item_id)
        except Exception as e:
            print(f"打开详情事件失败: {e}")

    def open_selected_transcript_detail(self):
        sel = self.transcript_tree.selection()
        if sel:
            self.open_transcript_detail(sel[0])

    def open_transcript_detail(self, item_id):
        """根据 tree item id 打开详情窗口"""
        try:
            values = self.transcript_tree.item(item_id, 'values')
            if not values or len(values) < 4:
                return
            # 根据显示顺序找到对应 transcript 原始对象（简单匹配时间+word_count+截断文本）
            time_str, original_short, formatted_short, wc = values
            matched = None
            for t in self.transcripts:
                try:
                    ts_fmt = datetime.fromisoformat(t['timestamp']).strftime('%m-%d %H:%M')
                except Exception:
                    continue
                if ts_fmt == time_str and str(t.get('word_count')) == str(wc):
                    # 进一步粗略核对开头
                    if t['original'].startswith(original_short[:10]) or original_short.replace('...', '') in t['original']:
                        matched = t
                        break
            if not matched:
                print("未找到匹配的转录记录")
                return

            win = tk.Toplevel(self.root)
            win.title(f"转录详情 - {time_str}")
            win.geometry("900x520")
            win.transient(self.root)
            win.grab_set()

            # 使用 grid 保证底部按钮可见
            win.grid_rowconfigure(1, weight=1)
            win.grid_columnconfigure(0, weight=1)

            # 支持 ESC 关闭
            win.bind('<Escape>', lambda e: win.destroy())

            # 上方信息栏
            info_bar = ttk.Frame(win)
            info_bar.grid(row=0, column=0, sticky='ew', padx=10, pady=(8,4))
            ttk.Label(info_bar, text=f"时间: {time_str}  词数: {matched.get('word_count', '')}").pack(side=tk.LEFT)

            # 主体区域（左右文本）
            body = ttk.Frame(win)
            body.grid(row=1, column=0, sticky='nsew', padx=8, pady=4)
            body.grid_rowconfigure(0, weight=1)
            body.grid_columnconfigure(0, weight=1)
            body.grid_columnconfigure(1, weight=1)

            # 左列
            left_col = ttk.Frame(body)
            left_col.grid(row=0, column=0, sticky='nsew', padx=(0,4))
            ttk.Label(left_col, text="原始文本", font=('Arial', 11, 'bold')).pack(anchor=tk.W)
            orig_txt = scrolledtext.ScrolledText(left_col, wrap=tk.WORD, font=('Consolas', 11))
            orig_txt.pack(fill=tk.BOTH, expand=True)
            orig_txt.insert(tk.END, matched['original'])
            orig_txt.config(state='disabled')

            # 右列
            right_col = ttk.Frame(body)
            right_col.grid(row=0, column=1, sticky='nsew', padx=(4,0))
            ttk.Label(right_col, text="处理后文本", font=('Arial', 11, 'bold')).pack(anchor=tk.W)
            fmt_txt = scrolledtext.ScrolledText(right_col, wrap=tk.WORD, font=('Consolas', 11))
            fmt_txt.pack(fill=tk.BOTH, expand=True)
            fmt_txt.insert(tk.END, matched['formatted'])
            fmt_txt.config(state='disabled')

            # 底部操作按钮
            btn_bar = ttk.Frame(win)
            btn_bar.grid(row=2, column=0, sticky='ew', padx=10, pady=(4,10))
            btn_bar.grid_columnconfigure(0, weight=1)

            def copy_original():
                try:
                    import pyperclip
                    pyperclip.copy(matched['original'])
                except Exception as ce:
                    messagebox.showerror("复制失败", str(ce))

            def copy_formatted():
                try:
                    import pyperclip
                    pyperclip.copy(matched['formatted'])
                except Exception as ce:
                    messagebox.showerror("复制失败", str(ce))

            ttk.Button(btn_bar, text="复制原始", command=copy_original).pack(side=tk.LEFT)
            ttk.Button(btn_bar, text="复制处理后", command=copy_formatted).pack(side=tk.LEFT, padx=(6,0))
            ttk.Button(btn_bar, text="关闭(Esc)", command=win.destroy).pack(side=tk.RIGHT)

        except Exception as e:
            print(f"打开详情窗口失败: {e}")
    
    def show_settings(self):
        """显示设置页面"""
        self.clear_content()

        # 标题
        ttk.Label(self.content_frame, text="设置", font=('Arial', 18, 'bold')).pack(anchor=tk.W, pady=(0,20))

        # 快捷键设置
        hotkey_frame = ttk.LabelFrame(self.content_frame, text="快捷键设置", padding=10)
        hotkey_frame.pack(fill=tk.X, pady=(0,15))
        ttk.Label(hotkey_frame, text="当前快捷键:").grid(row=0, column=0, sticky=tk.W)
        self.hotkey_var = tk.StringVar(value=self.current_hotkey)
        ttk.Entry(hotkey_frame, textvariable=self.hotkey_var).grid(row=0, column=1, padx=(10,0), sticky=tk.W)
        ttk.Button(hotkey_frame, text="应用", command=self.apply_hotkey).grid(row=0, column=2, padx=(10,0))
        ttk.Label(hotkey_frame, text="提示: ctrl+space 格式 (仅按住模式有效)", foreground='gray').grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(5,0))

        # 快捷键模式
        mode_frame = ttk.LabelFrame(self.content_frame, text="快捷键", padding=10)
        mode_frame.pack(fill=tk.X, pady=(0,15))
        ttk.Radiobutton(mode_frame, text="按住说话 (Ctrl+Space)", value='hold', variable=self.hotkey_mode_var, command=self.on_hotkey_mode_change).grid(row=0, column=0, sticky=tk.W, padx=(0,12))
        ttk.Radiobutton(mode_frame, text="双击Ctrl开始/单击结束", value='double_ctrl', variable=self.hotkey_mode_var, command=self.on_hotkey_mode_change).grid(row=0, column=1, sticky=tk.W)
        ttk.Label(mode_frame, text="双击间隔 ≤ 0.5 秒", foreground='gray').grid(row=1, column=0, columnspan=2, sticky=tk.W, pady=(4,0))

        # 输出语言
        lang_frame = ttk.LabelFrame(self.content_frame, text="输出语言", padding=10)
        lang_frame.pack(fill=tk.X, pady=(0,15))
        ttk.Radiobutton(lang_frame, text='中文', value='中文', variable=self.language_mode_var, command=self.on_language_change).grid(row=0, column=0, padx=6, sticky=tk.W)
        ttk.Radiobutton(lang_frame, text='英语', value='英语', variable=self.language_mode_var, command=self.on_language_change).grid(row=0, column=1, padx=6, sticky=tk.W)
        ttk.Label(lang_frame, text='中文模式输出中文，英语模式输出英语。', foreground='gray').grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(4,0))

        # 场景选择 + 智能切换
        scene_frame = ttk.LabelFrame(self.content_frame, text="场景 (影响语义风格)", padding=10)
        scene_frame.pack(fill=tk.X, pady=(0,15))
        for i, scene in enumerate(["文本", "聊天", "邮件", "代码"]):
            ttk.Radiobutton(scene_frame, text=scene, value=scene, variable=self.template_scene_var).grid(row=0, column=i, padx=8, sticky=tk.W)
        # 智能场景切换（从“其他设置”移动至此）
        ttk.Checkbutton(scene_frame, text="智能场景切换（自动选择场景）", variable=self.smart_template_var).grid(row=1, column=0, columnspan=4, sticky=tk.W, pady=(6,0))

        # 提示词配置入口
        prompt_frame = ttk.LabelFrame(self.content_frame, text="提示词配置", padding=10)
        prompt_frame.pack(fill=tk.X, expand=False)
        ttk.Label(prompt_frame, text="编辑默认/场景提示词。保存后立即生效（写入config.json）。", foreground='gray').pack(anchor=tk.W)
        ttk.Button(prompt_frame, text="打开提示词配置", command=self.open_prompt_config_window).pack(anchor=tk.W, pady=(6,0))

        # 其他设置
        other = ttk.LabelFrame(self.content_frame, text="其他设置", padding=10)
        other.pack(fill=tk.X, pady=(15,0))
        self.auto_paste_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(other, text="自动粘贴识别结果", variable=self.auto_paste_var).pack(anchor=tk.W)
        self.minimize_to_tray_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(other, text="最小化到系统托盘", variable=self.minimize_to_tray_var).pack(anchor=tk.W)

    # 文案助手功能已移除（原位置保留占位，便于未来新增其它扩展按钮）
    # launch_frame = ttk.Frame(self.content_frame)
    # launch_frame.pack(fill=tk.X, pady=(18,10))
    # ttk.Separator(launch_frame, orient='horizontal').pack(fill=tk.X, pady=(0,8))
    # ttk.Button(launch_frame, text="🪄 打开文案助手", command=self.open_copywriting_assistant, width=20).pack(anchor=tk.W)

    # def open_copywriting_assistant(self):
    #     """文案助手功能已移除占位"""
    #     pass
    # 已移动：智能场景切换复选框在上方场景区域

    def save_prompts_from_ui(self):
        """从界面采集并保存提示词配置"""
        # 精简版：当前无多文本编辑控件，保留占位函数避免旧调用报错
        messagebox.showinfo("提示", "当前版本未开放自定义多场景提示词编辑。使用内置默认配置。")

    # ================= 内置提示词加载 =================
    def load_builtin_prompts_from_config(self):
        """加载内置默认与场景提示词：
        优先读取 config.json -> builtin_prompts: { default: str, scenes: {场景: str} }
        若不存在则写入默认模板（只写一次，避免每次覆盖用户自定义）。
        """
        default_fallback = (
            "用户口述文本发给你，你首先理解用户真实意图，尽量不更改口述文本的情况下，输出用户真实意图的文本。"
            "注意：即使用户口述是问句，你也不需要回答，只需输出用户想表达的文本。"
        )
        scenes_fallback = {
            '聊天': (
                "用户正在用聊天应用，根据用户口述输出自然、简洁、友好的聊天文本：\n"
                "- 保留原本语气（口语/轻松）\n- 修正明显错别字与语序\n- 不扩写无关内容，不加入解释\n- 只输出润色后的文本，不加前缀或说明。"
            ),
            '邮件': (
                "用户正在写邮件，请将用户口述整理 / 润色成一封正式、礼貌、结构清晰的邮件：\n"
                "要求：\n1. 保留关键信息与时间节点，不杜撰事实\n2. 语气自然、礼貌、简洁、专业\n3. 列表化条目可用有序或无序方式提升可读性。\n5.邮件格式规范，不要markdown格式。"
            ),
            '代码': (
                "用户正在编写代码，有问题想问你，但是你不用回答，只需要将问题文本进行润色：\n"
                "- 用户如果说文件名或代码行号，保留这些信息（例如：若说 legacy hold to talk 点 py，则输出 legacy_hold_to_talk.py）\n"
                "- 保留原本语气（口语/轻松）\n- 修正明显错别字与语序\n- 只输出润色后的文本，不加前缀或说明。"
            )
        }
        # 暴露 fallback 供“恢复出厂默认”使用
        self._builtin_default_fallback = default_fallback
        self._builtin_scenes_fallback = scenes_fallback
        try:
            cfg = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f) or {}
            builtin_cfg = cfg.get('builtin_prompts') or {}
            self.builtin_default_prompt = builtin_cfg.get('default') or default_fallback
            scenes_cfg = builtin_cfg.get('scenes') or {}
            # 只接受已知场景键；如果未来增加场景，可放宽
            merged = {}
            for k, v in scenes_fallback.items():
                merged[k] = scenes_cfg.get(k) or v
            self.builtin_scene_prompts = merged

            # 若文件中没有 builtin_prompts，则写入一次默认结构（不覆盖已有）
            if 'builtin_prompts' not in cfg:
                cfg['builtin_prompts'] = {
                    'default': self.builtin_default_prompt,
                    'scenes': self.builtin_scene_prompts
                }
                try:
                    with open(self.config_file, 'w', encoding='utf-8') as f:
                        json.dump(cfg, f, ensure_ascii=False, indent=2)
                except Exception as we:
                    print(f"写入默认 builtin_prompts 失败: {we}")
        except Exception as e:
            print(f"加载 builtin_prompts 失败，使用内置硬编码: {e}")
            self.builtin_default_prompt = default_fallback
            self.builtin_scene_prompts = scenes_fallback

    # ================= 提示词配置窗口 =================
    def open_prompt_config_window(self):
        # 若已存在窗口，聚焦
        if hasattr(self, '_prompt_cfg_win') and self._prompt_cfg_win and self._prompt_cfg_win.winfo_exists():
            self._prompt_cfg_win.lift(); self._prompt_cfg_win.focus_force(); return

        win = tk.Toplevel(self.root)
        win.title("提示词配置（用户 & 内置）")
        win.geometry("980x740")
        win.transient(self.root)
        self._prompt_cfg_win = win

        # 状态变量提前定义（供各内部函数使用）
        status_var = tk.StringVar(value='')

        # Notebook
        nb = ttk.Notebook(win)
        nb.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)
        user_tab = ttk.Frame(nb)
        builtin_tab = ttk.Frame(nb)
        nb.add(user_tab, text='用户自定义')
        nb.add(builtin_tab, text='内置模板')

        # ---------------- 用户自定义 ----------------
        ttk.Label(user_tab, text="默认提示词 (留空则回退内置默认)", font=('Arial', 11, 'bold')).pack(anchor=tk.W, padx=6, pady=(6,4))
        ut_default_text = tk.Text(user_tab, height=6, wrap=tk.WORD, font=('Consolas', 11))
        ut_default_text.pack(fill=tk.X, padx=8)
        if self.prompts.get('default'):
            ut_default_text.insert('1.0', self.prompts['default'])

        ut_scene_frame = ttk.LabelFrame(user_tab, text='场景提示词 (留空 = 使用默认或内置)', padding=8)
        ut_scene_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=8)
        ut_scene_canvas = tk.Canvas(ut_scene_frame, highlightthickness=0)
        ut_scene_scroll = ttk.Scrollbar(ut_scene_frame, orient='vertical', command=ut_scene_canvas.yview)
        ut_scene_inner = ttk.Frame(ut_scene_canvas)
        ut_scene_inner.bind('<Configure>', lambda e: ut_scene_canvas.configure(scrollregion=ut_scene_canvas.bbox('all')))
        ut_scene_canvas.create_window((0,0), window=ut_scene_inner, anchor='nw')
        ut_scene_canvas.configure(yscrollcommand=ut_scene_scroll.set)
        ut_scene_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ut_scene_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        user_scene_widgets = {}

        def _add_user_scene_row(scene_name: str, init_text: str = ''):
            if scene_name in user_scene_widgets:
                return
            row = ttk.Frame(ut_scene_inner)
            row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text=scene_name, width=10).pack(side=tk.LEFT, anchor=tk.N, padx=(0,4))
            txt = tk.Text(row, height=4, wrap=tk.WORD, font=('Consolas', 10))
            txt.pack(side=tk.LEFT, fill=tk.X, expand=True)
            if init_text:
                txt.insert('1.0', init_text)
            def _del():
                if messagebox.askyesno('确认', f'删除用户场景 “{scene_name}”？'):
                    row.destroy(); user_scene_widgets.pop(scene_name, None)
            ttk.Button(row, text='删除', width=6, command=_del).pack(side=tk.LEFT, padx=4)
            user_scene_widgets[scene_name] = txt

        for sc, val in (self.prompts.get('scenes') or {}).items():
            _add_user_scene_row(sc, val)

        add_user_bar = ttk.Frame(user_tab)
        add_user_bar.pack(fill=tk.X, padx=8, pady=(0,6))
        ttk.Label(add_user_bar, text='新增场景:').pack(side=tk.LEFT)
        ut_new_scene_var = tk.StringVar()
        ttk.Entry(add_user_bar, textvariable=ut_new_scene_var, width=16).pack(side=tk.LEFT, padx=6)
        def _user_add_scene():
            name = ut_new_scene_var.get().strip()
            if not name:
                return
            if name in user_scene_widgets:
                messagebox.showwarning('提示', '场景已存在'); return
            if len(name) > 20:
                messagebox.showwarning('提示', '名称过长 (<=20)'); return
            _add_user_scene_row(name)
            ut_new_scene_var.set('')
        ttk.Button(add_user_bar, text='添加场景', command=_user_add_scene).pack(side=tk.LEFT)

        # ---------------- 内置模板 ----------------
        ttk.Label(builtin_tab, text='内置默认提示词', font=('Arial', 11, 'bold')).pack(anchor=tk.W, padx=6, pady=(6,4))
        bt_default_text = tk.Text(builtin_tab, height=6, wrap=tk.WORD, font=('Consolas', 11))
        bt_default_text.pack(fill=tk.X, padx=8)
        bt_default_text.insert('1.0', self.builtin_default_prompt or '')

        bt_scene_frame = ttk.LabelFrame(builtin_tab, text='内置场景提示词 (影响“填充内置”与回退逻辑)', padding=8)
        bt_scene_frame.pack(fill=tk.BOTH, expand=True, padx=6, pady=8)
        bt_scene_canvas = tk.Canvas(bt_scene_frame, highlightthickness=0)
        bt_scene_scroll = ttk.Scrollbar(bt_scene_frame, orient='vertical', command=bt_scene_canvas.yview)
        bt_scene_inner = ttk.Frame(bt_scene_canvas)
        bt_scene_inner.bind('<Configure>', lambda e: bt_scene_canvas.configure(scrollregion=bt_scene_canvas.bbox('all')))
        bt_scene_canvas.create_window((0,0), window=bt_scene_inner, anchor='nw')
        bt_scene_canvas.configure(yscrollcommand=bt_scene_scroll.set)
        bt_scene_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        bt_scene_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        builtin_scene_widgets = {}

        def _add_builtin_scene_row(scene_name: str, init_text: str = ''):
            if scene_name in builtin_scene_widgets:
                return
            row = ttk.Frame(bt_scene_inner)
            row.pack(fill=tk.X, pady=4)
            ttk.Label(row, text=scene_name, width=10).pack(side=tk.LEFT, anchor=tk.N, padx=(0,4))
            txt = tk.Text(row, height=4, wrap=tk.WORD, font=('Consolas', 10))
            txt.pack(side=tk.LEFT, fill=tk.X, expand=True)
            if init_text:
                txt.insert('1.0', init_text)
            def _del():
                if messagebox.askyesno('确认', f'删除内置场景 “{scene_name}”？'):
                    row.destroy(); builtin_scene_widgets.pop(scene_name, None)
            ttk.Button(row, text='删除', width=6, command=_del).pack(side=tk.LEFT, padx=4)
            builtin_scene_widgets[scene_name] = txt

        for sc, val in (self.builtin_scene_prompts or {}).items():
            _add_builtin_scene_row(sc, val)

        add_builtin_bar = ttk.Frame(builtin_tab)
        add_builtin_bar.pack(fill=tk.X, padx=8, pady=(0,6))
        ttk.Label(add_builtin_bar, text='新增场景:').pack(side=tk.LEFT)
        bt_new_scene_var = tk.StringVar()
        ttk.Entry(add_builtin_bar, textvariable=bt_new_scene_var, width=16).pack(side=tk.LEFT, padx=6)
        def _builtin_add_scene():
            name = bt_new_scene_var.get().strip()
            if not name:
                return
            if name in builtin_scene_widgets:
                messagebox.showwarning('提示', '场景已存在'); return
            if len(name) > 20:
                messagebox.showwarning('提示', '名称过长 (<=20)'); return
            _add_builtin_scene_row(name)
            bt_new_scene_var.set('')
        ttk.Button(add_builtin_bar, text='添加场景', command=_builtin_add_scene).pack(side=tk.LEFT)

        def _fill_user_from_builtin():
            ut_default_text.delete('1.0', tk.END)
            ut_default_text.insert('1.0', bt_default_text.get('1.0', tk.END).strip())
            for sc in list(user_scene_widgets.keys()):
                user_scene_widgets[sc].master.destroy()
            user_scene_widgets.clear()
            for sc, w in builtin_scene_widgets.items():
                txt = w.get('1.0', tk.END).strip()
                _add_user_scene_row(sc, txt)
            status_var.set('已复制内置到用户 (未保存)')
        ttk.Button(add_builtin_bar, text='复制内置到用户', command=_fill_user_from_builtin).pack(side=tk.LEFT, padx=(10,0))

        # ---------------- 底部操作区 ----------------
        bottom_bar = ttk.Frame(win)
        bottom_bar.pack(fill=tk.X, padx=10, pady=(4,2))

        def _reload_from_file():
            try:
                if not os.path.exists(self.config_file):
                    status_var.set('config.json 不存在'); return
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
                p = data.get('prompts', {}) or {}
                ut_default_text.delete('1.0', tk.END)
                ut_default_text.insert('1.0', p.get('default',''))
                for sc in list(user_scene_widgets.keys()):
                    user_scene_widgets[sc].master.destroy()
                user_scene_widgets.clear()
                for sc, val in (p.get('scenes') or {}).items():
                    _add_user_scene_row(sc, val)
                bp = data.get('builtin_prompts', {}) or {}
                bt_default_text.delete('1.0', tk.END)
                bt_default_text.insert('1.0', bp.get('default',''))
                for sc in list(builtin_scene_widgets.keys()):
                    builtin_scene_widgets[sc].master.destroy()
                builtin_scene_widgets.clear()
                for sc, val in (bp.get('scenes') or {}).items():
                    _add_builtin_scene_row(sc, val)
                status_var.set('已重载')
            except Exception as e:
                messagebox.showerror('错误', f'重载失败: {e}')

        def _factory_reset():
            if not messagebox.askyesno('确认', '恢复出厂默认将重置内置模板，是否继续？'):
                return
            bt_default_text.delete('1.0', tk.END)
            bt_default_text.insert('1.0', self._builtin_default_fallback)
            for sc in list(builtin_scene_widgets.keys()):
                builtin_scene_widgets[sc].master.destroy()
            builtin_scene_widgets.clear()
            for sc, val in (self._builtin_scenes_fallback or {}).items():
                _add_builtin_scene_row(sc, val)
            if messagebox.askyesno('可选操作', '是否同时清空用户自定义提示词？'):
                ut_default_text.delete('1.0', tk.END)
                for sc in list(user_scene_widgets.keys()):
                    user_scene_widgets[sc].master.destroy()
                user_scene_widgets.clear()
            status_var.set('已恢复出厂默认 (未保存)')

        def _save_all():
            user_default = ut_default_text.get('1.0', tk.END).strip()
            user_scenes = {}
            for sc, w in user_scene_widgets.items():
                val = w.get('1.0', tk.END).strip()
                if val:
                    user_scenes[sc] = val
            prompts_payload = {'default': user_default, 'scenes': user_scenes}
            builtin_default = bt_default_text.get('1.0', tk.END).strip()
            builtin_scenes = {}
            for sc, w in builtin_scene_widgets.items():
                val = w.get('1.0', tk.END).strip()
                if val:
                    builtin_scenes[sc] = val
            builtin_payload = {'default': builtin_default, 'scenes': builtin_scenes}
            try:
                cfg = {}
                if os.path.exists(self.config_file):
                    with open(self.config_file, 'r', encoding='utf-8') as f:
                        cfg = json.load(f) or {}
                cfg['prompts'] = prompts_payload
                cfg['builtin_prompts'] = builtin_payload
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(cfg, f, ensure_ascii=False, indent=2)
                self.prompts = prompts_payload
                self.builtin_default_prompt = builtin_default
                self.builtin_scene_prompts = builtin_scenes
                status_var.set('已保存')
            except Exception as e:
                messagebox.showerror('保存失败', str(e))

        def _close():
            win.destroy()

        ttk.Button(bottom_bar, text='保存全部', command=_save_all).pack(side=tk.LEFT)
        ttk.Button(bottom_bar, text='恢复出厂默认', command=_factory_reset).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(bottom_bar, text='重载', command=_reload_from_file).pack(side=tk.LEFT, padx=(6,0))
        ttk.Button(bottom_bar, text='关闭', command=_close).pack(side=tk.RIGHT)
        ttk.Label(win, textvariable=status_var, foreground='green').pack(fill=tk.X, padx=12, pady=(2,6))
        win.bind('<Escape>', lambda e: _close())
    
    def show_help(self):
        """显示帮助页面"""
        self.clear_content()

        title = ttk.Label(self.content_frame, text="帮助", font=('Arial', 18, 'bold'))
        title.pack(anchor=tk.W, pady=(0, 20))

        help_text = (
            "使用说明：\n\n"
            "1. 设置快捷键\n"
            "    - 两种模式：\n"
            "      a) 按住说话：按住 Ctrl+Space（或自定义组合）开始，松开结束\n"
            "      b) 双击Ctrl：快速双击 Ctrl 开始录音；录音中再按一次 Ctrl 结束\n"
            "    - 在 设置 -> 快捷键模式 中切换；按住模式下可编辑快捷键组合\n\n"
            "2. 语音识别\n"
            "    - 按住模式：按住快捷键开始录音，松开结束\n"
            "    - 双击Ctrl模式：双击开始，单击结束\n"
            "    - 处理后的文本会自动粘贴到当前光标位置（若启用）\n\n"
            "3. 语言模式 + 场景\n"
            "    - 语言模式：中文 / 外语(英文输出)\n"
            "    - 场景：文本 / 聊天 / 邮件 / 代码\n"
            "    - 外语模式下所有场景统一英文输出；中文模式按中文提示词输出\n\n"
            "4. 智能场景切换\n"
            "    - 根据当前活动窗口自动选择 场景（不改变语言模式）\n"
            "    - 例如 IDE -> 代码，聊天软件 -> 聊天，邮件客户端 -> 邮件\n\n"
            "5. 自定义提示词\n"
            "    - 设置页面底部 ‘提示词配置’：\n"
            "      * ‘中文’ 标签：全局中文默认 system 提示词\n"
            "      * 其他场景标签：该场景（中文模式）专属；留空回退中文默认\n"
            "    - 优先级：场景中文提示词 > 中文默认提示词 > 内置默认\n"
            "    - 外语模式会在选定提示词后自动附加英文输出指令\n"
            "    - 点击 ‘保存提示词’ 写入 config.json (prompts)\n\n"
            "6. 系统托盘\n"
            "    - 可最小化到系统托盘，右键图标查看菜单\n\n"
            "注意：确保麦克风权限与网络连接正常。"
        )
        help_label = ttk.Label(self.content_frame, text=help_text, justify=tk.LEFT)
        help_label.pack(anchor=tk.W)
    
    def setup_hotkey(self):
        """设置全局快捷键"""
        try:
            keyboard.unhook_all()
            # 保护性获取模式值
            mode_var = getattr(self, 'hotkey_mode_var', None)
            mode = 'hold'
            try:
                if mode_var is not None:
                    mode = mode_var.get() or 'hold'
            except Exception:
                mode = 'hold'
            if mode == 'hold':
                # 解析快捷键组合并启动监控线程
                self.hotkey_parts = self.current_hotkey.lower().replace(' ', '').split('+')
                if not self.hotkey_thread or not self.hotkey_thread.is_alive():
                    self.hotkey_thread = threading.Thread(target=self.hotkey_monitor, daemon=True)
                    self.hotkey_thread.start()
                print(f"已设置按住模式快捷键: {self.current_hotkey}")
            else:
                # 双击Ctrl模式: 监听 Ctrl 释放
                self._last_ctrl_release_time = 0.0
                def _on_release(event):
                    try:
                        # 若当前处于程序内部模拟 Ctrl 阶段，则不触发双击逻辑
                        if getattr(self, '_suppress_ctrl_listener', False):
                            return
                        if event.name in ('ctrl', 'left ctrl', 'right ctrl'):
                            self.handle_double_ctrl_release()
                    except Exception as ee:
                        print(f"双击Ctrl监听错误: {ee}")
                keyboard.on_release(_on_release)
                print("已设置双击Ctrl模式: 快速双击Ctrl开始，录音中再按一次Ctrl结束")
        except Exception as e:
            messagebox.showerror("错误", f"设置快捷键失败: {e}")

    def handle_double_ctrl_release(self):
        """处理双击Ctrl逻辑: 双击开始，再按一次结束"""
        now = time.time()
        if not self.is_recording:
            # 双击判定
            if now - self._last_ctrl_release_time <= getattr(self, 'double_ctrl_interval', 0.5):
                self.start_recording()
                self._last_ctrl_release_time = 0.0
            else:
                self._last_ctrl_release_time = now
        else:
            self.stop_recording()
    
    def hotkey_monitor(self):
        """快捷键监控线程"""
        was_pressed = False
        
        while True:
            try:
                if getattr(self, 'hotkey_mode_var', None) and self.hotkey_mode_var.get() == 'hold':
                    # 如果正在抑制 Ctrl 监听（内部模拟复制），则跳过一次检测，避免误判
                    if getattr(self, '_suppress_ctrl_listener', False):
                        is_pressed = False
                    else:
                        is_pressed = self.is_hotkey_combination_pressed()
                    if is_pressed and not was_pressed:
                        if not self.is_recording:
                            self.root.after(0, self.start_recording)
                    elif was_pressed and not is_pressed:
                        if self.is_recording:
                            self.root.after(0, self.stop_recording)
                    was_pressed = is_pressed
                else:
                    was_pressed = False
                time.sleep(0.05)
            except Exception as e:
                print(f"快捷键监控错误: {e}")
                time.sleep(0.1)
    
    def is_hotkey_combination_pressed(self):
        """检查快捷键组合是否被按下"""
        try:
            for key_part in self.hotkey_parts:
                if key_part == 'ctrl':
                    if not (keyboard.is_pressed('ctrl') or keyboard.is_pressed('left ctrl') or keyboard.is_pressed('right ctrl')):
                        return False
                elif key_part == 'alt':
                    if not (keyboard.is_pressed('alt') or keyboard.is_pressed('left alt') or keyboard.is_pressed('right alt')):
                        return False
                elif key_part == 'shift':
                    if not (keyboard.is_pressed('shift') or keyboard.is_pressed('left shift') or keyboard.is_pressed('right shift')):
                        return False
                else:
                    if not keyboard.is_pressed(key_part):
                        return False
            return True
        except Exception as e:
            print(f"按键状态检查错误: {e}")
            return False
    
    def apply_hotkey(self):
        """应用新的快捷键设置"""
        new_hotkey = self.hotkey_var.get().strip()
        if new_hotkey:
            self.current_hotkey = new_hotkey
            if self.hotkey_mode_var.get() == 'hold':
                self.setup_hotkey()
            self.hotkey_label.config(text=f"快捷键: {self.current_hotkey}")
            # 保存到配置
            self.save_hotkey_config()
           
            messagebox.showinfo("成功", f"快捷键已更新为: {new_hotkey}")

    def on_hotkey_mode_change(self):
        """切换快捷键模式"""
        self.setup_hotkey()
        mode = self.hotkey_mode_var.get()
        # 更新侧边栏显示
        try:
            if mode == 'double_ctrl':
                self.hotkey_label.config(text="快捷键: 双击Ctrl")
            else:
                self.hotkey_label.config(text=f"快捷键: {self.current_hotkey}")
        except Exception:
            pass
        # 模式改变后保存配置
        self.save_hotkey_config()

    def load_hotkey_config(self):
        """从配置文件加载快捷键与模式
        返回 (hotkey, mode) 若不存在返回 (None, None)
        """
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                hotkey = cfg.get('hotkey') or cfg.get('current_hotkey')
                mode = cfg.get('hotkey_mode') or cfg.get('last_hotkey_mode')
                # 兼容旧值: 如果模式值不合法则返回None
                if mode not in ('hold', 'double_ctrl'):
                    mode = None
                return hotkey, mode
        except Exception as e:
            print(f"读取快捷键配置失败: {e}")
        return None, None

    # ================== 输出语言持久化相关 ==================
    def load_language_config(self):
        """读取上次保存的输出语言 (中文 / 英语)。不存在则返回 None"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f) or {}
                lang = cfg.get('output_language') or cfg.get('language_mode')  # 兼容备选key
                if lang in ('中文', '英语'):
                    return lang
        except Exception as e:
            print(f"读取语言配置失败: {e}")
        return None

    def save_language_config(self):
        """保存当前输出语言到 config.json，与原配置字段合并"""
        try:
            data = {}
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
            data['output_language'] = self.language_mode_var.get()
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"已保存输出语言: {data['output_language']}")
        except Exception as e:
            print(f"保存语言配置失败: {e}")

    def on_language_change(self):
        """语言单选按钮回调: 保存配置"""
        self.save_language_config()

    def load_prompts_config(self):
        """加载提示词配置结构
        期望结构:
        {
           "prompts": {
               "default": "...",
               "scenes": {"聊天": "...", "邮件": "...", ...}
           }
        }
        兼容旧无 prompts 的情形。
        """
        data = {}
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
        except Exception as e:
            print(f"读取提示词配置失败: {e}")
            data = {}

        prompts_section = data.get('prompts') or {}

        # default 视为中文默认（兼容旧 key '中文'）
        default_prompt = (
            prompts_section.get('default')
            or prompts_section.get('中文')
            or (self.builtin_default_prompt if hasattr(self, 'builtin_default_prompt') else "")
        )
        scenes = prompts_section.get('scenes') or {}

        return {'default': default_prompt, 'scenes': scenes}

    def save_prompts_config(self):
        """保存当前 self.prompts 到配置文件（合并原有字段）"""
        data = {}
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
        except Exception as e:
            print(f"读取原配置失败(保存提示词时): {e}")
            data = {}

        data.setdefault('prompts', {})
        data['prompts']['default'] = self.prompts.get('default') or self.builtin_default_prompt
        data['prompts']['scenes'] = self.prompts.get('scenes') or {}

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print("已保存提示词配置")
        except Exception as e:
            print(f"保存提示词配置失败: {e}")

    def save_hotkey_config(self):
        """保存当前快捷键与模式到配置文件（与现有 config.json 合并）"""
        data = {}
        # 读取现有配置以合并
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    data = json.load(f) or {}
        except Exception as e:
            print(f"读取旧配置合并失败: {e}")
            data = {}
        # 更新字段
        data['hotkey'] = self.current_hotkey
        data['hotkey_mode'] = self.hotkey_mode_var.get()
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"已保存快捷键配置: {data}")
        except Exception as e:
            print(f"保存快捷键配置失败: {e}")
    
    def get_active_window_process(self):
        """获取当前活动窗口的进程信息"""
        return _get_active_window_process()
    
    def get_smart_template(self):
        """根据当前活动窗口智能选择场景 (不含语言模式)"""
        if not self.smart_template_var.get():
            return self.template_scene_var.get()
        
        process_name, window_title = self.get_active_window_process()

        fallback = self.template_scene_var.get()
        scene = _suggest_scene(process_name, window_title, mapping=self.app_template_mapping, fallback=fallback)
        # 保留必要日志，便于排查
        if process_name and process_name in self.app_template_mapping:
            print(f"检测到应用: {process_name}, 自动切换场景: {scene}")
        elif window_title and scene != fallback:
            print(f"检测到窗口: {window_title}, 自动切换场景: {scene}")
        return scene
    
    def start_recording(self):
        """开始录音"""
        if self.is_recording:
            return
        
        try:
            self.is_recording = True
            self.status_label.config(text="状态: 录音中", foreground='red')
            # 播放开始录音音效
            self.play_sound('start')
            
            # 显示录音提示
            self.show_recording_indicator()
            
            # 创建识别器（如果不存在）
            if not self.recognizer:
                # 优先使用 service 层实现
                if getattr(self, 'runtime', None) and getattr(self.runtime, 'asr', None):
                    try:
                        self.recognizer = ServiceRecognizer(self)
                    except Exception as _sr_e:
                        print(f"初始化 ServiceRecognizer 失败，回退 CustomRecognizer: {_sr_e}")
                        self.recognizer = CustomRecognizer(self)
                else:
                    self.recognizer = CustomRecognizer(self)
            
            # 开始录音
            self.recognizer.start_session()
            print("开始录音...")
            
        except Exception as e:
            self.is_recording = False
            self.status_label.config(text="状态: 错误", foreground='red')
            self.hide_recording_indicator()
            messagebox.showerror("错误", f"开始录音失败: {e}")
    
    def stop_recording(self):
        """停止录音"""
        if not self.is_recording:
            return
        
        try:
            self.is_recording = False
            self.status_label.config(text="状态: 处理中", foreground='orange')
            # 播放结束录音音效
            self.play_sound('end')
            
            # 隐藏录音提示
            self.hide_recording_indicator()
            
            # 停止录音
            if self.recognizer:
                self.recognizer.stop_session()
            
            print("停止录音...")
            
        except Exception as e:
            self.status_label.config(text="状态: 错误", foreground='red')
            self.hide_recording_indicator()
            messagebox.showerror("错误", f"停止录音失败: {e}")
    
    def on_recognition_complete(self, original_text: str, formatted_text: str, word_count: int):
        """录音识别完成回调"""
        self.status_label.config(text="状态: 待机", foreground='green')
        
        # 更新统计数据 - 使用实际录音时长
        recording_duration = getattr(self, 'last_recording_duration', 0)
        print(f"本次录音时长: {recording_duration}秒")
        self.update_stats(word_count, recording_duration)
        
        # 保存转录记录
        transcript = {
            "timestamp": datetime.now().isoformat(),
            "original": original_text,
            "formatted": formatted_text,
            "word_count": word_count
        }
        self.transcripts.insert(0, transcript)
        
        # 限制记录数量
        if len(self.transcripts) > 1000:
            self.transcripts = self.transcripts[:1000]
        
        # 保存数据
        self.save_data()
        
        # 更新界面
        self.update_stats_display()
        self.update_recent_transcripts()
        
        print(f"识别完成: {word_count}词")
    
    def update_stats(self, words: int, time_seconds: int):
        """更新统计数据"""
        print(f"统计更新: +{words}字, +{time_seconds}秒")
        self.stats['total_words'] += words
        self.stats['total_time'] += time_seconds
        self.stats['sessions_count'] += 1
        print(f"累计统计: {self.stats['total_words']}字, {self.stats['total_time']}秒")
        
        # 更新最近30天数据
        today = datetime.now().date().isoformat()
        found = False
        for day_data in self.stats['last_30_days']:
            if day_data['date'] == today:
                day_data['words'] += words
                day_data['sessions'] += 1
                found = True
                break
        
        if not found:
            self.stats['last_30_days'].append({
                'date': today,
                'words': words,
                'sessions': 1
            })
        
        # 保持最近30天
        cutoff_date = (datetime.now() - timedelta(days=30)).date().isoformat()
        self.stats['last_30_days'] = [
            day for day in self.stats['last_30_days'] 
            if day['date'] >= cutoff_date
        ]
    
    def update_stats_display(self):
        """更新统计显示"""
        try:
            if hasattr(self, 'stats_cards') and self.stats_cards:
                # 检查words组件
                if 'words' in self.stats_cards:
                    widget = self.stats_cards['words']
                    if hasattr(widget, 'winfo_exists') and widget.winfo_exists():
                        widget.config(text=str(self.stats['total_words']))
                
                # 检查time组件
                if 'time' in self.stats_cards:
                    widget = self.stats_cards['time']
                    if hasattr(widget, 'winfo_exists') and widget.winfo_exists():
                        widget.config(text=self.format_time(self.stats['total_time']))
                
                # 检查wmp组件
                if 'wmp' in self.stats_cards:
                    widget = self.stats_cards['wmp']
                    if hasattr(widget, 'winfo_exists') and widget.winfo_exists():
                        widget.config(text=str(self.calculate_wpm()))
        except Exception as e:
            print(f"更新统计显示出错: {e}")
    
    def update_transcripts_display(self):
        """更新转录记录显示"""
        try:
            if hasattr(self, 'transcript_tree') and hasattr(self.transcript_tree, 'winfo_exists') and self.transcript_tree.winfo_exists():
                # 清空现有数据
                for item in self.transcript_tree.get_children():
                    self.transcript_tree.delete(item)
                
                # 添加转录记录
                for transcript in self.transcripts[:100]:  # 只显示最近100条
                    time_str = datetime.fromisoformat(transcript['timestamp']).strftime('%m-%d %H:%M')
                    original = transcript['original'][:50] + "..." if len(transcript['original']) > 50 else transcript['original']
                    formatted = transcript['formatted'][:50] + "..." if len(transcript['formatted']) > 50 else transcript['formatted']
                    
                    self.transcript_tree.insert('', 'end', values=(
                        time_str,
                        original,
                        formatted,
                        transcript['word_count']
                    ))
        except tk.TclError:
            # GUI组件已被销毁，忽略错误
            pass
    
    def update_recent_transcripts(self):
        """更新最近转录显示"""
        try:
            if hasattr(self, 'recent_text') and hasattr(self.recent_text, 'winfo_exists') and self.recent_text.winfo_exists():
                self.recent_text.delete(1.0, tk.END)
                
                for transcript in self.transcripts[:5]:  # 显示最近5条
                    time_str = datetime.fromisoformat(transcript['timestamp']).strftime('%H:%M')
                    self.recent_text.insert(tk.END, f"[{time_str}] {transcript['formatted']}\n\n")
        except tk.TclError:
            # GUI组件已被销毁，忽略错误
            pass
    
    def filter_transcripts(self, event=None):
        """过滤转录记录"""
        try:
            if not hasattr(self, 'transcript_tree') or not hasattr(self.transcript_tree, 'winfo_exists') or not self.transcript_tree.winfo_exists():
                return
            
            search_text = self.search_var.get().lower()
            
            # 清空现有数据
            for item in self.transcript_tree.get_children():
                self.transcript_tree.delete(item)
            
            # 添加匹配的记录
            for transcript in self.transcripts:
                if (search_text in transcript['original'].lower() or 
                    search_text in transcript['formatted'].lower()):
                    
                    time_str = datetime.fromisoformat(transcript['timestamp']).strftime('%m-%d %H:%M')
                    original = transcript['original'][:50] + "..." if len(transcript['original']) > 50 else transcript['original']
                    formatted = transcript['formatted'][:50] + "..." if len(transcript['formatted']) > 50 else transcript['formatted']
                    
                    self.transcript_tree.insert('', 'end', values=(
                        time_str,
                        original,
                        formatted,
                        transcript['word_count']
                    ))
        except tk.TclError:
            # GUI组件已被销毁，忽略错误
            pass
    
    def format_time(self, seconds: int) -> str:
        """格式化时间显示"""
        if seconds < 60:
            return f"{seconds}秒"
        elif seconds < 3600:
            return f"{seconds//60}分{seconds%60}秒"
        else:
            hours = seconds // 3600
            minutes = (seconds % 3600) // 60
            return f"{hours}时{minutes}分"
    
    def calculate_wmp(self) -> int:
        """计算平均每分钟字数（CPM - Characters Per Minute）"""
        if self.stats['total_time'] == 0:
            return 0
        return int(self.stats['total_words'] / (self.stats['total_time'] / 60))
    
    # 保持向后兼容
    def calculate_wpm(self) -> int:
        """计算平均每分钟字数（CPM - Characters Per Minute）"""
        return self.calculate_wmp()
    
    def test_recording(self):
        """测试录音功能"""
        messagebox.showinfo("测试", f"请按快捷键 {self.current_hotkey} 开始测试录音")
    
    def clear_stats(self):
        """清空统计数据"""
        if messagebox.askyesno("确认", "确定要清空所有统计数据吗？"):
            self.stats = self.default_stats()
            self.transcripts = []
            self.save_data()
            self.update_stats_display()
            self.update_transcripts_display()
            self.update_recent_transcripts()
            messagebox.showinfo("完成", "统计数据已清空")
    
    def export_data(self):
        """导出数据"""
        try:
            export_data = {
                "stats": self.stats,
                "transcripts": self.transcripts,
                "export_time": datetime.now().isoformat()
            }
            
            filename = f"voice_data_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, ensure_ascii=False, indent=2)
            
            messagebox.showinfo("成功", f"数据已导出到: {filename}")
        except Exception as e:
            messagebox.showerror("错误", f"导出失败: {e}")
    
    def create_tray_icon(self):
        """创建系统托盘图标"""
        try:
            # 创建一个简单的图标
            width = height = 16
            image = Image.new('RGB', (width, height), color='blue')
            draw = ImageDraw.Draw(image)
            draw.ellipse([2, 2, width-2, height-2], fill='white')
            
            menu = pystray.Menu(
                pystray.MenuItem("显示", self.show_window),
                pystray.MenuItem("退出", self.quit_app)
            )
            
            self.tray_icon = pystray.Icon("VoiceRecognition", image, "语音识别助手", menu)
            
            # 在单独线程中运行托盘图标
            threading.Thread(target=self.tray_icon.run, daemon=True).start()
        except Exception as e:
            print(f"创建系统托盘失败: {e}")
            self.tray_icon = None
    
    def show_window(self, icon=None, item=None):
        """显示窗口"""
        self.root.deiconify()
        self.root.lift()
    
    def create_recording_indicator(self):
        """创建录音提示窗口"""
        if self.recording_indicator is not None:
            return
            
        # 创建顶层窗口
        self.recording_indicator = tk.Toplevel()
        self.recording_indicator.title("")
        self.recording_indicator.geometry("200x80")
        
        # 设置窗口属性
        self.recording_indicator.overrideredirect(True)  # 无边框
        self.recording_indicator.attributes('-topmost', True)  # 置顶
        self.recording_indicator.attributes('-alpha', 0.9)  # 半透明
        self.recording_indicator.configure(bg='#FF4444')  # 红色背景
        
        # 右侧贴边显示
        screen_width = self.recording_indicator.winfo_screenwidth()
        screen_height = self.recording_indicator.winfo_screenheight()
        x = screen_width - 200  # 贴到右边缘
        y = (screen_height - 80) // 2  # 垂直居中
        self.recording_indicator.geometry(f"200x80+{x}+{y}")
        
        # 添加内容
        frame = tk.Frame(self.recording_indicator, bg='#FF4444')
        frame.pack(fill=tk.BOTH, expand=True)
        
        # 录音图标和文字
        icon_label = tk.Label(frame, text="🎤", font=('Arial', 24), 
                             bg='#FF4444', fg='white')
        icon_label.pack(pady=5)
        
        text_label = tk.Label(frame, text="录音中...", font=('Arial', 12, 'bold'), 
                             bg='#FF4444', fg='white')
        text_label.pack()
        
        # 隐藏窗口（初始状态）
        self.recording_indicator.withdraw()
    
    def show_recording_indicator(self):
        """显示录音提示"""
        if self.recording_indicator is None:
            self.create_recording_indicator()
        # 再次判定，保证非 None（类型守卫）
        indicator = self.recording_indicator
        if indicator is not None:
            indicator.deiconify()  # type: ignore[attr-defined]
            indicator.lift()       # type: ignore[attr-defined]
    
    def hide_recording_indicator(self):
        """隐藏录音提示"""
        if self.recording_indicator is not None:
            self.recording_indicator.withdraw()

    def hide_window(self):
        """隐藏窗口"""
        self.root.withdraw()
    
    def quit_app(self, icon=None, item=None):
        """退出应用"""
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except:
            pass
        
        try:
            self.save_data()
        except:
            pass
        
        try:
            self.root.quit()
        except:
            pass
        
        try:
            self.root.destroy()
        except:
            pass
    
    def on_closing(self):
        """窗口关闭事件"""
        # 默认最小化到托盘
        self.hide_window()
    
    def update_timer(self):
        """定时更新"""
        try:
            # 智能场景切换：若开启则根据当前前台窗口自动勾选场景单选按钮
            if getattr(self, 'smart_template_var', None) and self.smart_template_var.get():
                scene = None
                try:
                    scene = self.get_smart_template()
                except Exception as _e:
                    scene = None
                # 若检测出的场景与当前显示不同，则更新UI变量（不改变语言）
                if scene and scene != self.template_scene_var.get():
                    # 仅在设置页面存在单选按钮时更新，避免用户在其它页面时频繁切换造成潜在困惑
                    # 这里简单判断 settings 页是否存在：检查某个独有控件，如 hotkey_var 是否存在
                    if hasattr(self, 'hotkey_var'):
                        self.template_scene_var.set(scene)
            # 你还可以在这里扩展更多周期性任务
        finally:
            # 继续下一次调度
            self.root.after(1000, self.update_timer)
    
    def run(self):
        """运行应用"""
        # 创建系统托盘
        self.create_tray_icon()
        
        # 启动GUI
        try:
            self.root.mainloop()
        except KeyboardInterrupt:
            self.quit_app()

    def preload_sounds(self):
        """预加载音效数据到内存，短 wav 减少播放时 I/O.
        若 soundfile 缺失或文件不存在则忽略。该操作只执行一次。
        """
        if self._sound_preloaded:
            return
        self._sound_preloaded = True
        if sf is None:
            return
        base_dir = os.path.dirname(__file__)
        mapping = {'start': 'start_rec.wav', 'end': 'end_rec.wav'}
        for key, fname in mapping.items():
            path = os.path.join(base_dir, 'assets', fname)
            if os.path.exists(path):
                try:
                    data, sr = sf.read(path, dtype='float32')
                    self._sound_cache[key] = (data, sr)
                except Exception as e:
                    print(f"预加载音效失败 {fname}: {e}")
            else:
                # 不打印频繁警告，预加载阶段只记录一次
                print(f"预加载跳过(不存在): {path}")

    # ================== 音效播放相关（新增） ==================
    def play_sound(self, which: str):
        """播放开始/结束录音音效 (wav)
        which: 'start' 或 'end'
        使用单独线程，避免阻塞 GUI。若文件不存在则打印警告后忽略。
        仅支持 wav：assets/start_rec.wav, assets/end_rec.wav
        优先使用预加载缓存。
        """
        if which not in ('start', 'end'):
            return
        # 若尚未预加载，尝试触发一次（懒加载）
        if not self._sound_preloaded:
            self.preload_sounds()
        threading.Thread(target=self._play_sound_cached_or_load, args=(which,), daemon=True).start()

    # ================== 选中文本润色功能 ==================

    def _play_sound_cached_or_load(self, which: str):
        if sf is None:
            return
        # 1. 直接用缓存
        if which in self._sound_cache:
            data, sr = self._sound_cache[which]
            try:
                sd.play(data, sr, blocking=True)
            except Exception as e:
                print(f"音效播放失败(缓存): {e}")
            return
        # 2. 缓存没有 -> 尝试磁盘读取一次并放入缓存
        base_dir = os.path.dirname(__file__)
        fname = 'start_rec.wav' if which == 'start' else 'end_rec.wav'
        path = os.path.join(base_dir, 'assets', fname)
        if not os.path.exists(path):
            print(f"音效文件不存在(跳过): {path}")
            return
        try:
            data, sr = sf.read(path, dtype='float32')
            self._sound_cache[which] = (data, sr)
            sd.play(data, sr, blocking=True)
        except Exception as e:
            print(f"播放音效失败(磁盘加载): {e} -> {path}")

    # 保留旧的 _play_sound_file 名称兼容（不再直接使用）
    def _play_sound_file(self, path: str):
        if sf is None:
            print("soundfile 未安装，无法播放: ", path)
            return
        try:
            data, samplerate = sf.read(path, dtype='float32')
            sd.play(data, samplerate, blocking=True)
        except Exception as e:
            print(f"播放音效失败: {e} -> {path}\n若文件为 mp3，可先转换: from pydub import AudioSegment; AudioSegment.from_mp3('x.mp3').export('x.wav', format='wav')")


 
            
if __name__ == "__main__":
    app = VoiceRecognitionGUI()
    app.run()