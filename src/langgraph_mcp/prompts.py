"""Default prompts."""

ROUTING_QUERY_SYSTEM_PROMPT = """Generate query to search the right Model Context Protocol (MCP) server document that may help with user's message. Previously, we made the following queries:
    
<previous_queries/>
{queries}
</previous_queries>

System time: {system_time}"""
