from mcp.server.fastmcp import FastMCP
from functools import wraps
from pathlib import Path
import re
import ast
import subprocess

mcp = FastMCP("mcp-server")


def catch_error(func):
    @wraps(func)
    def wrap(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            raise RuntimeError(
                    f"{type(e).__name__}: {e}"
                    ) from e
    return wrap


def resolve_path(path):
    original_path = Path(path)
    allowed_path = Path("/testbed").resolve()
    if not original_path.is_absolute():
        original_path = allowed_path / original_path

    resolved_path = original_path.resolve(strict=False)

    if not resolved_path.is_relative_to(allowed_path):
        raise PermissionError(f"path '{path}' is not available.")

    return resolved_path


@mcp.tool()
@catch_error
def read_file(filepath: str, start_line: int, end_line: int) -> str:
    """Read the content of a file with line numbers."""
    if start_line < 1 or end_line < 1:
        raise ValueError("line numbers must be greater than 0.")
    if start_line > end_line:
        start_line, end_line = end_line, start_line

    resolved_path = resolve_path(filepath)

    if not resolved_path.exists():
        raise FileNotFoundError(2, "No such file or directory", filepath)
    with open(resolved_path, "r", encoding="utf-8") as file:
        lines = file.readlines()

    result = ""
    for i in range(start_line-1, end_line):
        if i >= len(lines):
            break
        result += f"{i + 1}: {lines[i]}"

    if not result.endswith("\n"):
        result += "\n"
    return result


@mcp.tool()
@catch_error
def edit_file(filepath: str, old_str: str, new_str: str) -> str:
    """Replace an exact string in a file with a new string."""
    if old_str == "":
        raise ValueError("old_str cannot be empty.")

    resolved_path = resolve_path(filepath)
    with open(resolved_path, "r", encoding="utf-8") as file:
        text = file.read()

    count = text.count(old_str)

    if count == 0:
        raise ValueError("old_str was not found.")
    elif count > 1:
        raise ValueError(f"old_str appears {count} times inside the file. "
                         "The file was not edited. Try to be more specific.")

    new_text = text.replace(old_str, new_str, 1)

    with open(resolved_path, "w", encoding="utf-8") as file:
        file.write(new_text)
    return "Edit done."


@mcp.tool()
@catch_error
def list_files(directory: str, pattern: str) -> str:
    """List files in a directory matching a given pattern."""
    directory_path = Path(directory)
    if directory_path.is_absolute():
        if not str(directory_path).startswith("/testbed"):
            directory_path = Path("/testbed") / str(directory_path).lstrip("/")
    else:
        directory_path = Path("/testbed") / directory_path

    if pattern == "":
        pattern = "*"
    resolved_path = resolve_path(directory_path)

    if not resolved_path.is_dir():
        raise ValueError(f"{directory} is not a directory.")

    matches = sorted(path for path in resolved_path.rglob(pattern)
                     if path.is_file())

    if not matches:
        return "No matching files found."

    if len(matches) > 50:
        directories = sorted({str(path.parent) for path in matches})

        return (f"Too many matching files ({len(matches)}). "
                f"Showing directories containing those matches only:\n"
                + "\n".join(directories)
                + "\n\nNarrow your search by selecting a specific directory "
                "or file pattern.\n")

    return "\n".join(str(path) for path in matches)


@mcp.tool()
@catch_error
def search_code(pattern: str, file_pattern: str) -> str:
    """Perform a grep-like search in the codebase."""
    if file_pattern in ["", "*"]:
        file_pattern = "*.py"
    matches = []

    if len(pattern) == 0:
        raise ValueError("pattern cannot be empty.")
    for path in Path("/testbed").resolve().rglob(file_pattern):
        if not path.is_file():
            continue

        try:
            with open(path, "r", encoding="utf-8") as file:
                for lineno, line in enumerate(file, start=1):
                    if pattern in line:
                        matches.append(f"{path}:{lineno} {line.rstrip()}")
        except UnicodeDecodeError:
            continue

    if not matches:
        return "No matches found."
    return "\n".join(matches)


@mcp.tool()
@catch_error
def search_function_or_class_definition_in_code(name: str) -> str:
    """Find the definition of a function or a class."""
    if len(name) == 0:
        raise ValueError("name cannot be empty.")

    matches = []

    for path in Path("/testbed").rglob("*.py"):
        if not path.is_file():
            continue

        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (UnicodeDecodeError, SyntaxError):
            continue

        lines = text.splitlines()

        for node in ast.walk(tree):
            if (isinstance(
                    node,
                    (ast.FunctionDef,
                     ast.AsyncFunctionDef,
                     ast.ClassDef)) and
                    node.name == name):
                line = lines[node.lineno - 1]

                matches.append(f"{path}:{node.lineno} {line.strip()}")

    if not matches:
        return "No definitions found."
    return "\n".join(matches)


@mcp.tool()
@catch_error
def find_references(name: str, filepath: str, line: int) -> str:
    """Find all usages of a symbol (function or class)."""
    if len(name) == 0:
        raise ValueError("name cannot be empty.")
    if line < 1:
        raise ValueError("line must be greater than 0.")
    resolved_path = resolve_path(filepath)
    pattern = re.compile(rf"\b{re.escape(name)}\b")

    matches = []

    for path in Path("/testbed").rglob("*.py"):
        if not path.is_file():
            continue

        try:
            with open(path, "r", encoding="utf-8") as file:
                for lineno, file_line in enumerate(file, start=1):
                    if path.resolve() == resolved_path and lineno == line:
                        continue

                    if pattern.search(file_line):
                        matches.append(f"{path}:{lineno} "
                                       f"{file_line.strip()}")
        except UnicodeDecodeError:
            continue
    if not matches:
        return "No references found."
    return "\n".join(matches)


@mcp.tool()
@catch_error
def run_tests() -> str:
    """Execute the evaluation script."""
    try:
        result = subprocess.run(
                ["pytest", "-q"],
                cwd=Path("/testbed"),
                capture_output=True,
                text=True,
                timeout=30)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Tests timed out after 30 seconds.")

    return ("stdout:\n"
            f"{result.stdout}\n"
            "stderr:\n"
            f"{result.stderr}\n"
            f"exit_code: {result.returncode}")


@mcp.tool()
@catch_error
def get_patch() -> str:
    """Retrieve the unified git diff of all changes made to the repository,
    depending on the implementation."""
    try:
        result = subprocess.run(
                ["git", "-c", "core.fileMode=false", "diff"],
                cwd=Path("/testbed"),
                capture_output=True,
                text=True,
                timeout=30)
    except subprocess.TimeoutExpired:
        raise RuntimeError("git diff timed out after 30 seconds.")

    if result.returncode != 0:
        raise RuntimeError(f"git diff failed: {result.stderr.strip()}")

    return result.stdout


@mcp.tool()
@catch_error
def run_command(command: str, workdir: str) -> str:
    """Execute a shell command in the specified working directory."""
    resolved_path = resolve_path(workdir)

    if not resolved_path.is_dir():
        raise ValueError(f"'{workdir}' is not a directory")

    try:
        result = subprocess.run(
                command,
                cwd=resolved_path,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30)
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"command '{command}' timed out after 30 seconds.")

    return ("stdout:\n"
            f"{result.stdout}\n"
            "stderr:\n"
            f"{result.stderr}\n"
            f"exit_code: {result.returncode}")


if __name__ == "__main__":
    mcp.run()
