"""
Модуль 0: Первый вызов LLM — сравнение GigaChat и OpenRouter
"""

import os
import time

from pathlib import Path
from dotenv import load_dotenv
from gigachat import GigaChat
from openai import OpenAI


def setup_env():
    load_dotenv(Path(__file__).parent.parent / ".env")


def call_gigachat(question: str) -> dict:
    credentials = os.getenv("GIGACHAT_CREDENTIALS")
    if not credentials:
        raise ValueError("GIGACHAT_CREDENTIALS не найден в .env")

    start = time.time()

    with GigaChat(credentials=credentials, verify_ssl_certs=False, scope="GIGACHAT_API_PERS") as client:
        response = client.chat(
            {
                "messages": [{"role": "user", "content": question}],
                "model": "GigaChat",
            }
        )

    latency = time.time() - start

    return {
        "answer": response.choices[0].message.content,
        "tokens": response.usage.total_tokens,
        "latency": latency,
    }


def call_openrouter(question: str) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY не найден в .env")

    model = os.getenv("OPENROUTER_DEFAULT_MODEL", "openrouter/auto")

    client = OpenAI(api_key=api_key, base_url="https://openrouter.ai/api/v1")

    start = time.time()

    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": question}],
    )

    latency = time.time() - start

    return {
        "answer": response.choices[0].message.content,
        "tokens": response.usage.total_tokens if response.usage else 0,
        "latency": latency,
    }


def print_result(provider_name: str, result: dict):
    print(f"=== {provider_name} ===")
    print(f"Ответ: {result['answer']}")
    print(f"Токены: {result['tokens']}")
    print(f"Latency: {result['latency']:.2f} сек.")
    print()


def main():
    setup_env()

    question = "Что такое RAG в контексте языковых моделей? Ответь в 2-3 предложениях."

    print("=" * 60)
    print("СРАВНЕНИЕ ПРОВАЙДЕРОВ LLM")
    print("=" * 60)
    print()

    gigachat_result = None
    openrouter_result = None

    try:
        gigachat_result = call_gigachat(question)
        print_result("GigaChat", gigachat_result)
    except Exception as e:
        print(f"GigaChat ошибка: {e}\n")

    try:
        openrouter_result = call_openrouter(question)
        model_name = os.getenv("OPENROUTER_DEFAULT_MODEL", "openrouter/auto")
        print_result(f"OpenRouter: {model_name}", openrouter_result)
    except Exception as e:
        print(f"OpenRouter ошибка: {e}\n")

    if gigachat_result and openrouter_result:
        print("=" * 60)
        print(
            f"Итог: GigaChat ответил за {gigachat_result['latency']:.2f} сек., "
            f"OpenRouter за {openrouter_result['latency']:.2f} сек."
        )
        print("=" * 60)


if __name__ == "__main__":
    main()
