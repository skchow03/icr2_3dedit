import unittest

from icr2_3dedit.analysis import Severity, analyze
from icr2_3dedit.parser import parse_document


SOURCE = """3D VERSION 3.0;

nil: NIL;
a: [<0, 1, 2>];
b: [<3, 4, 5>];
body: POLY <32> {a, b};
root: LIST {body};
"""


class ParserTests(unittest.TestCase):
    def test_definitions_and_kinds(self) -> None:
        parsed = parse_document(SOURCE)
        self.assertEqual(parsed.definitions["a"].kind, "vertex")
        self.assertEqual(parsed.definitions["body"].kind, "POLY")
        self.assertEqual(parsed.definitions["root"].kind, "LIST")

    def test_forward_and_backward_references_are_resolved(self) -> None:
        parsed = parse_document(SOURCE)
        self.assertEqual(parsed.definitions["body"].references, ("a", "b"))
        self.assertEqual(parsed.definitions["root"].references, ("body",))

    def test_duplicate_definition_is_error(self) -> None:
        parsed = parse_document("3D VERSION 3.0;\na: NIL;\na: NIL;\n")
        errors = [item for item in analyze(parsed) if item.severity is Severity.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertIn("Duplicate definition", errors[0].message)

    def test_statement_ranges_preserve_source(self) -> None:
        parsed = parse_document(SOURCE)
        reconstructed = "".join(item.text for item in parsed.statements)
        self.assertEqual(reconstructed, SOURCE)

    def test_comment_before_definition_is_preserved_and_parsed(self) -> None:
        source = "% wheel hub\n  % retained\nhub: [<0, 0, 0>];\n"
        parsed = parse_document(source)
        self.assertIn("hub", parsed.definitions)
        self.assertEqual(parsed.definitions["hub"].line, 3)
        self.assertEqual("".join(item.text for item in parsed.statements), source)

    def test_semicolon_in_comment_does_not_end_statement(self) -> None:
        source = "% not a statement; still a comment\nhub: NIL;\n"
        parsed = parse_document(source)
        self.assertEqual(len(parsed.statements), 2)
        self.assertIn("hub", parsed.definitions)

    def test_inline_comment_is_an_error(self) -> None:
        parsed = parse_document("3D VERSION 3.0;\nhub: NIL; % invalid inline comment\n")
        errors = [item for item in analyze(parsed) if item.severity is Severity.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line, 2)
        self.assertIn("must be on their own line", errors[0].message)

    def test_indented_comment_is_not_an_inline_comment(self) -> None:
        parsed = parse_document("3D VERSION 3.0;\n  % valid full-line comment\nhub: NIL;\n")
        errors = [item for item in analyze(parsed) if item.severity is Severity.ERROR]
        self.assertEqual(errors, [])

    def test_semicolon_in_quote_does_not_end_statement(self) -> None:
        parsed = parse_document('3D VERSION 3.0;\nitem: DATA "a;b";\n')
        self.assertEqual(len(parsed.statements), 3)
        self.assertIn("item", parsed.definitions)

    def test_unterminated_quote_and_missing_semicolon(self) -> None:
        parsed = parse_document('3D VERSION 3.0;\nitem: DATA "oops')
        messages = [item.message for item in analyze(parsed)]
        self.assertTrue(any("Unterminated quoted" in message for message in messages))
        self.assertTrue(any("missing semicolon" in message for message in messages))

    def test_invalid_header(self) -> None:
        messages = [item.message for item in analyze(parse_document("root: NIL;\n"))]
        self.assertTrue(any("VERSION 3.0" in message for message in messages))

    def test_bspf_is_recognized(self) -> None:
        parsed = parse_document("3D VERSION 3.0;\nroot: BSPF {NIL};\n")
        self.assertEqual(parsed.definitions["root"].kind, "BSPF")
        self.assertFalse(any("Unknown command" in d.message for d in analyze(parsed)))

    def test_uppercase_and_underscore_unresolved_references(self) -> None:
        parsed = parse_document("3D VERSION 3.0;\nroot: LIST {MISSING, _private};\n")
        messages = [item.message for item in analyze(parsed)]
        self.assertTrue(any("MISSING" in message for message in messages))
        self.assertTrue(any("_private" in message for message in messages))

    def test_strings_are_not_references(self) -> None:
        parsed = parse_document('3D VERSION 3.0;\nroot: DATA "MISSING";\n')
        self.assertEqual(parsed.definitions["root"].reference_tokens, ())

    def test_exact_reference_token_ranges(self) -> None:
        source = "3D VERSION 3.0;\nvertex: [<0,0,0>];\nroot: LIST {vertex};\n"
        parsed = parse_document(source)
        token = parsed.definitions["root"].reference_tokens[0]
        self.assertEqual(source[token.start:token.end], "vertex")

    def test_explicit_root_and_reachable_vertices_not_unused(self) -> None:
        diagnostics = analyze(parse_document(SOURCE))
        unused = [item.message for item in diagnostics if "unreachable" in item.message]
        self.assertNotIn("Definition is unreachable: root", unused)
        self.assertNotIn("Definition is unreachable: a", unused)

    def test_inferred_final_entry_and_unreachable_vertex(self) -> None:
        source = "3D VERSION 3.0;\nlost: [<0,0,0>];\nused: [<1,1,1>];\nbody: POLY {used};\n"
        messages = [item.message for item in analyze(parse_document(source))]
        self.assertIn("Definition is unreachable: lost", messages)
        self.assertNotIn("Definition is unreachable: body", messages)

    def test_cycles_are_safe_and_reported(self) -> None:
        source = "3D VERSION 3.0;\na: LIST {b};\nb: LIST {a};\nroot: LIST {a};\n"
        messages = [item.message for item in analyze(parse_document(source))]
        self.assertTrue(any("Reference cycle" in message for message in messages))


if __name__ == "__main__":
    unittest.main()
