# 贡献指南（Contributing）

感谢你愿意改进 FlyRec。

## 运行与调试

- Windows 10/11 + Python >= 3.10
- 推荐使用 `.env` 提供 `DASHSCOPE_API_KEY`（不要提交 `.env`）
- 本地配置/数据文件（已在 `.gitignore` 中忽略）：`config.json`、`transcripts.json`、`voice_stats.json`、`user_dictionary.json`、`voice_data_export_*.json`

快速启动：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install .
Copy-Item config.example.json config.json
python flyrec_gui.py
```

## 代码风格

本项目使用 `pyproject.toml` 中的 `black/ruff` 配置作为约定。

- 格式化：`python -m black .`
- 静态检查：`python -m ruff check .`

## 模块划分

- [flyrec_gui.py](flyrec_gui.py) 作为主 GUI 入口（逐步瘦身）
- [services.py](services.py) 为 ASR/LLM 统一服务层
- [flyrec/](flyrec/) 为可复用的核心模块（环境加载、智能场景、词典替换、识别器对接等）

## 提交前检查

- `python -m py_compile flyrec_gui.py services.py flyrec/*.py`
- 不要提交任何密钥、转录、统计、导出数据
