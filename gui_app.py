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
from demo4 import HoldToTalkRecognizer
import keyboard
import sys
try:
    import psutil
    import win32gui
    import win32process
    SMART_TEMPLATE_AVAILABLE = True
except ImportError:
    SMART_TEMPLATE_AVAILABLE = False
    print("警告: psutil 或 pywin32 未安装，智能模板切换功能将不可用")


class VoiceRecognitionGUI:
    """语音识别工具图形界面"""
    
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("FlyRecDemo")
        self.root.geometry("800x600")
        
        # 数据存储
        self.stats_file = "voice_stats.json"
        self.transcripts_file = "transcripts.json"
        self.load_data()
        
        # 语音识别器
        self.recognizer = None
        self.is_recording = False
        self.current_hotkey = "ctrl+space"
        
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
        self.template_var = tk.StringVar(value="默认")
        self.smart_template_var = tk.BooleanVar(value=True)  # 智能模板切换开关
        
        # 应用程序模板映射
        self.app_template_mapping = {
            # 聊天应用
            'wechat.exe': '聊天',
            'qq.exe': '聊天', 
            'qqscm.exe': '聊天',
            'dingtalk.exe': '聊天',
            'teams.exe': '聊天',
            'slack.exe': '聊天',
            'telegram.exe': '聊天',
            'discord.exe': '聊天',
            
            # 邮件应用
            'outlook.exe': '邮件',
            'thunderbird.exe': '邮件',
            'foxmail.exe': '邮件',
            'mailmaster.exe': '邮件',
            
            # 代码编辑器
            'code.exe': '代码',
            'devenv.exe': '代码',
            'pycharm64.exe': '代码',
            'idea64.exe': '代码',
            'notepad++.exe': '代码',
            'sublime_text.exe': '代码',
            'atom.exe': '代码',
            'webstorm64.exe': '代码',
            'phpstorm64.exe': '代码',
            'codebuddy.exe': '代码',  # 添加CodeBuddy支持
            
            # 默认应用
            'notepad.exe': '默认',
            'wordpad.exe': '默认',
            'winword.exe': '默认',
            'excel.exe': '默认',
            'powerpnt.exe': '默认',
        }
        
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
        title_label = ttk.Label(sidebar, text="FlyRecDemo", font=('Arial', 16, 'bold'))
        title_label.pack(pady=(0, 20))
        
        # 导航按钮
        nav_buttons = [
            ("📊 仪表板", self.show_dashboard),
            ("🎤 识别记录", self.show_transcripts),
            ("⚙️ 设置", self.show_settings),
            ("❓ 帮助", self.show_help)
        ]
        
        self.nav_buttons = {}
        for text, command in nav_buttons:
            btn = ttk.Button(sidebar, text=text, command=command, width=20)
            btn.pack(pady=2, fill=tk.X)
            self.nav_buttons[text] = btn
        
        # 状态指示
        ttk.Separator(sidebar, orient='horizontal').pack(fill=tk.X, pady=10)
        
        self.status_label = ttk.Label(sidebar, text="状态: 待机", foreground='green')
        self.status_label.pack()
        
        self.hotkey_label = ttk.Label(sidebar, text=f"快捷键: {self.current_hotkey}")
        self.hotkey_label.pack(pady=(5, 0))
    
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
        
        # 快捷操作
        actions_frame = ttk.LabelFrame(self.content_frame, text="快捷操作", padding=10)
        actions_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Button(actions_frame, text="开始录音测试", 
                  command=self.test_recording).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions_frame, text="清空统计", 
                  command=self.clear_stats).pack(side=tk.LEFT, padx=5)
        ttk.Button(actions_frame, text="导出数据", 
                  command=self.export_data).pack(side=tk.LEFT, padx=5)
        
        # 最近转录
        recent_frame = ttk.LabelFrame(self.content_frame, text="最近转录", padding=10)
        recent_frame.pack(fill=tk.BOTH, expand=True)
        
        self.recent_text = scrolledtext.ScrolledText(recent_frame, height=10, wrap=tk.WORD)
        self.recent_text.pack(fill=tk.BOTH, expand=True)
        
        # 显示最近的转录
        self.update_recent_transcripts()
    
    def show_transcripts(self):
        """显示识别记录"""
        self.clear_content()
        
        title = ttk.Label(self.content_frame, text="识别记录", font=('Arial', 18, 'bold'))
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
    
    def show_settings(self):
        """显示设置页面"""
        self.clear_content()
        
        title = ttk.Label(self.content_frame, text="设置", font=('Arial', 18, 'bold'))
        title.pack(anchor=tk.W, pady=(0, 20))
        
        # 快捷键设置
        hotkey_frame = ttk.LabelFrame(self.content_frame, text="快捷键设置", padding=10)
        hotkey_frame.pack(fill=tk.X, pady=(0, 20))
        
        ttk.Label(hotkey_frame, text="当前快捷键:").grid(row=0, column=0, sticky=tk.W)
        self.hotkey_var = tk.StringVar(value=self.current_hotkey)
        hotkey_entry = ttk.Entry(hotkey_frame, textvariable=self.hotkey_var)
        hotkey_entry.grid(row=0, column=1, padx=(10, 0), sticky=tk.W)
        
        ttk.Button(hotkey_frame, text="应用", 
                  command=self.apply_hotkey).grid(row=0, column=2, padx=(10, 0))
        
        ttk.Label(hotkey_frame, text="提示: 使用 ctrl+space 格式", 
                 foreground='gray').grid(row=1, column=0, columnspan=3, sticky=tk.W, pady=(5, 0))
        
        # 文本处理模板
        template_frame = ttk.LabelFrame(self.content_frame, text="文本处理模板", padding=10)
        template_frame.pack(fill=tk.BOTH, expand=True)
        
        self.template_var = tk.StringVar(value="默认")
        templates = ["默认", "邮件", "代码", "聊天"]
        
        for i, template in enumerate(templates):
            ttk.Radiobutton(template_frame, text=template, variable=self.template_var, 
                           value=template).grid(row=0, column=i, padx=10, sticky=tk.W)
        
        # 其他设置
        other_frame = ttk.LabelFrame(self.content_frame, text="其他设置", padding=10)
        other_frame.pack(fill=tk.X, pady=(20, 0))
        
        self.auto_paste_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(other_frame, text="自动粘贴识别结果", 
                       variable=self.auto_paste_var).pack(anchor=tk.W)
        
        self.minimize_to_tray_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(other_frame, text="最小化到系统托盘", 
                       variable=self.minimize_to_tray_var).pack(anchor=tk.W)
        
        self.smart_template_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(other_frame, text="智能模板切换（根据当前应用自动选择模板）", 
                       variable=self.smart_template_var).pack(anchor=tk.W)
    
    def show_help(self):
        """显示帮助页面"""
        self.clear_content()
        
        title = ttk.Label(self.content_frame, text="帮助", font=('Arial', 18, 'bold'))
        title.pack(anchor=tk.W, pady=(0, 20))
        
        help_text = """
使用说明：

1. 设置快捷键
   - 在设置页面可以自定义全局快捷键
   - 默认快捷键为 Ctrl+Space
   - 支持组合键，如 ctrl+alt+v

2. 语音识别
   - 按住快捷键开始录音
   - 松开快捷键结束录音并处理
   - 处理后的文本会自动粘贴到当前光标位置

3. 智能模板切换
   - 系统会自动检测当前活动窗口
   - 根据应用类型自动选择合适的模板
   - 支持聊天、邮件、代码、默认四种模板

4. 文本处理模板
   - 默认：去除语气词，修正错误
   - 邮件：格式化为正式邮件
   - 代码：生成代码实现
   - 聊天：生成聊天回复

5. 系统托盘
   - 可以最小化到系统托盘
   - 右键托盘图标查看菜单

注意事项：
- 确保麦克风权限已开启
- 需要网络连接进行语音识别
- 首次使用需要配置 API Key
        """
        
        help_label = ttk.Label(self.content_frame, text=help_text, justify=tk.LEFT)
        help_label.pack(anchor=tk.W)
    
    def setup_hotkey(self):
        """设置全局快捷键"""
        try:
            # 移除旧的快捷键监听器
            keyboard.unhook_all()
            
            # 解析快捷键组合
            self.hotkey_parts = self.current_hotkey.lower().replace(' ', '').split('+')
            
            # 启动快捷键检测线程
            self.hotkey_thread = threading.Thread(target=self.hotkey_monitor, daemon=True)
            self.hotkey_thread.start()
            
            print(f"已设置快捷键: {self.current_hotkey}")
        except Exception as e:
            messagebox.showerror("错误", f"设置快捷键失败: {e}")
    
    def hotkey_monitor(self):
        """快捷键监控线程"""
        was_pressed = False
        
        while True:
            try:
                # 检查快捷键组合是否被按下
                is_pressed = self.is_hotkey_combination_pressed()
                
                # 状态改变时触发相应动作
                if is_pressed and not was_pressed:
                    # 快捷键刚被按下
                    if not self.is_recording:
                        self.root.after(0, self.start_recording)
                elif was_pressed and not is_pressed:
                    # 快捷键刚被释放
                    if self.is_recording:
                        self.root.after(0, self.stop_recording)
                
                was_pressed = is_pressed
                time.sleep(0.05)  # 50ms 检查间隔
                
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
            self.setup_hotkey()
            self.hotkey_label.config(text=f"快捷键: {self.current_hotkey}")
            messagebox.showinfo("成功", f"快捷键已更新为: {new_hotkey}")
    
    def get_active_window_process(self):
        """获取当前活动窗口的进程信息"""
        if not SMART_TEMPLATE_AVAILABLE:
            return None, None
            
        try:
            # 获取前台窗口句柄
            hwnd = win32gui.GetForegroundWindow()
            if hwnd == 0:
                return None, None
            
            # 获取窗口标题
            window_title = win32gui.GetWindowText(hwnd)
            
            # 获取进程ID
            _, process_id = win32process.GetWindowThreadProcessId(hwnd)
            
            # 获取进程信息
            try:
                process = psutil.Process(process_id)
                process_name = process.name().lower()
                return process_name, window_title
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                return None, window_title
                
        except Exception as e:
            print(f"获取活动窗口信息失败: {e}")
            return None, None
    
    def get_smart_template(self):
        """根据当前活动窗口智能选择模板"""
        if not self.smart_template_var.get():
            return self.template_var.get()
        
        process_name, window_title = self.get_active_window_process()
        
        if process_name:
            # 检查进程名映射
            if process_name in self.app_template_mapping:
                template = self.app_template_mapping[process_name]
                print(f"检测到应用: {process_name}, 自动切换模板: {template}")
                return template
            
            # 检查窗口标题关键词
            if window_title:
                title_lower = window_title.lower()
                if any(keyword in title_lower for keyword in ['微信', 'wechat', 'qq', '钉钉']):
                    print(f"检测到聊天窗口: {window_title}, 切换到聊天模板")
                    return '聊天'
                elif any(keyword in title_lower for keyword in ['邮件', 'mail', 'outlook', '邮箱']):
                    print(f"检测到邮件窗口: {window_title}, 切换到邮件模板")
                    return '邮件'
                elif any(keyword in title_lower for keyword in ['code', 'visual studio', 'pycharm', 'idea']):
                    print(f"检测到代码编辑器: {window_title}, 切换到代码模板")
                    return '代码'
        
        # 默认返回用户设置的模板
        return self.template_var.get()
    
    def start_recording(self):
        """开始录音"""
        if self.is_recording:
            return
        
        try:
            self.is_recording = True
            self.status_label.config(text="状态: 录音中", foreground='red')
            
            # 显示录音提示
            self.show_recording_indicator()
            
            # 创建识别器（如果不存在）
            if not self.recognizer:
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
                        widget.config(text=str(self.calculate_wmp()))
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
        self.recording_indicator.deiconify()
        self.recording_indicator.lift()
    
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
        # 这里可以添加定时更新的逻辑
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


