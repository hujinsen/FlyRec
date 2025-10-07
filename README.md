# 语音识别助手 GUI

一个基于阿里云 DashScope API 的智能语音识别工具，提供实时语音转文字和智能文本处理功能。

## 功能特性

### 🎤 语音识别
- 新增：双模式快捷键
	- 按住模式：按住 Ctrl+Space（或自定义组合）开始，松开结束
	- 双击Ctrl模式：快速双击 Ctrl 开始录音，录音中再按一次 Ctrl 结束
	- 在 设置 -> 快捷键模式 中切换
	- 双击判定默认最大间隔 0.5s
- 新增：录音开始/结束音效（`assets/start_rec.mp3`, `assets/end_rec.mp3`），可直接替换文件自定义提示音

### 📊 统计分析
- **使用统计**：总词数、节省时间、平均WPM
- **历史记录**：保存所有识别记录
- **搜索功能**：可按内容搜索历史记录
- **数据导出**：支持导出统计数据和历史记录

### ⚙️ 设置选项
- **自定义快捷键**：默认 `Ctrl+Space`，可自定义
- **文本处理模板**：选择不同的文本处理方式
- **自动粘贴开关**：可选择是否自动粘贴结果
- **系统托盘**：支持最小化到系统托盘

## 安装依赖

```bash
pip install dashscope pyaudio pynput pyperclip pyautogui pystray pillow keyboard playsound
```

若使用 `uv` 或 `pip` 根据 `pyproject.toml` 安装：
```bash
pip install .
```

## 使用方法

### 1. 启动应用
```bash
python gui_app.py
```

### 2. 设置 API Key
在 `text_format.py` 中设置你的阿里云 DashScope API Key：
```python
dashscope.api_key = 'your-api-key-here'
```

### 3. 使用语音识别
1. 按住 `Ctrl+Space`（或自定义快捷键）开始录音（或双击Ctrl）
2. 播放开始提示音后说话
3. 松开快捷键或再次按Ctrl停止录音，播放结束提示音
4. 处理后的文本会自动粘贴到当前光标位置（若开启）

### 4. 文本处理模板

#### 默认模板
- 去除语气词
- 修正可能的错误文字
- 返回最接近说话人意思的文本

#### 邮件模板
- 润色为正式邮件格式
- 简洁、礼貌、专业、有条理
- 自动添加发件人信息

#### 代码模板
- 根据描述生成代码
- 代码简洁、规范、有注释
- 适合编程需求

#### 聊天模板
- 生成有趣的聊天回复
- 使用 emoji 表情
- 回答简洁有趣

## 界面说明

### 仪表板
- **统计卡片**：显示使用统计信息
- **快捷操作**：录音测试、清空统计、导出数据
- **最近转录**：显示最近的识别结果

### 识别记录
- **历史列表**：所有识别记录的表格视图
- **搜索功能**：按内容搜索历史记录
- **详细信息**：时间、原文、处理后文本、词数

### 设置页面
- **快捷键设置**：自定义全局快捷键
- **模板选择**：选择文本处理模板
- **行为设置**：自动粘贴、系统托盘等选项

## 快捷键格式

支持以下快捷键格式：
- `ctrl+space`（默认）
- `alt+v`
- `ctrl+alt+r`
- `f1`、`f2` 等功能键

## 音效自定义
- 替换 `assets/start_rec.mp3` 为自定义开始音效
- 替换 `assets/end_rec.mp3` 为自定义结束音效
- 保持文件名不变即可，无需修改代码

## 注意事项

1. **麦克风权限**：确保应用有麦克风访问权限
2. **网络连接**：需要网络连接进行语音识别
3. **API 配额**：注意阿里云 API 的使用配额
4. **系统兼容性**：支持 Windows、Mac、Linux
5. **提示音不播放**：检查是否安装 `playsound`，或 MP3 是否能被系统解码（尝试重新转换为 128kbps MP3）

## 故障排除

