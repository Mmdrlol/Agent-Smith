.PHONY: install mbpp swebench sandbox clean

install:
	uv sync

mbpp:
	uv run python -m agent_mbpp --task-file="cache/mbpp_task.json" --output="cache/mbpp_solution.json" --model-name="openai/gpt-oss-120b" --provider-url="https://api.groq.com/openai/v1"

swebench:
	uv run python -m agent_swebench --task-file "cache/swebench_task.json" --output "cache/swebench_solution.json" --model-name "qwen/qwen3.6-27b" --provider-url "https://api.groq.com/openai/v1"

sandbox:
	uv run sandbox --mcp-stdio "python mcp_server/main.py"

clean:
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
