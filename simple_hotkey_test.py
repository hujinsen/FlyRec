"""
简化版快捷键测试 - 使用单个按键
"""

import keyboard
import time

class SimpleHotkeyTester:
    def __init__(self):
        self.hotkey = "f1"  # 使用 F1 作为测试按键
        self.is_recording = False
        self.setup_hotkey()
    
    def setup_hotkey(self):
        """设置全局快捷键"""
        try:
            keyboard.unhook_all()
            
            # 使用直接的按键监听
            keyboard.on_press_key(self.hotkey, self.on_key_press)
            keyboard.on_release_key(self.hotkey, self.on_key_release)
            
            print(f"已设置快捷键: {self.hotkey}")
        except Exception as e:
            print(f"设置快捷键失败: {e}")
    
    def on_key_press(self, event):
        """按键按下事件"""
        print(f"🔽 按下: {self.hotkey}")
        if not self.is_recording:
            self.start_recording()
    
    def on_key_release(self, event):
        """按键释放事件"""
        print(f"🔼 释放: {self.hotkey}")
        if self.is_recording:
            self.stop_recording()
    
    def start_recording(self):
        """开始录音"""
        self.is_recording = True
        print("🎤 开始录音...")
    
    def stop_recording(self):
        """停止录音"""
        self.is_recording = False
        print("⏹️ 停止录音")

if __name__ == "__main__":
    tester = SimpleHotkeyTester()
    print("按住 F1 开始录音，释放停止录音")
    print("按 Esc 退出")
    
    try:
        keyboard.wait('esc')
    except KeyboardInterrupt:
        pass
    
    print("测试结束")