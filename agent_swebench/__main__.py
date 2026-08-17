from sandbox.__main__ import stdio_server
from sandbox.sandbox_config import SandboxConfig
import fire
import asyncio
from pathlib import Path
from pydantic import BaseModel
from llm.agent_output import SolutionOutput
import time
import subprocess


class SWEBenchTaskInput(BaseModel):
    """Input for a SWE-bench task, provided by the moulinette.
    Your agent receives this and must produce a git patch that fixes the
    issue.
    """
    instance_id: str
    problem_statement: str
    docker_image: str
    eval_script: str
    hints_text: str
    repo: str


def start_swe_container(image):
    result = subprocess.run(
            ["docker", "image", "inspect", image],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL)
    if result.returncode != 0:
        subprocess.run(
                ["docker", "pull", image],
                check=True)

    result = subprocess.run(
            ["docker", "run", "-d", "--rm", image,
             "tail", "-f", "/dev/null"],
            capture_output=True,
            text=True,
            check=True)

    return result.stdout.strip()


def install_mcp_server(container_id):
    subprocess.run(["docker", "exec", container_id, "python",
                    "-m", "pip", "install", "mcp"],
                   check=True)

    subprocess.run(
            ["docker", "exec", container_id,
             "mkdir", "-p", "/agent_smith"],
            check=True)

    subprocess.run(
            ["docker", "cp", "mcp_tools_swebench.py",
             f"{container_id}:/agent_smith/mcp_tools_swebench.py"],
            check=True)

    subprocess.run(
            ["docker", "cp", "mcp_server",
             f"{container_id}:/agent_smith/mcp_server"],
            check=True)


def copy_eval_script(container_id, eval_script):
    subprocess.run(
            ["docker", "exec", "-i", container_id,
             "bash", "-c",
             "cat > /agent_smith/eval_script.sh && chmod +x "
             "/agent_smith/eval_script.sh"],
            input=eval_script,
            text=True,
            check=True)


def get_repo_file_list(container_id):
    result = subprocess.run(
            ["docker", "exec", "-w", "/testbed",
             container_id, "find", ".", "-type", "f"],
            capture_output=True,
            text=True,
            check=True)
    return result.stdout


def agent_swe(task_file, output, model_name, provider_url):
    sandbox_config = SandboxConfig()
    swe_task = SWEBenchTaskInput.model_validate_json(
            Path(task_file).read_text())
    solution_output = SolutionOutput(
            task_id=swe_task.instance_id,
            benchmark="swebench",
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

    user_message = (
            "Solve the follwing SWE-bench task.\n\n"
            "Instance:\n"
            f"{swe_task.instance_id}\n\n"
            "Repository:\n"
            f"{swe_task.repo}\n\n"
            "Problem statement:\n"
            f"{swe_task.problem_statement}\n")

    if swe_task.hints_text:
        user_message += ("\nHints:\n"
                         f"{swe_task.hints_text}\n")

    swe_system_prompt = (
            "This is a SWE-bench repository debugging task.\n"
            "The repository is already available at /testbed.\n\n"
            "Investigate the repository before making changes.\n"
            "user the available file and code-search tools to "
            "locate the revelant implementations, definitions, "
            "references, and tests.\n"
            "Do not assume which file contains the bug from the "
            "problem statement alone.\n\n"
            "When modifying the repository:\n"
            "- make the smallest appropriate fix,\n"
            "- avoid unreated refactors,\n"
            "- preserve existing behavior outside of the reported issue,\n"
            "- do not modify tests just to make them pass,\n"
            "- use edit-file for targeted edits when practical.\n\n"
            "Testing strategy:\n"
            "- prefer focused tests or commands while investigating,\n"
            "- use run_command when a specific test or diagnostic "
            "command is sufficient,\n"
            "- use run_tests to execute the providede SWE-bench evaluation "
            "script when the solution is reasonably complete,\n"
            "- treat test failures and command output as evidence and "
            "iterate from them.\n\n"
            "Before finishing:\n"
            "- verify the relevant behavior,\n"
            "Import file-editing rule:\n"
            "- read_file() returns line-numbered text for inspection only."
            "- Do not pass the output of read_file directly as old_str to "
            "edit_file().\n"
            "- edit_file() requires old_str to be small exact raw substring "
            "that exists in the file, wiuthout line-number prefixes.\n"
            "- Always prefer the smallest exact replacement possible.\n\n"
            "Protocal role:\n"
            "- Each response must contian exactly one Thought section and "
            "exactly one Python code block.\n"
            "- Stop immediately after the closing ``` of that code block."
            "- Never output an Observation, stdout, stderr, file content or "
            "test results.\n"
            "- Never simulate or predict tool results.\n"
            "- Wait for the environment to return the real Observation "
            "before taking another action.\n\n"
            "Your very first action should be to call list_files() but make "
            "sure to add the exact right directory or pattern you need for "
            "the problem and don't"
            "make the search too general.\n"
            "For example, do not execute list_files(\"/testbed/\", \"*\").\n"
            "Finally, as always, do NOT output Observations. Wait for the "
            "envirement to give it back.\n")

    start_time = time.perf_counter()
    container_id = None
    try:
        container_id = start_swe_container(swe_task.docker_image)
        install_mcp_server(container_id)
        copy_eval_script(container_id, swe_task.eval_script)

        asyncio.run(
                stdio_server(
                    sandbox_config,
                    f"docker exec -i {container_id} "
                    f"python /agent_smith/mcp_tools_swebench.py",
                    model_name=model_name, provider_url=provider_url,
                    additional_system_prompt=swe_system_prompt,
                    user_message=user_message,
                    solution_output=solution_output,
                    llm=True, swe=True, container_id=container_id))

        diff_result = subprocess.run(
                ["docker", "exec", "-w", "/testbed",
                 container_id, "git", "-c", "core.fileMode=false",
                 "diff"],
                capture_output=True,
                text=True,
                check=True)
        solution_output.success = True
        solution_output.solution = diff_result.stdout
    except Exception as e:
        solution_output.success = False
        solution_output.error = f"{type(e).__name__}: {e}"

    solution_output.total_time_seconds = time.perf_counter() - start_time

    if container_id:
        subprocess.run(
                ["docker", "rm", "-f", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL)

    Path(output).write_text(
            solution_output.model_dump_json(indent=2))


if __name__ == "__main__":
    fire.Fire(agent_swe)
