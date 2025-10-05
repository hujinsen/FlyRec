"""
测试录音提示窗口功能
"""

import tkinter as tk
import time

def create_recording_indicator():
    """创建录音提示窗口"""
    # 创建主窗口（隐藏）
    root = tk.Tk()
    root.withdraw()
    
    # 创建录音提示窗口
    indicator = tk.Toplevel()
    indicator.title("")
    indicator.geometry("200x80")
    
    # 设置窗口属性
    indicator.overrideredirect(True)  # 无边框
    indicator.attributes('-topmost', True)  # 置顶
    indicator.attributes('-alpha', 0.9)  # 半透明
    indicator.configure(bg='#FF4444')  # 红色背景
    
    # 右侧贴边显示
    screen_width = indicator.winfo_screenwidth()
    screen_height = indicator.winfo_screenheight()
    x = screen_width - 200  # 贴到右边缘
    y = (screen_height - 80) // 2  # 垂直居中
    indicator.geometry(f"200x80+{x}+{y}")
    
    # 添加内容
    frame = tk.Frame(indicator, bg='#FF4444')
    frame.pack(fill=tk.BOTH, expand=True)
    
    # 录音图标和文字
    icon_label = tk.Label(frame, text="🎤", font=('Arial', 24), 
                         bg='#FF4444', fg='white')
    icon_label.pack(pady=5)
    
    text_label = tk.Label(frame, text="录音中...", font=('Arial', 12, 'bold'), 
                         bg='#FF4444', fg='white')
    text_label.pack()
    
    # 显示3秒后自动关闭
    def close_after_delay():
        root.after(3000, root.quit)
    
    close_after_delay()
    root.mainloop()

if __name__ == "__main__":
    print("显示录音提示窗口3秒...")
    create_recording_indicator()
    print("测试完成")