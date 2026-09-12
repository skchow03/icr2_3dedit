from pathlib import Path

from icr2_3dedit.analysis import MAX_DIAGNOSTICS, analyze
from icr2_3dedit.document import SourceDocument
from icr2_3dedit.geometry import build_geometry_model
from icr2_3dedit.parser import SyntaxGroup, parse_document
from icr2_3dedit.syntax import TokenKind, tokenize


NESTED = """3D VERSION 3.0
DetailP_0-1: [<0,0,0>];
paint: [<0,0,0>, c=<248>];
root: FACE ([<0,0,0>], [<1,0,0>], [<0,1,0>]),
  BSPA ([<0,0,0>]), LIST {
    MATERIAL GROUP = 2, MIP = "walls", POLY [T] __walls__.c {
      [<0,0,0>, t=<0,0>], [<1,0,0>, t=<1,0>]
    }, LINE __walls__.c {DetailP_0-1},
    SWITCH DISTANCE ([<0,0,0>]) > {(10 ? DYNO {1,2,3}), (0 ? NIL)}
  }, DYNAMIC 0, 0, 0, EXTERN "tree";
"""


def _groups(items):
    for item in items:
        if isinstance(item, SyntaxGroup):
            yield item
            yield from _groups(item.children)


def test_tokenizer_is_lossless_and_covers_punctuation_and_members() -> None:
    tokens = tokenize(NESTED)
    assert "".join(token.text for token in tokens) == NESTED
    assert {TokenKind.COMMA, TokenKind.SEMICOLON, TokenKind.EQUALS,
            TokenKind.QUESTION, TokenKind.DOT, TokenKind.OPEN,
            TokenKind.CLOSE} <= {token.kind for token in tokens}
    member = next(i for i, token in enumerate(tokens)
                  if token.text == "c" and tokens[i - 1].kind is TokenKind.DOT)
    assert tokens[member - 1].kind is TokenKind.DOT


def test_non_semicolon_header_hyphens_and_nested_groups() -> None:
    parsed = parse_document(NESTED)
    assert parsed.header is not None and parsed.header.text == "3D VERSION 3.0"
    assert len(parsed.definitions) == 3
    assert parsed.definitions["DetailP_0-1"].line == 2
    root = parsed.definitions["root"]
    groups = list(_groups(root.syntax))
    assert all(group.closer is not None for group in groups)
    assert {group.opener.text for group in groups} == {"{", "(", "[", "<"}
    assert "walls" not in [token.name for token in root.reference_tokens]
    assert "c" not in [token.name for token in root.reference_tokens]
    assert "t" not in [token.name for token in root.reference_tokens]


def test_attribute_record_is_not_guessed_as_spatial_geometry() -> None:
    parsed = parse_document(NESTED)
    model = build_geometry_model(parsed)
    assert set(model.vertices) == {"DetailP_0-1"}
    assert parsed.definitions["paint"].kind == "record"
    assert set(model.unsupported_constructs) == {"FACE", "BSPA", "POLY", "LINE"}


def test_semicolon_header_remains_supported() -> None:
    parsed = parse_document("3D VERSION 3.0;\nroot: NIL;")
    assert parsed.header is not None
    assert "root" in parsed.definitions


def test_diagnostics_are_bounded() -> None:
    source = "3D VERSION 3.0;\n" + "".join(f"v{i}: LIST {{missing{i}}};\n" for i in range(300))
    diagnostics = analyze(parse_document(source))
    assert len(diagnostics) == MAX_DIAGNOSTICS
    assert "additional diagnostics omitted" in diagnostics[-1].message


def test_unchanged_nested_source_round_trip_is_byte_identical(tmp_path: Path) -> None:
    raw = NESTED.replace("\n", "\r\n").encode("ascii")
    source, copy = tmp_path / "nested.3D", tmp_path / "copy.3D"
    source.write_bytes(raw)
    document = SourceDocument.load(source)
    parse_document(document.text)
    document.save(copy)
    assert copy.read_bytes() == raw
