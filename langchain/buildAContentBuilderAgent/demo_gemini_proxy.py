"""
Gemini 生图 — 直连 vs PackyAPI 中转站 双模式 Demo

用法（在项目根目录 .env 中配置）:

  直连 Google（默认）:
      GOOGLE_API_KEY=AIzaSy...           # Google AI Studio 官方 key
      # 不设置 GEMINI_BASE_URL 或不填，即走直连

  中转站模式:
      GOOGLE_API_KEY=sk-你的PackyAPI令牌  # PackyAPI 控制台生成的 key
      GEMINI_BASE_URL=https://www.packyapi.com   # PackyAPI 中转站地址

说明:
  - google.genai SDK 会在 base_url 后自动追加 /v1beta
  - PackyAPI 最终请求路径为: https://www.packyapi.com/v1beta/models/...
"""

import os
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import types

# 加载项目根目录 .env
load_dotenv(Path(__file__).resolve().parents[2] / ".env")


def create_gemini_client() -> genai.Client:
    """根据环境变量创建 Gemini 客户端，自动区分直连 / 中转站模式"""

    api_key = os.getenv("GOOGLE_API_KEY")
    proxy_base_url = os.getenv("GEMINI_BASE_URL", "").strip()

    if proxy_base_url:
        # ==================== 中转站模式 ====================
        print(f"[中转站模式] base_url = {proxy_base_url}")
        http_opts = types.HttpOptions(base_url=proxy_base_url)
        return genai.Client(api_key=api_key, http_options=http_opts)
    else:
        # ==================== 直连模式 ====================
        print("[直连模式] 使用 Google AI Studio 官方端点")
        return genai.Client(api_key=api_key)


def generate_image(prompt: str, output_path: str) -> str:
    """生成图片并保存到本地"""
    client = create_gemini_client()

    response = client.models.generate_content(
        model="gemini-2.5-flash-image",
        contents=[prompt],
    )

    for part in response.parts:
        if part.inline_data is not None:
            image = part.as_image()
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            image.save(output_path)
            return f"图片已保存至: {output_path}"

    # 如果模型返回的是文本而非图片
    if response.text:
        return f"模型返回文本（非图片）: {response.text[:200]}..."

    return "未生成图片"


if __name__ == "__main__":
    result = generate_image(
        prompt="A cute cat sitting on a cloud in anime style",
        output_path="./demo_output.png",
    )
    print(result)
