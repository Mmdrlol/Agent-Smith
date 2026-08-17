from mcp_server.main import mcp, catch_error
import subprocess
from pathlib import Path


mcp.remove_tool("run_tests")


@mcp.tool()
@catch_error
def run_tests() -> str:
    try:
        result = subprocess.run(
                ["bash", "-e", "/agent_smith/eval_script.sh"],
                cwd=Path("/testbed"),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                timeout=60)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Tests timed out after 60 seconds.")
    return clean_run_test_output(result)[0]


def clean_run_test_output(result) -> tuple[str, bool]:
    """Execute the evaluation script."""
    cleaned = []

    for line in result.stdout.splitlines():
        stripped = line.lstrip()

        if stripped.startswith("+"):
            continue

        if ("CONDA_" in line or
                "export PATH=" in line or
                "PS1=" in line):
            continue

        if stripped.startswith((
                "export ",
                "DEPRECATION: ")):
            continue

        if ("/conda/activate.d/" in stripped or
                "/conda/deactivate.d/" in stripped):
            continue

        cleaned.append(line)

    if result.returncode == 0:
        useful = "\n".join(cleaned[-50:])

        return ("status: PASS\n\n"
                f"{useful}", True)

    useful = "\n".join(cleaned[-50:])

    return ("status: FAIL\n\n"
            f"{useful}", False)


if __name__ == "__main__":
    mcp.run()
