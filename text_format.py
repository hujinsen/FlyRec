"""Dashscope Generation API 的文本生成封装。

提供一个基于类的简单接口，其他模块可以调用
TextGenerator.generate(messages, api_key=...) 来获取结构化响应，
或在失败时收到带有详细信息的异常。

契约：
- 输入：messages（包含 'role' 和 'content' 的字典列表），可选 api_key
- 输出：当 status_code == 200 时返回包含响应数据的字典
- 错误：对于非 200 的响应会抛出带细节的 RuntimeError

考虑的边缘情况：
- 缺少 api_key（会从环境变量 DASHSCOPE_API_KEY 读取）
- messages 无效或为空
- HTTP 返回码不是 200

使用示例（参见 __main__）：
    generator = TextGenerator()
    out = generator.generate([{"role":"user","content":"你好"}])

"""

from typing import List, Dict, Optional, Any
import json
import os
from dashscope import Generation
import dashscope

# 如果使用新加坡(region)的模型，请取消下面注释以切换API地址
# dashscope.base_http_api_url = "https://dashscope-intl.aliyuncs.com/api/v1"


class TextGenerator:
    """dashscope.Generation.call 的封装类。

    方法
    -----
    generate(messages, api_key=None, model='qwen-plus', result_format='message')
        调用 API 并在成功时返回解析后的类似 JSON 的字典。
    """

    def __init__(self, api_key: Optional[str] = None, model: str = "qwen-plus"):
        self.api_key = api_key or os.getenv("DASHSCOPE_API_KEY")
        self.model = model

    def generate(
        self,
        messages: List[Dict[str, str]],
        api_key: Optional[str] = None,
        result_format: str = "message",
        **call_kwargs: Any,
    ) -> Dict[str, Any]:
        """从模型生成响应。

        参数：
        - messages: 列表，每项为 {'role':..., 'content':...}
        - api_key: 可选，临时覆盖实例的 API Key
        - result_format: 传递给 Generation.call 的 result_format 参数
        - call_kwargs: 其他转发给 Generation.call 的关键字参数

        返回：当 status_code == 200 时返回解析后的响应字典。
        错误时：对于非 200 的响应抛出 RuntimeError，包含详细信息。
        """

        key = api_key or self.api_key
        if not key:
            raise ValueError(
                "需要 API Key。请设置环境变量 DASHSCOPE_API_KEY 或通过 api_key 参数传入。"
            )

        if not isinstance(messages, list) or len(messages) == 0:
            raise ValueError("messages 必须是非空的 role/content 字典列表")

        response = Generation.call(
            api_key=key,
            model=self.model,
            # messages 是简单字典的列表；dashscope 的类型存根期望一个 Message 类型，
            # 在这里不可用 —— 为静态类型检查添加忽略注释。
            messages=messages,  # type: ignore[arg-type]
            result_format=result_format,
            **call_kwargs,
        )

        # 保持原有行为：状态码为 200 时返回解析对象，否则抛出异常
        if getattr(response, "status_code", None) == 200:
            # 返回对象可能无法直接被 JSON 序列化；优先通过 json 转换
            try:
                return json.loads(json.dumps(response, default=lambda o: o.__dict__, ensure_ascii=False))
            except Exception:
                # 回退：如果有 __dict__ 则返回它
                return getattr(response, "__dict__", {"raw": response})
        else:
            code = getattr(response, "code", None)
            message = getattr(response, "message", None)
            raise RuntimeError(
                f"生成失败：status_code={getattr(response, 'status_code', None)}, code={code}, message={message}"
            )


if __name__ == "__main__":
    # 简单的命令行使用示例
    default_messages = [
        {"role": "system", "content": "你是专业的邮件助手，帮我把下面的内容润色成正式的邮件。要求简洁、礼貌、专业、有条理。我叫胡进森，邮箱是：<hujsen@163.com>,电话是：13290818863，个人网站是：https://hujinsen.github.io/。"},
        {"role": "user", "content": "写封邮件给张三，要他明天做好语音识别功能开发，回复我邮件。"},
    ]
    CODE_MESSAGE = [
    {"role": "system", "content": "你是专业的代码助手，帮我把下面内容写成代码，要求代码简洁、规范、有注释。"},
    {"role": "user", "content": "帮我实现一个简单的文本比较功能，输入两个文本，输出两个文本的相似度，相似度大于0.5时输出相似，否则输出不相似。"},
]

    gen = TextGenerator(api_key="sk-2d627fbbc4fa491db207c632a77f2852")
    try:
        out = gen.generate(CODE_MESSAGE)
        print("调用成功，响应内容：")
        if out:
            print(out.get("output").get("choices")[0].get("message").get("content"))
        else:
            print("响应为空")
        # print(json.dumps(out, indent=4, ensure_ascii=False))
    except Exception as e:
        print(f"调用失败：{e}")