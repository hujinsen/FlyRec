#!/usr/bin/env python3
"""
测试智能模板切换功能
"""

import sys
try:
    import psutil
    import win32gui
    import win32process
    SMART_TEMPLATE_AVAILABLE = True
except ImportError:
    SMART_TEMPLATE_AVAILABLE = False
    print("警告: psutil 或 pywin32 未安装，智能模板切换功能将不可用")

def get_active_window_process():
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

def get_smart_template(process_name, window_title):
    """根据当前活动窗口智能选择模板"""
    
    # 应用程序模板映射
    app_template_mapping = {
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
        
        # 默认应用
        'notepad.exe': '默认',
        'wordpad.exe': '默认',
        'winword.exe': '默认',
        'excel.exe': '默认',
        'powerpnt.exe': '默认',
    }
    
    if process_name:
        # 检查进程名映射
        if process_name in app_template_mapping:
            template = app_template_mapping[process_name]
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
    
    # 默认返回默认模板
    return '默认'

if __name__ == "__main__":
    print("智能模板切换功能测试")
    print("=" * 50)
    
    if not SMART_TEMPLATE_AVAILABLE:
        print("❌ 智能模板切换功能不可用")
        sys.exit(1)
    
    print("✅ 智能模板切换功能可用")
    
    # 获取当前活动窗口信息
    process_name, window_title = get_active_window_process()
    
    print(f"当前活动窗口:")
    print(f"  进程名: {process_name}")
    print(f"  窗口标题: {window_title}")
    
    # 获取推荐模板
    template = get_smart_template(process_name, window_title)
    print(f"  推荐模板: {template}")
    
    print("\n测试完成！")