### 快捷键不工作
- 检查是否有其他应用占用了相同快捷键
- 尝试使用不同的快捷键组合
- 确保应用有足够的系统权限

### 语音识别失败
- 检查网络连接
- 验证 API Key 是否正确
- 确保麦克风正常工作

### 自动粘贴不工作
- 检查目标应用是否支持 Ctrl+V 粘贴
- 确保目标应用有焦点
- 在设置中检查自动粘贴是否开启

## 技术架构

- **GUI框架**：tkinter.ttk
- **语音识别**：阿里云 DashScope API
- **音频处理**：pyaudio
- **快捷键监听**：keyboard
- **系统集成**：pystray（系统托盘）
- **自动输入**：pyautogui
- **提示音播放**：playsound（独立线程，不阻塞界面）

## 开发说明

### 文件结构
- `gui_app.py`：主GUI应用
- `gui_app_fixed.py`：修复版 GUI（新增提示音逻辑）
- `demo4.py`：语音识别核心逻辑
- `text_format.py`：文本生成API封装
- `voice_stats.json`：统计数据存储
- `transcripts.json`：识别记录存储
- `assets/`：提示音资源

### 扩展功能
可以通过修改以下部分来扩展功能：
- 添加新的文本处理模板
- 自定义统计分析
- 集成其他语音识别API
- 添加更多输出格式
- 使用其他播放库（如 pygame / pydub+simpleaudio）实现淡入淡出或并行多音效

## 许可证

本项目仅供学习和个人使用。使用阿里云 DashScope API 需要遵守相应的服务条款。

## 打包部署（PyInstaller 目录模式）

已提供 `FlyRecApp.spec`，可生成 `dist/FlyRecApp/` 目录用于分发。

### 1. 安装依赖
```powershell
pip install -r requirements.txt   # 若你有生成；或
pip install pyinstaller            # 已在 pyproject 中可直接安装
```

### 2. 生成 / 更新 spec 文件（可跳过）
第一次也可以用命令让 PyInstaller 自动生成，再手动优化：
```powershell
pyinstaller -D -n FlyRecApp gui_app_fixed.py
```
随后使用仓库中的 `FlyRecApp.spec` 覆盖或编辑。

### 3. 正式打包
```powershell
pyinstaller .\FlyRecApp.spec
```
完成后目录结构：
```
dist/
	FlyRecApp/
		FlyRecApp.exe
		assets/ (内含 wav)
		config.json (模板，可编辑)
		其余依赖 DLL / *.pyz
```

### 4. 运行与测试
```powershell
cd dist/FlyRecApp
./FlyRecApp.exe
```

### 5. 常见问题
| 现象 | 说明 / 解决 |
|------|-------------|
| 首次启动慢 | 正常，初始化库加载与 DLL 校验。 |
| 声音不播放 | 检查 `soundfile` 对应的 `libsndfile` DLL 是否被打包；更新声卡驱动。 |
| 粘贴失败 | 有安全软件拦截 `pyautogui` / 剪贴板访问。 |
| 杀毒误报 | 关闭 UPX（在 spec 中 `upx=False`）或使用目录模式（已是目录模式）| 

### 6. 升级发布建议
1. 增量更新：只替换新的 `FlyRecApp` 目录。
2. 若想保留用户统计数据，可提示用户先备份 `voice_stats.json` 与 `transcripts.json`（当前放在运行目录）。
3. 后续可将运行期数据迁移至 `%APPDATA%/FlyRec` 以便放入受保护目录。

### 7. 可选：单文件模式（调试用）
```powershell
pyinstaller --onefile --add-data "assets;assets" --add-data "config.json;." gui_app_fixed.py
```
（单文件首次启动需解压，目录模式已足够）

### 8. 资源路径提示
若后续需要更稳定的资源定位，可在代码里封装：
```python
def resource_path(*parts):
		import sys, os
		base = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(__file__)
		return os.path.join(base, *parts)
```
然后替换 `os.path.join(base_dir, 'assets', fname)`。
