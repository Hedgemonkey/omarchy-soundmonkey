def make_pw_node(node_id, media_class, description, name=None):
    """Build a minimal pw-dump object matching the shape SinkManager parses."""
    props = {"media.class": media_class, "node.description": description}
    if name is not None:
        props["node.name"] = name
    return {"id": node_id, "info": {"props": props}}
