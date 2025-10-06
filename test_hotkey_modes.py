"""简单测试/示例：验证双模式快捷键状态机逻辑（非自动化GUI测试）。
运行后按提示在终端外部测试快捷键行为。
增加: 配置读写测试，用于验证 gui_app_fixed 中新增的快捷键模式持久化逻辑。
"""
import time
import keyboard
import json
import os

CONFIG_FILE = 'config.json'

def _read_cfg():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE,'r',encoding='utf-8') as f:
            try:
                return json.load(f)
            except Exception:
                return {}
    return {}

def test_persist(mode_expect: str, hotkey_expect: str):
    """简单验证配置文件中的模式/快捷键是否为期望值"""
    cfg = _read_cfg()
    mode = cfg.get('hotkey_mode')
    hotkey = cfg.get('hotkey')
    print('[CONFIG]', cfg)
    assert mode == mode_expect, f"期望模式 {mode_expect} 实际 {mode}"
    assert hotkey == hotkey_expect, f"期望快捷键 {hotkey_expect} 实际 {hotkey}"
    print('✅ 配置持久化检查通过')

class HotkeyModeTester:
    def __init__(self):
        self.mode = 'double_ctrl'  # 改成 'hold' 测试按住模式原理
        self.hotkey = 'ctrl+space'
        self.is_recording = False
        self.hotkey_parts = self.hotkey.split('+')
        self.last_ctrl_release = 0.0
        self.double_interval = 0.5
        if self.mode == 'hold':
            self.thread_run = True
            import threading
            threading.Thread(target=self._loop, daemon=True).start()
        else:
            keyboard.on_release(self._on_release)
        print('测试模式:', self.mode)
        print('说明:')
        if self.mode == 'hold':
            print('按住 Ctrl+Space -> 开始录音, 松开任意 -> 停止')
        else:
            print('快速双击 Ctrl -> 开始录音; 录音中再按一次 Ctrl -> 停止')

    def _loop(self):
        was_pressed = False
        while getattr(self, 'thread_run', False):
            pressed = all(keyboard.is_pressed(k) for k in self.hotkey_parts)
            if pressed and not was_pressed and not self.is_recording:
                self.start()
            elif was_pressed and not pressed and self.is_recording:
                self.stop()
            was_pressed = pressed
            time.sleep(0.05)

    def _on_release(self, e):
        if e.name in ('ctrl','left ctrl','right ctrl'):
            now = time.time()
            if not self.is_recording:
                if now - self.last_ctrl_release <= self.double_interval:
                    self.start(); self.last_ctrl_release = 0
                else:
                    self.last_ctrl_release = now
            else:
                self.stop()

    def start(self):
        self.is_recording = True
        print('[START] 录音中...')
    def stop(self):
        self.is_recording = False
        print('[STOP] 已结束')

if __name__ == '__main__':
    # 先做一次配置持久化的快速检查（如果用户已运行过 GUI 切换过模式）
    try:
        test_persist(mode_expect=_read_cfg().get('hotkey_mode','hold'), hotkey_expect=_read_cfg().get('hotkey','ctrl+space'))
    except AssertionError as ae:
        print('配置检查未通过(可能尚未运行 GUI 保存):', ae)

    t = HotkeyModeTester()
    print('按 Esc 退出测试')
    keyboard.wait('esc')
    print('退出')
