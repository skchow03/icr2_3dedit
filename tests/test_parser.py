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
        parsed = parse_document("a: NIL;\na: NIL;\n")
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
        parsed = parse_document("hub: NIL; % invalid inline comment\n")
        errors = [item for item in analyze(parsed) if item.severity is Severity.ERROR]
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0].line, 1)
        self.assertIn("must be on their own line", errors[0].message)

    def test_indented_comment_is_not_an_inline_comment(self) -> None:
        parsed = parse_document("  % valid full-line comment\nhub: NIL;\n")
        errors = [item for item in analyze(parsed) if item.severity is Severity.ERROR]
        self.assertEqual(errors, [])


if __name__ == "__main__":
    unittest.main()
