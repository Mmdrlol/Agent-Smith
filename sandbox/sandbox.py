import builtins
from contextlib import redirect_stdout, redirect_stderr
from io import StringIO
import traceback
import linecache
from pathlib import Path
import multiprocessing
import resource
import socket


def is_path_allowed(file_path, sandbox_config):
    real_path = Path(file_path).resolve(strict=False)

    for allowed in sandbox_config.allowed_directories:
        allowed_path = Path(allowed).resolve(strict=False)
        if real_path.is_relative_to(allowed_path):
            return True
    return False


def get_restricted_open(sandbox_config):
    def restricted_open(file_path, *args, **kwargs):
        if not is_path_allowed(file_path, sandbox_config):
            raise SandboxError(f"path '{file_path}' is not available.")
        return open(file_path, *args, **kwargs)
    return restricted_open


def get_builtins(sandbox_config):
    return {
            "print": print,
            "len": len,
            "range": range,
            "open": get_restricted_open(sandbox_config),
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


def create_namespace(sandbox_config, mcp_functions):
    namespace = {
            "__builtins__": {}
            }
    namespace["__builtins__"].update(get_builtins(sandbox_config))
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


def sandbox_worker(sandbox_config, result_queue, mcp_connection,
                   sandbox_connection, tool_infos):
    max_memory = sandbox_config.max_memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS,
                       (max_memory, max_memory))
    desable_networking()

    mcp_functions = {}
    for tool in tool_infos:
        mcp_functions[tool["name"]] = make_mcp_wrapper(
                mcp_connection, tool["name"], tool["parameters"])

    namespace = create_namespace(sandbox_config, mcp_functions)

    while True:
        code = sandbox_connection.recv()
        if code["type"] == "shutdown":
            break
        elif code["type"] == "execute":
            result = sandbox(code["code"], namespace)
            result_queue.put(result)


def create_sandbox(sandbox_config, mcp_connection, tool_infos):
    result_queue = multiprocessing.Queue()

    sandbox_connection = multiprocessing.Pipe()
    process = multiprocessing.Process(
            target=sandbox_worker,
            args=(sandbox_config, result_queue,
                  mcp_connection, sandbox_connection[0], tool_infos)
            )

    process.start()

    return process, result_queue, sandbox_connection[1]
