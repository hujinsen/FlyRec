#!/usr/bin/env python3
"""
测试智能模板切换功能
"""

import sys
from flyrec import smart_template as st

if __name__ == "__main__":
    print("智能模板切换功能测试")
    print("=" * 50)
    
    if not st.SMART_TEMPLATE_AVAILABLE:
        print("❌ 智能模板切换功能不可用")
        sys.exit(1)
    
    print("✅ 智能模板切换功能可用")
    
    # 获取当前活动窗口信息
    process_name, window_title = st.get_active_window_process()
    
    print(f"当前活动窗口:")
    print(f"  进程名: {process_name}")
    print(f"  窗口标题: {window_title}")
    
    # 获取推荐模板
    scene = st.suggest_scene(process_name, window_title, fallback="文本")
    print(f"  推荐场景: {scene}")
    
    print("\n测试完成！")