import builtins
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import traceback
import linecache
from pathlib import Path
import multiprocessing
import resource
import socket


def resolve_sandbox_path(file_path, workspace):
    path = Path(file_path)

    if path.is_absolute():
        if path == Path("/testbed"):
            relative = Path(".")
        elif path.is_relative_to("/testbed"):
            relative = path.relative_to("/testbed")
        else:
            raise SandboxError(f"path '{file_path}' is not available.")
    else:
        relative = path

    real_path = (Path(workspace).resolve() / relative).resolve(strict=False)
    workspace_path = Path(workspace).resolve()

    if not real_path.is_relative_to(workspace_path):
        raise SandboxError(f"path '{file_path}' is not available.")

    return real_path


def get_restricted_open(sandbox_config, workspace):
    def restricted_open(file_path, *args, **kwargs):
        real_path = resolve_sandbox_path(file_path, workspace)
        return open(real_path, *args, **kwargs)
    return restricted_open


def get_builtins(sandbox_config, workspace):
    return {
            "print": print,
            "len": len,
            "range": range,
            "open": get_restricted_open(sandbox_config, workspace),
            "bytearray": bytearray,
            "enumerate": enumerate,
            "min": min,
            "max": max,
            "sum": sum,
            "all": all,
            "any": any,
            "abs": abs,
            "round": round,
            "sorted": sorted,
            "reversed": reversed,
            "map": map,
            "filter": filter,
            "zip": zip,
            "list": list,
            "dict": dict,
            "set": set,
            "tuple": tuple,
            "str": str,
            "int": int,
            "float": float,
            "bool": bool,
            "type": type,
            "isinstance": isinstance,
            "iter": iter,
            "repr": repr,
            "chr": chr,
            "ord": ord,
            "bin": bin,
            "hex": hex,
            "Exception": Exception,
            "ValueError": ValueError,
            "IndexError": IndexError,
            "TypeError": TypeError,
            "NameError": NameError,
            "KeyError": KeyError,
            "FileNotFoundError": FileNotFoundError,
            "PermissionError": PermissionError
            }


def desable_networking():
    def blocked(*args, **kwargs):
        raise SandboxError("networking is not available.")

    socket.socket = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    socket.gethostbyname = blocked
    socket.gethostbyname_ex = blocked
    socket.gethostbyaddr = blocked


def is_module_allowed(name, sandbox_config):
    for module in sandbox_config.authorized_imports:
        if module.endswith(".*"):
            if name.startswith(module[:-1]):
                return True
        elif name == module:
            return True
    return False


class SandboxError(Exception):
    pass


def get_restricted_imports(sandbox_config):
    def restricted_imports(name, *args, **kwargs):
        if not is_module_allowed(name, sandbox_config):
            raise SandboxError(f"module \'{name}\' is not available.")
        return builtins.__import__(name, *args, **kwargs)
    return restricted_imports


class FinalAnswer(Exception):
    def __init__(self, value):
        self.value = value


def final_answer(solution):
    raise FinalAnswer(solution)


class MCPToolError(Exception):
    pass


def call_mcp_tool(connection, func_name, arguments):
    connection.send({
        "name": func_name,
        "arguments": arguments
        })

    response = connection.recv()

    if response["is_error"]:
        message = response["text"]
        prefix = f"Error executing tool {func_name}: "
        if message.startswith(prefix):
            message = message[len(prefix):]
        raise MCPToolError(message)
    return response["text"]


def make_mcp_wrapper(connection, func_name, parameters):
    def mcp_wrapper(*args, **kwargs):
        arguments = {}

        if len(args) > len(parameters):
            raise TypeError(
                    f"{func_name}() takes {len(parameters)} positional "
                    f"arguments but {len(args)} were given")

        for param_name, param_value in zip(parameters, args):
            arguments[param_name] = param_value

        for param_name, param_value in kwargs.items():
            if param_name in arguments:
                raise TypeError(
                        f"{func_name}() got multiple values for argument "
                        f"'{param_name}'")

            if param_name not in parameters:
                raise TypeError(f"{func_name}() got an unexpected keyword "
                                f"argument '{param_name}'")

            arguments[param_name] = param_value

        return call_mcp_tool(connection, func_name, arguments)
    return mcp_wrapper


def create_namespace(sandbox_config, mcp_functions, workspace):
    namespace = {
            "__builtins__": {}
            }
    namespace["__builtins__"].update(get_builtins(sandbox_config, workspace))
    namespace["__builtins__"]["__import__"] = \
        get_restricted_imports(sandbox_config)
    namespace["final_answer"] = final_answer
    namespace.update(mcp_functions)
    return namespace


def sandbox(code, namespace):
    output_buffer = StringIO()
    with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
        try:
            filename = "<sandbox>"
            linecache.cache[filename] = (
                    len(code),
                    None,
                    code.splitlines(keepends=True),
                    filename
                    )
            compiled = compile(code, filename, "exec")
            exec(compiled, namespace)
        except FinalAnswer as e:
            return {"status": "finished",
                    "output": output_buffer.getvalue(),
                    "final_answer": e.value}
        except SyntaxError as e:
            error = f'File "{e.filename}", line {e.lineno}\n'
            if e.text:
                error += f"    {e.text}"
            error += f"\n{type(e).__name__}: {e.msg}"
            return {"status": "error",
                    "output": error}
        except Exception as e:
            tb = traceback.TracebackException.from_exception(e)
            sandbox_frames = [frame for frame in tb.stack
                              if frame.filename == "<sandbox>"]
            error = ""
            if len(sandbox_frames):
                for frame in sandbox_frames:
                    error += (f'File "{frame.filename}", '
                              f'line {frame.lineno}, in {frame.name}\n')
                    if frame.line:
                        error += f"    {frame.line}\n"

                    if isinstance(e, NameError) and e.name in vars(builtins):
                        error += (f"\nSandboxError: builtin '{e.name}' "
                                  "is not available.")
                    elif isinstance(e, MemoryError):
                        error += "\nMemoryError: memory limit exceeded."
                    elif isinstance(e, MCPToolError):
                        error += f"\n{e}"
                    else:
                        error += f"\n{type(e).__name__}: {e}"
            return {"status": "error",
                    "output": error}

    return {"status": "ok",
            "output": output_buffer.getvalue()}


def sandbox_worker(sandbox_config, result_connection, mcp_connection,
                   sandbox_connection, tool_infos, workspace):
    max_memory = sandbox_config.max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS,
                       (max_memory, max_memory))
    desable_networking()

    mcp_functions = {}
    for tool in tool_infos:
        mcp_functions[tool["name"]] = make_mcp_wrapper(
                mcp_connection, tool["name"], tool["parameters"])

    namespace = create_namespace(sandbox_config, mcp_functions, workspace)

    while True:
        code = sandbox_connection.recv()
        if code["type"] == "shutdown":
            break
        elif code["type"] == "execute":
            result = sandbox(code["code"], namespace)
            result_connection.send(result)


def create_sandbox(sandbox_config, mcp_connection, tool_infos, workspace):
    result_parent, result_child = multiprocessing.Pipe(duplex=False)

    sandbox_connection = multiprocessing.Pipe()
    process = multiprocessing.Process(
            target=sandbox_worker,
            args=(sandbox_config, result_child, mcp_connection,
                  sandbox_connection[0], tool_infos, workspace)
            )

    process.start()

    return process, result_parent, sandbox_connection[1]
