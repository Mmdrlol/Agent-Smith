import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import multiprocessing
from .sandbox import create_sandbox
from .sandbox_config import SandboxConfig
from .manual import generate_manual
from llm.__main__ import agent_llm, send_llm
from mcp_tools_swebench import clean_run_test_output
from pathlib import Path
from mcp.client.streamable_http import streamable_http_client
from queue import Empty
import fire
import subprocess
import shlex
from llm.agent_output import StepMetrics
import sys
import re


async def handle_tool_call(session, mcp_connection, message):
    try:
        result = await session.call_tool(
                message["name"],
                arguments=message["arguments"])

        texts = [item.text
                 for item in result.content
                 if hasattr(item, "text")]

        text = "\n".join(texts)

        mcp_connection.send({
            "is_error": result.is_error,
            "text": text})
    except Exception as e:
        mcp_connection.send({
            "is_error": True,
            "text": f"{type(e).__name__}: {e}"
            })


def add_print_to_tools(code, tools):
    tool_pattern = "|".join(tool.name for tool in tools.tools)

    pattern = re.compile(
        rf"^(\s*)({tool_pattern})\((.*)\)\s*$"
    )

    new_lines = []

    for line in code.splitlines():
        match = pattern.match(line)

        if match:
            indent, tool_name, arguments = match.groups()
            line = f"{indent}print({tool_name}({arguments}))"

        new_lines.append(line)

    return "\n".join(new_lines)


