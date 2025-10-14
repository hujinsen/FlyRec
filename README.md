## FlyRec - 语音→可用文本效率工具

按下快捷键，说完就得到已润色/场景化的文本，并自动粘贴到你正在输入的窗口。

### 核心价值
| 诉求 | 传统方式 | FlyRec | 收益 |
|------|----------|--------|------|
| 快速输入 | 手打慢 | 语音即文本 | 节省时间 |
| 可直接使用 | 回听+整理 | 自动润色/风格化 | 减少后处理 |
| 多场景切换 | 手动调风格 | 智能识别窗口 | 降低心智负担 |
| 专有名词 | 易错/口误 | 用户词典替换 | 输出更稳定 |

---
### 功能概览（基于当前代码实现，未夸大）
1. 双模式快捷键：
   - 按住模式：按住 `Ctrl+Space`（可自定义）录音，松开结束。
   - 双击 Ctrl：双击开始，再按一次结束（默认间隔 ≤0.5s）。
2. 实时语音识别：调用 DashScope `fun-asr-realtime`，结束后拼接句段。
3. 场景/风格：文本 / 聊天 / 邮件 / 代码，可手动或智能自动（依据活动进程名/窗口标题）。
4. 输出语言：中文或英语；英语模式附加强制英文规则并检测重试。
5. 文本润色生成：使用 `qwen-plus` 模型，根据 system + user messages 输出。
6. 用户词典：发送到模型前按“原词→替换”为顺序匹配（长词优先），打印替换明细。
7. 自动粘贴：生成后复制剪贴板并模拟 `Ctrl+V`。
8. 历史记录：本地保存（原文/处理后/时间/字数），支持搜索、详情查看、复制。
9. 统计：总字数、录音累计时长、平均 CPM（字符/分钟），最近 30 天聚合（内部维护）。
10. 录音指示：浮层提示 + 开始/结束音效（使用 wav + 预加载缓存）。
11. 系统托盘：关闭窗口默认隐藏到托盘，可右键显示/退出。
12. 数据持久化：JSON 文件（`config.json`, `transcripts.json`, `voice_stats.json`, `user_dictionary.json`）。

---
### 安装依赖
推荐使用 `pyproject.toml`：
```powershell
pip install .
```
或手动：
```powershell
pip install dashscope pyaudio pyautogui pyperclip keyboard pystray pillow sounddevice soundfile psutil
```
（说明：当前版本实际使用 `sounddevice+soundfile` 播放 wav；旧文档中的 playsound/mp3 已移除。）

### 启动
```powershell
python gui_app_fixed.py
```
首次运行会在同目录生成配置与数据文件。

### 设置 API Key
在环境变量或代码中设置：
```powershell
$Env:DASHSCOPE_API_KEY="你的Key"
```
或编辑 `demo4.py`/`text_format.py` 传入（不推荐硬编码）。

---
### 快速上手（用户视角）
1. 打开程序 → 进入“设置”选择：语言 / 场景 / 是否启用智能场景 / 自动粘贴。
2. 选“按住模式”或“双击 Ctrl”模式。
3. 聚焦到任何输入框（聊天/邮件/IDE）。
4. 触发快捷键，说话，松开或再按结束。
5. 几秒后润色文本自动粘贴。
6. 在“转录记录”查看详情或复制。
7. 在“词典”添加专有词规范。

---
### 英语模式特殊逻辑
1. system prompt 附加英文输出强制规则。
2. 若检测到模型输出仍含中文字符，触发一次英文回退消息重试。
3. 第二次仍失败则保留原内容（避免陷入循环）。

### 智能场景切换（示例映射）
| 进程/标题包含 | 场景 | 说明 |
|---------------|------|------|
| wechat / qq / 钉钉 | 聊天 | 聊天语气优化 |
| outlook / mail / foxmail | 邮件 | 正式、礼貌、结构化 |
| code / pycharm / idea | 代码 | 保留技术语义、口语→清晰描述 |
| 其它 | 文本 | 普通精炼描述 |

### 用户词典机制
| 阶段 | 作用 |
|------|------|
| 识别结束后 | 将识别结果按从长到短顺序做纯字符串替换 |
| 发送前 | 替换后的文本进入模型 prompt |
| 保存记录 | 原文与润色后分别存储（原文不篡改） |

