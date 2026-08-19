def generate_manual(tools):
    return (
        "You are executing Python code inside a restricted sandbox.\n\n"
        "The repository workspace is /testbed, do not try to access files "
        "in other folders.\n"
        "Use repository-relative paths when supported by the tool.\n"
        "Do not guess filesystem locations.\n"
        "Sandbox restrictions:\n"
        "- Builtin functions are restricted.\n"
        "- Python imports are restricted.\n"
        "- File access is limited to authorized directories.\n"
        "- Networking is disabled.\n"
        "- Execution time and memory are limited.\n\n"
        "Here are all available MCP tools inside the sandbox:\n\n"
        f"{
            '\n'.join(
                f'{tool.name}({
                    ", ".join(
                        f"{key}: {value.get("type", "unknown")}"
                        for key, value in tool.inputSchema[
                            "properties"].items()
                    )
                })\n    {tool.description}\n    Returns: {
                    tool.outputSchema["properties"]["result"].get("type",
                                                                  "unknown")
                }\n'
                for tool in tools.tools
            )
        }"
    )
