from dotenv import load_dotenv
import os
from .agent import LLMClient
from .system_prompt import get_system_prompt
import re


def test_cli():
    code = ""
    while not code.endswith("\n\n"):
        code += input("\033[36m>>\033[m ") + "\n"
    print("\033[m", end="")
    return code


async def agent_llm(sandbox_manual, provider_url, model_name, solution_output,
                    additional_system_prompt):
    load_dotenv()
    keys = [value
            for name, value in sorted(os.environ.items())
            if name.startswith("GROQ_API_KEY") and value]

    client = LLMClient(
            provider_url=provider_url,
            model_name=model_name,
            api_keys=keys)

    system_prompt = get_system_prompt(sandbox_manual)
    system_prompt += additional_system_prompt

    solution_output.system_prompt = system_prompt

    messages = [{
        "role": "system",
        "content": system_prompt
        }]

    return client, messages


async def send_llm(client, messages, solution_output):
    response = await client.generate(messages)
    messages.append({
        "role": "assistant",
        "content": response.content
        })

    print("\033[m")
    print(response.content)
    matches = re.findall(r"```python\s(.*?)```", response.content, re.DOTALL)
    if len(matches) != 0:
        code = "\n".join(match.strip() for match in matches)
    else:
        code = ""

    solution_output.iterations += 1
    solution_output.total_requests += 1 + response.retries
    solution_output.total_input_tokens += response.input_tokens
    solution_output.total_output_tokens += response.output_tokens

    return code, messages, response
