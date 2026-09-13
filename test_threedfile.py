from pathlib import Path
from icr2_3dedit.threedfile import ThreeDFile

FILES = [
    Path("tests/fixtures/roadcar.3d"),
    Path("tests/fixtures/RENO.3D"),
]

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