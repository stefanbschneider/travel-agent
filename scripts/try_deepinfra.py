import os

from openai import OpenAI
from chinatravel.agent.phase2.llm_client import load_local_env


load_local_env()

api_key = os.getenv("INFRADEEP_API_KEY")
if not api_key:
    raise RuntimeError(
        "INFRADEEP_API_KEY is not set. Put it in .env or export it in your shell before running."
    )

openai = OpenAI(
    api_key=api_key,
    base_url="https://api.deepinfra.com/v1/openai",
)

chat_completion = openai.chat.completions.create(
    model="Qwen/Qwen3.6-27B",
    messages=[{"role": "user", "content": "Hello"}],
)

print(chat_completion.choices[0].message.content)
print(chat_completion.usage.prompt_tokens, chat_completion.usage.completion_tokens)