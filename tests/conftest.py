import os
import sys

# Make the daemon package importable as `soundmonkey.*` without installing it.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "daemon"))


def make_pw_node(node_id, media_class, description, name=None):
    """Build a minimal pw-dump object matching the shape SinkManager parses."""
    props = {"media.class": media_class, "node.description": description}
    if name is not None:
        props["node.name"] = name
    return {"id": node_id, "info": {"props": props}}