---
### 数据文件说明
| 文件 | 内容 |
|------|------|
| config.json | 快捷键、模式、输出语言、提示词结构 |
| transcripts.json | 转录历史（数组） |
| voice_stats.json | 累计统计与最近30天聚合 |
| user_dictionary.json | 词典映射 |

---
### FAQ
Q: 一定要联网吗？  
A: 是，需要在线语音识别和文本生成。  
Q: 原始音频会保存本地吗？  
A: 不会，只实时采集并发送，结束即释放。  
Q: 英语模式为什么偶尔仍有中文？  
A: 已做一次检测+回退重试，属于模型输出特例。  
Q: 智能场景没反应？  
A: 需 Windows 且安装 `pywin32`；不支持的进程名称会回退到手动场景。  
Q: 统计字数为何与“词”不同？  
A: 当前实现按字母/数字字符计数（中文视作字数近似），并用此估 CPM。  
Q: 想自定义提示词？  
A: 当前 UI 按钮为预留，可直接修改 `config.json -> prompts` 后重启。  
Q: 声音没播放？  
A: 安装 `soundfile`，并确保 `assets/start_rec.wav` / `end_rec.wav` 存在。  

---
### 与旧文档差异修正
| 旧描述 | 当前真实情况 |
|--------|--------------|
| playsound 播放 mp3 | 现用 sounddevice + soundfile 播放 wav 并预加载缓存 |
| 代码模板直接生成代码 | 代码场景侧重“表达清晰化”，不自动写代码 |
| 多模板完全可自定义 | 自定义编辑入口尚未实现，使用内置 + config.json |
| 全平台托盘统一可用 | 代码中使用 pywin32 获取活动窗口（主要验证于 Windows） |

---
### 开发/结构速览
| 文件 | 作用 |
|------|------|
| gui_app_fixed.py | 主 GUI 应用（快捷键/场景/统计/托盘/音效） |
| demo4.py | 基础识别封装（DashScope ASR 会话） |
| text_format.py | 大模型生成封装（Qwen 文本生成） |
| services.py | 新增统一 Service 层：ASR/LLM 抽象与工厂，支持 DashScope / Dummy 后端 |
| FlyRecApp.spec | PyInstaller 打包配置 |
| assets/ | 音效资源（wav） |

---
### 打包（PyInstaller 目录模式）
```powershell
pyinstaller .\FlyRecApp.spec
```
输出位于 `dist/FlyRecApp/`，包含 exe、依赖与资源。

常见问题：
| 现象 | 说明 |
|------|------|
| 首次启动慢 | 动态库加载正常现象 |
| 粘贴失败 | 目标应用拦截模拟输入或失焦，确保前台窗口 | 
| 无托盘/智能场景 | 缺少 pywin32，安装后重启 |

---
### 将来可迭代方向（建议）
1. 自定义提示词 UI & 导入导出。
2. 本地/离线识别（Whisper 等）备选。
3. 历史记录标签/收藏/多维筛选。
4. Markdown / 批量导出 / 一键复制格式化摘要。
5. 统计图表（活跃度、场景分布）。
6. 连续长时录音自动分段 + 实时流式显示。
7. 更智能的语言自动检测与中英文混排优化。

---
### Service 层说明（新增）
`services.py` 引入统一抽象：
 - ASRService: start/stop/is_running/on_partial
 - LLMService: generate/simple_refine
 - FlyRecRuntime: 从配置构造组合 (runtime.asr / runtime.llm)

配置示例（`config.json` 可新增 `runtime` 字段）：
```jsonc
{
   "runtime": {
      "asr": { "backend": "dashscope", "model": "fun-asr-realtime" },
      "llm": { "backend": "dashscope", "model": "qwen-plus" }
   }
}
```
离线/占位（开发/无网）可设置：
```jsonc
{
   "runtime": {
      "asr": { "backend": "dummy" },
      "llm": { "backend": "dummy" }
   }
}
```
Dummy 后端仅返回模拟文本，用于界面联调，不调用真实 API。

---
### 许可证
本项目用于学习与个人效率提升。使用 DashScope 服务需遵守其服务条款。

---
### 快速摘要（可复制到介绍页）
FlyRec：按下快捷键开始说话，结束即得润色后的文本（支持聊天/邮件/代码场景与智能切换），自动粘贴到当前光标位置；内置用户词典、历史记录与统计，全程本地保存结果数据。

---
（文档已根据 2025-10 当前仓库代码同步校准。）
