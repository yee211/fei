"""模型调用封装：任何 OpenAI 兼容端点都能用。"""
from openai import OpenAI

from fei import config


def make_client() -> OpenAI:
    if not config.API_KEY:
        raise SystemExit("缺少 API key：复制 .env.example 为 .env，填入 FEI_API_KEY")
    return OpenAI(api_key=config.API_KEY, base_url=config.BASE_URL,
                  timeout=config.REQUEST_TIMEOUT, max_retries=config.REQUEST_RETRIES)
