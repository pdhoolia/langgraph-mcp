from typing_extensions import TypedDict
from langgraph.graph import StateGraph, START, END

# --- Subgraph definition ---

class SubgraphState(TypedDict):
    value: int

def subgraph_node(state: SubgraphState):
    # Subgraph doubles the value
    return {"value": state["value"] * 2}

subgraph_builder = StateGraph(SubgraphState)
subgraph_builder.add_node("subgraph_node", subgraph_node)
subgraph_builder.add_edge(START, "subgraph_node")
subgraph_builder.add_edge("subgraph_node", END)
subgraph = subgraph_builder.compile()

# --- Main graph definition ---

class MainState(TypedDict):
    value: int
    used_subgraph: bool

def main_node(state: MainState):
    # If value is even, call the subgraph; else, just increment
    if state["value"] % 2 == 0:
        subgraph_result = subgraph.invoke({"value": state["value"]})
        return {
            "value": subgraph_result["value"],
            "used_subgraph": True
        }
    else:
        return {
            "value": state["value"] + 1,
            "used_subgraph": False
        }

main_builder = StateGraph(MainState)
main_builder.add_node("main_node", main_node)
main_builder.add_edge(START, "main_node")
main_builder.add_edge("main_node", END)
main_graph = main_builder.compile()

# --- Example usage ---

if __name__ == "__main__":
    # Case 1: value is even, subgraph is used
    result1 = main_graph.invoke({"value": 4, "used_subgraph": False})
    print("Input: 4 →", result1)  # Output: {'value': 8, 'used_subgraph': True}

    # Case 2: value is odd, subgraph is not used
    result2 = main_graph.invoke({"value": 5, "used_subgraph": False})
    print("Input: 5 →", result2)  # Output: {'value': 6, 'used_subgraph': False}