async def run_session(sandbox_config, session, connection,
                      model_name=None, provider_url=None,
                      additional_system_prompt="",
                      user_message=None, workspace=None,
                      solution_output=None,
                      llm=False, mbpp=False, swe=False,
                      container_id=None):
    parent_connection, child_connection = connection
    await session.initialize()
    tools = await session.list_tools()

    tool_infos = []
    for tool in tools.tools:
        tool_infos.append({
            "name": tool.name,
            "parameters": list(
                tool.input_schema.get("properties", {}).keys())})

    if llm:
        manual = generate_manual(tools)
        llm_client, llm_messages = await agent_llm(
                manual, provider_url, model_name, solution_output,
                additional_system_prompt)

    process, result_queue, sandbox_connection = create_sandbox(
            sandbox_config, child_connection, tool_infos)

    if llm:
        llm_messages.append({"role": "user",
                             "content": user_message})

    old_eval_output_len = None
    while True:
        if swe and old_eval_output_len:
            old_id = [i for i, message in enumerate(llm_messages)
                      if message["role"] == "user" and
                      "Eval script Output:" in message["content"]][-1]
            old_user_content = llm_messages[old_id]["content"]
            llm_messages[old_id]["content"] = \
                old_user_content[:-old_eval_output_len
                                 - len("\n\nEval script Output:\n")]
            old_eval_output_len = None

        if llm:
            code, llm_messages, response = await send_llm(
                    llm_client, llm_messages, solution_output)
            code = add_print_to_tools(code, tools)
        else:
            code = test_cli()

        sandbox_connection.send({"type": "execute",
                                 "code": code})

        loop = asyncio.get_running_loop()
        start_time = loop.time()
        mcp_time = 0

        while True:
            elapsed_time = loop.time() - start_time - mcp_time
            if elapsed_time > sandbox_config.max_execution_time_seconds:
                process.terminate()
                process.join()
                result = {"status": "error",
                          "output": "SandboxError: the program timed out."}
                break

            if parent_connection.poll():
                message = parent_connection.recv()
                mcp_start = loop.time()
                await handle_tool_call(session, parent_connection, message)
                mcp_time += loop.time() - mcp_start

            try:
                result = result_queue.get_nowait()
            except Empty:
                result = None

            if result is not None:
                if result["status"] == "finished":
                    print()
                    print(f"\033[36m{result["final_answer"]}\033[m")
                    sandbox_connection.send({"type": "shutdown"})

                    if llm:
                        solution_output.steps.append(
                                StepMetrics(
                                    step=solution_output.iterations,
                                    input_tokens=response.input_tokens,
                                    output_tokens=response.output_tokens,
                                    request_time_ms=response.request_time,
                                    api_url=response.api_url,
                                    model_name=response.model_name,
                                    llm_output=response.content,
                                    sandbox_input=code,
                                    sandbox_output=result["output"],
                                    retries=response.retries))
                    process.join()
                    return
                break

            await asyncio.sleep(0.01)

        if len(result["output"]) > 10000:
            result["output"] = (result["output"][:10000] +
                                "\n[The output has been truncated]\n")
        if llm:
            if mbpp:
                test_result = subprocess.run(
                        [sys.executable, "-m", "pytest", "-q",
                         "--tb=short", "--disable-warnings", "--no-header"],
                        cwd=workspace,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True)
                if test_result.returncode == 0:
                    solution_output.steps.append(
                            StepMetrics(
                                step=solution_output.iterations,
                                input_tokens=response.input_tokens,
                                output_tokens=response.output_tokens,
                                request_time_ms=response.request_time,
                                api_url=response.api_url,
                                model_name=response.model_name,
                                llm_output=response.content,
                                sandbox_input=code,
                                sandbox_output=result["output"],
                                retries=response.retries))
                    solution_output.success = True
                    solution_output.solution = (
                            workspace / "solution.py").read_text()
                    sandbox_connection.send({"type": "shutdown"})
                    process.join()
                    return
                if len(result["output"]) != 0:
                    result["output"] += "\n\n"
                result["output"] += "Current /testbed/solution.py:\n"
                result["output"] += "```python\n"
                result["output"] += (
                        workspace / "solution.py").read_text() + "\n"
                result["output"] += "```\n\n"
                result["output"] += "Pytest Output:\n"
                result["output"] += (test_result.stdout
                                     + test_result.stderr + "\n")

            if swe:
                if "edit_file" in code:
                    test_result = subprocess.run(
                            ["docker", "exec", "-w", "/testbed",
                             container_id, "bash", "-e",
                             "/agent_smith/eval_script.sh"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            timeout=60)
                    test_result_cleaned, test_result_passed = \
                        clean_run_test_output(test_result)
                    if test_result_passed:
                        diff_result = subprocess.run(
                                ["docker", "exec", "-w", "/testbed",
                                 container_id, "git", "-c",
                                 "core.fileMode=false", "diff"],
                                capture_output=True,
                                text=True,
                                check=True)
                        solution_output.steps.append(
                                StepMetrics(
                                    step=solution_output.iterations,
                                    input_tokens=response.input_tokens,
                                    output_tokens=response.output_tokens,
                                    request_time_ms=response.request_time,
                                    api_url=response.api_url,
                                    model_name=response.model_name,
                                    llm_output=response.content,
                                    sandbox_input=code,
                                    sandbox_output=result["output"],
                                    retries=response.retries))
                        solution_output.success = True
                        solution_output.solution = diff_result.stdout
                        sandbox_connection.send({"type": "shutdown"})
                        process.join()
                        return

                    result["output"] += "\n\nEval script Output:\n"
                    result["output"] += test_result_cleaned
                    old_eval_output_len = len(test_result_cleaned)

            for line in result["output"].split("\n"):
                print(f"\033[36m>>\033[m {line}")

            llm_messages.append({
                "role": "user",
                "content": "Observation:\n" +
                (result["output"] or "No output from the sandbox.")})

            solution_output.steps.append(
                    StepMetrics(
                        step=solution_output.iterations,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        request_time_ms=response.request_time,
                        api_url=response.api_url,
                        model_name=response.model_name,
                        llm_output=response.content,
                        sandbox_input=code,
                        sandbox_output=result["output"],
                        retries=response.retries))
        else:
            print(f"\033[36m{result["output"]}\033[m")

    process.join()


def test_cli():
    print("\033[m", end="")
    lines = []
    while True:
        try:
            line = input("\033[35m>>>\033[m ")
        except EOFError:
            print()
            raise SystemExit

        if len(lines) == 0 and line.strip() == "exit":
            raise SystemExit

        if line.strip() == "":
            if lines:
                break
            continue
        lines.append(line)

    print("\033[36m", end="")
    return "\n".join(lines) + "\n"


def build_docker(mcp_stdio, workspace=None):
    subprocess.run(["docker",
                    "build",
                    "-f",
                    "docker/Dockerfile",
                    "-t",
                    "mcp-server",
                    "."],
                   check=True)
    if not workspace:
        workspace = Path("testbed").resolve()
    mcp_command = shlex.split(mcp_stdio)
    project_root = Path(".").resolve()
    server_params = StdioServerParameters(
            command="docker",
            args=["run", "--rm", "-i",
                  "-v", f"{project_root}:/agent_smith:ro,Z",
                  "-v", f"{workspace}:/testbed:Z",
                  "-w", "/agent_smith",
                  "mcp-server",
                  *mcp_command])
    return server_params


async def stdio_server(sandbox_config, mcp_stdio,
                       model_name=None, provider_url=None,
                       additional_system_prompt=None,
                       user_message=None, workspace=None,
                       solution_output=None,
                       llm=False, mbpp=False, swe=False,
                       container_id=None):
    if not swe:
        server_params = build_docker(mcp_stdio, workspace=workspace)
    else:
        parts = shlex.split(mcp_stdio)
        server_params = StdioServerParameters(
                command=parts[0],
                args=parts[1:])

    connection = multiprocessing.Pipe()
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await run_session(
                    sandbox_config, session, connection,
                    model_name=model_name, provider_url=provider_url,
                    additional_system_prompt=additional_system_prompt,
                    user_message=user_message, workspace=workspace,
                    solution_output=solution_output,
                    llm=llm, mbpp=mbpp, swe=swe,
                    container_id=container_id)


async def http_server(sandbox_config, mcp_url):
    connection = multiprocessing.Pipe()
    async with streamable_http_client(mcp_url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await run_session(sandbox_config, session, connection)


def run(config=None, mcp_stdio=None, mcp_server=None):
    if config:
        sandbox_config = SandboxConfig.model_validate_json(
                Path(config).read_text())
    else:
        sandbox_config = SandboxConfig()

    if mcp_stdio and mcp_server:
        raise ValueError("Only one server should be specified.")
    if mcp_stdio:
        asyncio.run(stdio_server(sandbox_config, mcp_stdio))
    elif mcp_server:
        asyncio.run(http_server(sandbox_config, mcp_server))
    else:
        raise ValueError("You must specify a MCP server with either "
                         "--mcp_stdio or --mcp_server")


if __name__ == "__main__":
    fire.Fire(run)
