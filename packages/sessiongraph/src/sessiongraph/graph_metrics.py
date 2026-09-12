from __future__ import annotations

from typing import Any


def _networkx():
    try:
        import networkx as nx
    except ImportError as exc:
        raise ValueError(
            'NetworkX metrics require the optional graph extra: pip install "sessiongraph[graph]"'
        ) from exc
    return nx


def build_networkx(analysis: dict[str, Any]):
    """Build a NetworkX graph from content-free SessionGraph analysis."""
    nx = _networkx()
    graph_data = analysis.get("graph")
    if not isinstance(graph_data, dict):
        raise ValueError("malformed analysis.json: graph must be an object")
    nodes = graph_data.get("nodes")
    edges = graph_data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("malformed analysis.json: graph needs node and edge arrays")

    graph = nx.MultiDiGraph()
    declared: set[str] = set()
    node_rows: dict[str, dict[str, Any]] = {}
    for row in nodes:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            raise ValueError("malformed analysis.json: every graph node needs a nonempty string id")
        node_id = row["id"]
        if node_id in declared:
            raise ValueError(f"malformed analysis.json: duplicate graph node id {node_id!r}")
        declared.add(node_id)
        node_rows[node_id] = row
        graph.add_node(node_id, **row)

    relations: dict[str, int] = {}
    for row in edges:
        if (not isinstance(row, dict) or not isinstance(row.get("from"), str)
                or not row["from"] or not isinstance(row.get("to"), str) or not row["to"]):
            raise ValueError("malformed analysis.json: every graph edge needs nonempty string from/to ids")
        relation = row.get("relation", "precedes")
        if not isinstance(relation, str) or not relation:
            raise ValueError("malformed analysis.json: edge relation must be a nonempty string")
        graph.add_edge(row["from"], row["to"], relation=relation)
        relations[relation] = relations.get(relation, 0) + 1

    return nx, graph, declared, node_rows, relations


def measure_graph(analysis: dict[str, Any]) -> dict[str, Any]:
    """Measure an analysis graph without treating topology as answer quality."""
    nx, graph, declared, node_rows, relations = build_networkx(analysis)

    simple = nx.DiGraph(graph)
    dag = nx.is_directed_acyclic_graph(simple)
    cycle_nodes: set[str] = set()
    if not dag:
        cycle_nodes.update(node for component in nx.strongly_connected_components(simple)
                           if len(component) > 1 for node in component)
        cycle_nodes.update(node for node in simple if simple.has_edge(node, node))
    roots = sorted(node for node in declared if simple.in_degree(node) == 0)
    leaves = sorted(node for node in declared if simple.out_degree(node) == 0)
    components = list(nx.weakly_connected_components(simple)) if simple else []

    request_kinds = {"user_request", "iseeagents_payload", "iseeagents_dispatch"}
    output_kinds = {"response", "final_response", "iseeagents_response"}
    request_roots = sorted(node_id for node_id, row in node_rows.items()
                           if row.get("kind") in request_kinds
                           or (row.get("kind") == "iseeagents_load"
                               and row.get("role") == "user_input")
                           or (row.get("kind") == "message" and row.get("role") == "user"))
    outputs = sorted(node_id for node_id, row in node_rows.items()
                     if row.get("kind") in output_kinds
                     or (row.get("kind") == "message" and row.get("role") == "assistant"))
    reachable_outputs = sorted(output for output in outputs if any(
        root == output or nx.has_path(simple, root, output) for root in request_roots
    ))

    changed_artifacts: set[str] = set()
    verified_artifacts: set[str] = set()
    for source, target, data in graph.edges(data=True):
        relation = data["relation"]
        if relation in {"created", "modified"}:
            changed_artifacts.add(target)
    for source, target, data in graph.edges(data=True):
        if (data["relation"] == "verified_by" and source in changed_artifacts
                and target in node_rows and not node_rows[target].get("is_error", False)):
            verified_artifacts.add(source)

    return {
        "schema_version": 1,
        "engine": f"networkx-{nx.__version__}",
        "session": analysis.get("session", {}).get("id"),
        "metrics": {
            "declared_nodes": len(declared),
            "implicit_nodes": len(set(graph) - declared),
            "edges": graph.number_of_edges(),
            "roots": len(roots),
            "leaves": len(leaves),
            "weakly_connected_components": len(components),
            "is_directed_acyclic": dag,
            "cycle_nodes": len(cycle_nodes),
            "max_depth": nx.dag_longest_path_length(simple) if dag and simple else None,
            "request_roots": len(request_roots),
            "outputs": len(outputs),
            "reachable_outputs": len(reachable_outputs),
            "request_output_coverage": (len(reachable_outputs) / len(outputs)) if outputs else None,
            "changed_artifacts": len(changed_artifacts),
            "verified_artifacts": len(verified_artifacts),
            "artifact_verification_coverage": (
                len(verified_artifacts) / len(changed_artifacts) if changed_artifacts else None
            ),
            "relation_counts": dict(sorted(relations.items())),
        },
        "evidence": {
            "roots": roots,
            "leaves": leaves,
            "cycle_nodes": sorted(cycle_nodes),
            "request_roots": request_roots,
            "outputs": outputs,
            "reachable_outputs": reachable_outputs,
            "changed_artifacts": sorted(changed_artifacts),
            "verified_artifacts": sorted(verified_artifacts),
        },
        "scope": "structural measurements only; topology does not establish answer or code quality",
    }
