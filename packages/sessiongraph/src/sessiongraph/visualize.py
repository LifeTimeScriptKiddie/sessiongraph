from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any

from .graph_metrics import build_networkx


COLORS = {
    "user_request": "#2563eb",
    "message": "#64748b",
    "tool_call": "#d97706",
    "tool_result": "#ca8a04",
    "artifact": "#7c3aed",
    "test_run": "#059669",
    "review": "#db2777",
    "response": "#0891b2",
    "final_response": "#0891b2",
}


def _pyvis_network():
    try:
        from pyvis.network import Network
    except ImportError as exc:
        raise ValueError(
            'Interactive visualization requires the optional visual extra: '
            'pip install "sessiongraph[visual]"'
        ) from exc
    return Network


def write_interactive_html(analysis: dict[str, Any], destination: Path) -> Path:
    """Write a content-free, self-contained interactive graph explorer."""
    Network = _pyvis_network()
    _, graph, declared, node_rows, _ = build_networkx(analysis)
    network = Network(
        height="850px", width="100%", directed=True, bgcolor="#f8fafc",
        font_color="#0f172a", select_menu=True, filter_menu=True,
        cdn_resources="in_line",
    )
    safe_ids = {node_id: f"n{index}" for index, node_id in enumerate(graph.nodes)}
    for node_id in graph.nodes:
        row = node_rows.get(node_id, {})
        kind = str(row.get("kind") or "missing_parent")
        role = str(row.get("role") or "")
        name = str(row.get("name") or "")
        status = "error" if row.get("is_error") else "recorded"
        label = escape(name or kind)
        title = escape(
            f"id: {node_id}\nkind: {kind}\nrole: {role or '-'}\nstatus: {status}"
        ).replace("\n", "<br>")
        network.add_node(
            safe_ids[node_id],
            label=label,
            title=title,
            group=escape(kind),
            color=COLORS.get(kind, "#94a3b8" if node_id in declared else "#ef4444"),
            shape="box" if kind in {"artifact", "test_run", "review"} else "dot",
        )
    for source, target, data in graph.edges(data=True):
        relation = str(data.get("relation") or "precedes")
        safe_relation = escape(relation)
        network.add_edge(
            safe_ids[source], safe_ids[target], label=safe_relation, title=safe_relation, arrows="to"
        )
    network.set_options("""
    {
      "layout": {"hierarchical": {"enabled": true, "direction": "LR", "sortMethod": "directed"}},
      "physics": {"enabled": false},
      "interaction": {"hover": true, "navigationButtons": true, "keyboard": true},
      "edges": {"smooth": {"type": "cubicBezier"}, "font": {"size": 10, "align": "middle"}},
      "nodes": {"font": {"size": 13}, "margin": 10}
    }
    """)
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # PyVis write_html uses the platform default encoding (cp1252 on Windows).
    # Its inline assets contain Unicode, so write the generated page as UTF-8.
    destination.write_text(network.generate_html(notebook=False), encoding="utf-8")
    return destination
