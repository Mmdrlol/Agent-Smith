from sandbox.__main__ import stdio_server
from sandbox.sandbox_config import SandboxConfig
import fire
import asyncio
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List
from llm.agent_output import SolutionOutput
import time
import subprocess
import sys


class MBPPTaskInput(BaseModel):
    """Input for MBPP task evaluation."""
    task_id: int
    task_definition: str
    function_definition: str
    test_imports: List[str] = Field(default_factory=list)
    test_list: List[str] = Field(default_factory=list)


def read_file(filepath: str) -> str:
    with open(filepath, "r", encoding="utf-8") as file:
        lines = file.readlines()

    result = ""
    for i in range(len(lines)):
        result += f"{i + 1}: {lines[i]}"

    if not result.endswith("\n"):
        result += "\n"
    return result


def create_mbpp_workspace(mbpp_task):
    root = Path(".").resolve()

    n = 1
    while (root / f"mbpp{n}").exists():
        n += 1

    workspace = root / f"mbpp{n}"
    workspace.mkdir()

    solution_content = (
            f"{mbpp_task.function_definition}\n"
            "    pass")

    test_content = ""

    if mbpp_task.test_imports:
        test_content += "\n".join(mbpp_task.test_imports) + "\n"

    test_content += (
            "from solution import *\n\n"
            "def test_mbpp():\n"
            f"    {"\n    ".join(mbpp_task.test_list)}\n")

    (workspace / "solution.py").write_text(solution_content)
    (workspace / "test_solution.py").write_text(test_content)

    return workspace


def agent_mbpp(task_file, output, model_name, provider_url):
    sandbox_config = SandboxConfig()
    mbpp_task = MBPPTaskInput.model_validate_json(Path(task_file).read_text())
    workspace = create_mbpp_workspace(mbpp_task)
    user_message = (
            "Solve the following MBPP task.\n\n"
            "Task:\n"
            f"{mbpp_task.task_definition}\n\n"
            "Required function:\n"
            f"{mbpp_task.function_definition}\n\n"
            "Initial workspace contents of /testbed/solution.py:\n"
            f"{read_file(workspace / "solution.py")}\n\n")

    mbpp_system_prompt = (
            "The task workspace is already prepared in /testbed.\n"
            "Implement the solution by modifying /testbed/solution.py "
            "using the available file tools.\n"
            "Do not define the solution only inside the sandbox code block, "
            "because that does not modify the files.\n"
            "Instead, replace the \"    pass\" placeholder with the correct "
            "solution.\n"
            "To edit a file, directly use this format:\n"
            "```python\n"
            "edit_file(\"/testbed/solution.py\", \"    pass\", ...)\n"
            "```\n"
            "Do not modify /testbed/test_solution.py.\n"
            "Use the test command to verify the implementation.\n"
            "Make sure that the function manages all edge cases and is "
            "generalized outside of the few tests available.\n"
            "The provided tests are only public examples. "
            "Do not overfit to the visible tests.\n"
            "infer the most general intended behavior from:\n"
            "1. the natural-language task description,\n"
            "2. the required function signature,\n"
            "3. all visible input/output examples.\n\n"
            "If the description and examples seem ambiguous or inconsistent, "
            "prefer the simplest rile that explains all visible examples "
            "while behaving sensibly on unseen inputs.\n\n"
            "Before finishing:\n"
            "- consider boundary cases,\n"
            "- consider inputs just outside the visible examples,\n"
            "- check both sides of coditions demonstrated by the examples,\n"
            "- avoid special-casing specific test values,\n"
            "- avoid unnecessary assumptions not supported by the task.\n\n"
            "Passing the public tests is necessary but not sufficient "
            "evidence that the solution is correct.\n")

    solution_output = SolutionOutput(
            task_id=str(mbpp_task.task_id),
            benchmark="mbpp",
            success=False,
            solution="",
            iterations=0,
            total_requests=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_time_seconds=0.0,
            steps=[],
            system_prompt="",
            error=None)

    start_time = time.perf_counter()
    asyncio.run(stdio_server(sandbox_config, "python mcp_tools_mbpp.py",
                             model_name=model_name, provider_url=provider_url,
                             additional_system_prompt=mbpp_system_prompt,
                             user_message=user_message, workspace=workspace,
                             solution_output=solution_output,
                             llm=True, mbpp=True))

    result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q"],
            cwd=workspace,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True)

    if result.returncode == 0:
        solution_output.success = True
        solution_output.solution = (workspace / "solution.py").read_text()
    else:
        solution_output.success = False
        solution_output.error = "Function verification failed."

    solution_output.total_time_seconds = time.perf_counter() - start_time
    Path(output).write_text(solution_output.model_dump_json(indent=2))


if __name__ == "__main__":
    fire.Fire(agent_mbpp)
