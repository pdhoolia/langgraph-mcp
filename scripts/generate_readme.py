import sys

configs = {
    "public": {
        "DEMO_VIDEO": "https://github.com/user-attachments/assets/f7f60d9b-528f-4103-a8a2-d974aaab5b0b",
        "REPO_URL": "https://github.com/pdhoolia/langgraph-mcp.git",
    },
    "enterprise": {
        "DEMO_VIDEO": "https://github.ibm.com/conversational-ai/langgraph-mcp/assets/14595/8fe59dae-c7e9-4236-862c-5bc21a75038e",
        "REPO_URL": "https://github.ibm.com/conversational-ai/langgraph-mcp.git",
    }
}

def main(env):
    with open("README.template.md", "r") as file:
        content = file.read()

    config = configs[env]
    for key, value in config.items():
        content = content.replace(f"{{{{{key}}}}}", value)

    with open("README.md", "w") as file:
        file.write(content)

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in configs:
        print("Usage: python generate_readme.py [public|enterprise]")
        sys.exit(1)

    main(sys.argv[1])