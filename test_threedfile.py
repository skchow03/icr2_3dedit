from pathlib import Path
from icr2_3dedit.threedfile import ThreeDFile

FILES = [
    Path("tests/fixtures/roadcar.3d"),
    Path("tests/fixtures/RENO.3D"),
]

# Optional explicit definitions to inspect. Leave as None to automatically pick
# the first structurally interesting definition in each file.
TREE_DEFINITIONS = {
    "roadcar.3d": None,
    "RENO.3D": None,
}
TREE_MAX_DEPTH = 12
TREE_MAX_NODES = 100


def node_label(f, node):
    if node.kind == "definition":
        return f"Definition {node.name!r} [Node {node.node_id}]"
    if node.kind == "command":
        return f"Command {node.command} [Node {node.node_id}]"
    if node.kind == "reference":
        target = next((r.target_node_id for r in f.references if r.node_id == node.node_id), None)
        suffix = f" -> Node {target}" if target is not None else " -> unresolved"
        return f"Reference {node.name!r}{suffix} [Node {node.node_id}]"
    if node.kind == "group":
        delimiters = f"{node.opener or ''}{node.closer or ''}"
        return f"Group {delimiters!r} [Node {node.node_id}]"
    return f"{node.kind} [Node {node.node_id}]"


def pick_tree_definition(f, requested_name=None):
    if requested_name:
        ids = f.symbols.get(requested_name)
        return ids[0] if ids else None

    # Prefer a definition containing nested commands because that is the most
    # useful visual check of the structural parser. Fall back to any definition
    # with children.
    fallback = None
    for did in f.top_level_nodes:
        root = f.nodes_by_id[did]
        if not root.children:
            continue
        if fallback is None:
            fallback = did
        stack = [(child, 1) for child in root.children]
        command_depths = []
        while stack:
            nid, depth = stack.pop()
            node = f.nodes_by_id[nid]
            if node.kind == "command":
                command_depths.append(depth)
                if len(command_depths) >= 2 and max(command_depths) > min(command_depths):
                    return did
            stack.extend((child, depth + 1) for child in node.children)
    return fallback


def print_tree(f, root_id, max_depth=TREE_MAX_DEPTH, max_nodes=TREE_MAX_NODES):
    """Print a structural subtree iteratively so deep files cannot recurse Python."""
    printed = 0
    stack = [(root_id, "", True, 0)]
    while stack and printed < max_nodes:
        nid, prefix, is_last, depth = stack.pop()
        node = f.nodes_by_id[nid]
        connector = "" if depth == 0 else ("└─ " if is_last else "├─ ")
        print(prefix + connector + node_label(f, node))
        printed += 1

        if depth >= max_depth:
            if node.children:
                child_prefix = prefix + ("   " if is_last else "│  ")
                print(child_prefix + f"└─ ... {len(node.children)} child node(s) hidden by depth limit")
            continue

        children = node.children
        child_prefix = prefix if depth == 0 else prefix + ("   " if is_last else "│  ")
        for index in range(len(children) - 1, -1, -1):
            child = children[index]
            stack.append((child, child_prefix, index == len(children) - 1, depth + 1))

    if stack:
        print(f"... tree truncated after {max_nodes} nodes")


print("=" * 70)
print("ThreeDFile STEP 1 TEST")
print("=" * 70)

for path in FILES:
    print(f"\nTesting: {path}")
    print("-" * 70)

    if not path.exists():
        print("FILE NOT FOUND")
        continue

    try:
        original = path.read_bytes()
        f = ThreeDFile.load(path)
        rebuilt = f.to_bytes()
        exact = original == rebuilt

        print(f"File size:          {len(original):,} bytes")
        print(f"Tokens:             {len(f.tokens):,}")
        print(f"Nodes:              {len(f.nodes_by_id):,}")
        print(f"Top-level nodes:    {len(f.top_level_nodes):,}")
        print(f"Symbols:            {len(f.symbols):,}")
        print(f"References:         {len(f.references):,}")
        print(f"Diagnostics:        {len(f.diagnostics):,}")
        print(f"Maximum nesting:    {f.max_nesting_depth}")
        print(f"Parse time:         {f.parse_seconds:.4f} seconds")
        print(f"Exact reconstruction: {exact}")

        print("\nFirst 10 top-level definitions:")
        for node_id in f.top_level_nodes[:10]:
            node = f.nodes_by_id[node_id]
            print(
                f"  Node {node.node_id:<6} "
                f"name={node.name!r:<25} "
                f"children={len(node.children)}"
            )

        requested = TREE_DEFINITIONS.get(path.name)
        tree_root = pick_tree_definition(f, requested)
        print("\nStructural tree sample:")
        if tree_root is None:
            if requested:
                print(f"  Definition {requested!r} not found.")
            else:
                print("  No definition with structural children found.")
        else:
            print_tree(f, tree_root)

        if f.diagnostics:
            print("\nFirst 10 diagnostics:")
            for d in f.diagnostics[:10]:
                print(
                    f"  {d.severity.upper():7} "
                    f"line {d.line:<6} "
                    f"{d.code}: {d.message}"
                )

        print()
        if exact:
            print("PASS: File reconstructs byte-for-byte.")
        else:
            print("FAIL: Reconstructed file differs from original.")

    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")

print("\n" + "=" * 70)
print("TEST COMPLETE")
print("=" * 70)