class CustomRecognizer(HoldToTalkRecognizer):
    """自定义识别器，集成GUI回调"""
    
    def __init__(self, gui_app):
        super().__init__()
        self.gui_app = gui_app
        self.start_time = None
    
    def start_session(self):
        """重写开始会话方法，记录开始时间"""
        import time
        self.start_time = time.time()
        super().start_session()
    
    def stop_session(self):
        """重写停止会话方法，添加GUI回调"""
        if not self._running:
            return
        
        # 计算录音时长
        import time
        recording_duration = 0
        if self.start_time:
            recording_duration = int(time.time() - self.start_time)
            self.gui_app.last_recording_duration = recording_duration
        
        print('Stop recognition session')
        self._running = False
        
        if self._audio_thread is not None:
            self._audio_thread.join()
        
        if self._recognition is not None:
            self._recognition.stop()
        
        # 清理资源
        if self._stream is not None:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        
        if self._mic is not None:
            try:
                self._mic.terminate()
            except Exception:
                pass
        
        self._stream = None
        self._mic = None
        self._recognition = None
        self._audio_thread = None
        self._callback = None
        
        # 处理结果
        with self._results_lock:
            results = getattr(self, '_results', [])
            
            if results:
                final_text = ' '.join(results)
                print('Final recognition result:\n' + final_text)
                
                # 使用智能模板选择
                template = self.gui_app.get_smart_template() if hasattr(self.gui_app, 'get_smart_template') else "默认"
                
                # 选择消息模板
                if template == "邮件":
                    from demo4 import EMAIL_MESSAGE
                    messages = EMAIL_MESSAGE.copy()
                elif template == "代码":
                    from demo4 import CODE_MESSAGE
                    messages = CODE_MESSAGE.copy()
                elif template == "聊天":
                    from demo4 import CHAT_MESSAGE
                    messages = CHAT_MESSAGE.copy()
                else:
                    from demo4 import DEFAULT_MESSAGE
                    messages = DEFAULT_MESSAGE.copy()
                
                messages[-1]['content'] = final_text
                
                try:
                    formatted = self._format_text.generate(messages)
                    if formatted:
                        formatted_content = formatted.get("output", {}).get("choices", [])[0].get("message", {}).get("content", "")
                        print('Formatted text:\n' + formatted_content)
                        
                        # 自动粘贴（如果启用）
                        if hasattr(self.gui_app, 'auto_paste_var') and self.gui_app.auto_paste_var.get():
                            try:
                                import pyperclip
                                import pyautogui
                                import time
                                
                                # 复制到剪贴板
                                pyperclip.copy(formatted_content)
                                print(f"已复制到剪贴板: {formatted_content[:50]}...")
                                
                                # 短暂延迟确保复制完成
                                time.sleep(0.1)
                                
                                # 模拟粘贴
                                pyautogui.hotkey("ctrl", "v")
                                print("已执行粘贴操作")
                                
                            except Exception as paste_error:
                                print(f"自动粘贴失败: {paste_error}")
                        
                        # 回调GUI - 中文按字符数统计更准确
                        word_count = len([c for c in final_text if c.isalnum()])
                        # 使用after方法确保在主线程中执行GUI更新
                        self.gui_app.root.after(0, lambda: self.gui_app.on_recognition_complete(final_text, formatted_content, word_count))
                    else:
                        print('No formatted response received.')
                        word_count = len([c for c in final_text if c.isalnum()])
                        # 使用after方法确保在主线程中执行GUI更新
                        self.gui_app.root.after(0, lambda: self.gui_app.on_recognition_complete(final_text, final_text, word_count))
                        
                except Exception as e:
                    print(f'格式化文本失败: {e}')
                    word_count = len([c for c in final_text if c.isalnum()])
                    # 使用after方法确保在主线程中执行GUI更新
                    self.gui_app.root.after(0, lambda: self.gui_app.on_recognition_complete(final_text, final_text, word_count))
            else:
                print('No final recognition result.')
            
            # 清空结果
            self._results = []


if __name__ == "__main__":
    app = VoiceRecognitionGUI()
    app.run()