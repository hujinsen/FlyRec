"""
测试快捷键按住/释放逻辑
"""

import keyboard
import time

class HotkeyTester:
    def __init__(self):
        self.current_hotkey = "ctrl+space"
        self.is_recording = False
        self.hotkey_parts = []
        self.pressed_keys = set()
        self.setup_hotkey()
    
    def setup_hotkey(self):
        """设置全局快捷键"""
        try:
            # 移除旧的快捷键监听器
            keyboard.unhook_all()
            
            # 解析快捷键组合
            self.hotkey_parts = self.current_hotkey.lower().replace(' ', '').split('+')
            self.pressed_keys = set()
            
            # 设置按键监听器
            keyboard.on_press(self.on_key_press)
            keyboard.on_release(self.on_key_release)
            
            print(f"已设置快捷键: {self.current_hotkey}")
            print(f"快捷键组合: {self.hotkey_parts}")
        except Exception as e:
            print(f"设置快捷键失败: {e}")
    
    def on_key_press(self, key):
        """按键按下事件"""
        try:
            key_name = self.get_key_name(key)
            self.pressed_keys.add(key_name)
            print(f"按下: {key_name}, 当前按键: {self.pressed_keys}")
            
            # 检查是否匹配快捷键组合
            if self.is_hotkey_pressed():
                if not self.is_recording:
                    self.start_recording()
        except Exception as e:
            print(f"按键处理错误: {e}")
    
    def on_key_release(self, key):
        """按键释放事件"""
        try:
            key_name = self.get_key_name(key)
            print(f"🔓 释放: {key_name}")
            
            if key_name in self.pressed_keys:
                self.pressed_keys.remove(key_name)
                print(f"   从按键集合中移除: {key_name}")
            
            # 检查释放的按键是否是快捷键组合的一部分
            normalized_key = key_name
            if key_name in ['ctrl_l', 'ctrl_r']:
                normalized_key = 'ctrl'
            elif key_name in ['alt_l', 'alt_r']:
                normalized_key = 'alt'
            elif key_name in ['shift_l', 'shift_r']:
                normalized_key = 'shift'
            
            print(f"   标准化按键: {normalized_key}, 快捷键组合: {self.hotkey_parts}")
            print(f"   当前按键集合: {self.pressed_keys}")
            
            # 如果释放的是快捷键组合中的任意一个键，就停止录音
            if normalized_key in self.hotkey_parts and self.is_recording:
                print(f"   ✅ 释放了快捷键组合中的按键: {normalized_key}")
                self.stop_recording()
            else:
                print(f"   ❌ 不是快捷键或未在录音: normalized_key={normalized_key}, in_hotkey={normalized_key in self.hotkey_parts}, recording={self.is_recording}")
        except Exception as e:
            print(f"按键释放处理错误: {e}")
    
    def get_key_name(self, key):
        """获取按键名称"""
        if hasattr(key, 'name'):
            return key.name.lower()
        elif hasattr(key, 'char') and key.char:
            return key.char.lower()
        else:
            return str(key).lower()
    
    def is_hotkey_pressed(self):
        """检查快捷键组合是否被按下"""
        # 将ctrl映射到ctrl_l或ctrl_r
        normalized_pressed = set()
        for key in self.pressed_keys:
            if key in ['ctrl_l', 'ctrl_r']:
                normalized_pressed.add('ctrl')
            elif key in ['alt_l', 'alt_r']:
                normalized_pressed.add('alt')
            elif key in ['shift_l', 'shift_r']:
                normalized_pressed.add('shift')
            else:
                normalized_pressed.add(key)
        
        print(f"标准化按键集合: {normalized_pressed}, 需要: {set(self.hotkey_parts)}")
        
        # 检查是否包含所有必要的按键
        required_keys = set(self.hotkey_parts)
        return required_keys.issubset(normalized_pressed)
    
    def start_recording(self):
        """开始录音"""
        if self.is_recording:
            return
        
        self.is_recording = True
        print("🎤 开始录音...")
    
    def stop_recording(self):
        """停止录音"""
        if not self.is_recording:
            return
        
        self.is_recording = False
        print("⏹️ 停止录音")

if __name__ == "__main__":
    tester = HotkeyTester()
    print("按住 Ctrl+Space 开始录音，释放停止录音")
    print("按 Esc 退出")
    
    try:
        keyboard.wait('esc')
    except KeyboardInterrupt:
        pass
    
    print("测试结束")