def generate_routing_instructions(server_infos: dict) -> dict:
    """
    Generate routing instructions for the given servers information coming from MCP servers.

    Args:
        server_infos (dict): A dictionary containing information on MCP servers.

    Returns:
        dict: A dictionary containing routing instructions.
    """
    routing_instructions = {}
    for server_name, info in server_infos.items():
        content = f"Server: {server_name}\n---\n"
        tools = info.get("tools")
        if tools:
            content += "Provides tools:\n"
            for tool in tools.tools:
                content += f"- {tool.name}: {tool.description}\n"
            content += "---\n"
        prompts = info.get("prompts")
        if prompts:
            content += "Provides prompts:\n"
            for prompt in prompts.prompts:
                content += f"- {prompt.name}: {prompt.description}\n"
            content += "---\n"
        resources = info.get("resources")
        if resources:
            content += "Provides resources:\n"
            for resource in resources.resources:
                content += f"- {resource.name}: {resource.description}\n"
            content += "---\n"
        routing_instructions[server_name] = content
    return routing_instructions