from mcp_server.main import mcp

mcp.remove_tool("read_file")
mcp.remove_tool("list_files")
mcp.remove_tool("search_code")
mcp.remove_tool("search_function_or_class_definition_in_code")
mcp.remove_tool("find_references")
mcp.remove_tool("get_patch")
mcp.remove_tool("run_command")

if __name__ == "__main__":
    mcp.run()
