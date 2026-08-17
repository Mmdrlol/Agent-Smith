import time
from openai import AsyncOpenAI
from pydantic import BaseModel


class LLMResponse(BaseModel):
    content: str
    input_tokens: int
    output_tokens: int
    request_time: float
    api_url: str
    model_name: str
    retries: int


class LLMClient:
    def __init__(self, provider_url, model_name, api_keys):
        self.provider_url = provider_url
        self.model_name = model_name
        self.api_keys = api_keys
        self.key_index = 0

    async def generate(self, message, stop=None):
        retries = 0

        while True:
            api_key = self.api_keys[self.key_index]

            client = AsyncOpenAI(
                    api_key=api_key,
                    base_url=self.provider_url,
                    max_retries=0)

            start_time = time.perf_counter()

            try:
                response = await client.chat.completions.create(
                        model=self.model_name,
                        messages=message,
                        stop=stop,
                        tool_choice="none",
                        max_completion_tokens=500)

                elapsed_time = (time.perf_counter() - start_time) * 1000

                return LLMResponse(
                    content=response.choices[0].message.content or "",
                    input_tokens=response.usage.prompt_tokens,
                    output_tokens=response.usage.completion_tokens,
                    request_time=elapsed_time,
                    api_url=self.provider_url,
                    model_name=self.model_name,
                    retries=retries
                    )
            except Exception as e:
                print(f"{type(e).__name__}: {e}")
                retries += 1
                self.key_index = (self.key_index + 1) % len(self.api_keys)

        raise RuntimeError("All API keys failed.")
