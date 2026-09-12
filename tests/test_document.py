from pathlib import Path
import tempfile
import unittest
from unittest import mock

from icr2_3dedit.document import SourceDocument


class SourceDocumentTests(unittest.TestCase):
    def test_unchanged_document_is_byte_identical(self) -> None:
        original = b"3D VERSION 3.0;\r\n\r\nnil: NIL;\r\n"
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.3D"
            copy = Path(directory) / "copy.3D"
            source.write_bytes(original)
            document = SourceDocument.load(source)
            document.save(copy)
            self.assertEqual(copy.read_bytes(), original)

    def test_unchanged_cp1252_is_byte_identical(self) -> None:
        original = "3D VERSION 3.0;\r\nname: DATA \"café\";\r\n".encode("cp1252")
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "sample.3D"
            copy = Path(directory) / "copy.3D"
            source.write_bytes(original)
            document = SourceDocument.load(source)
            self.assertEqual(document.encoding, "cp1252")
            document.save(copy)
            self.assertEqual(copy.read_bytes(), original)

    def test_utf8_bom_is_preserved(self) -> None:
        original = b"\xef\xbb\xbf3D VERSION 3.0;\nroot: NIL;\n"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bom.3D"
            path.write_bytes(original)
            document = SourceDocument.load(path)
            document.text += "% note\n"
            document.save()
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))

    def test_edited_crlf_retains_crlf_and_becomes_clean(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.3D"
            path.write_bytes(b"3D VERSION 3.0;\r\nroot: NIL;\r\n")
            document = SourceDocument.load(path)
            document.text += "extra: NIL;\n"
            self.assertTrue(document.dirty)
            document.save()
            self.assertNotIn(b"\n", path.read_bytes().replace(b"\r\n", b""))
            self.assertFalse(document.dirty)

    def test_failed_encoding_does_not_corrupt_destination(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.3D"
            original = "3D VERSION 3.0;\r\nname: DATA \"café\";\r\n".encode("cp1252")
            path.write_bytes(original)
            document = SourceDocument.load(path)
            document.text += "emoji: DATA \"😀\";\n"
            with self.assertRaises(UnicodeEncodeError):
                document.save()
            self.assertEqual(path.read_bytes(), original)
            self.assertTrue(document.dirty)

    def test_atomic_failure_cleans_temporary_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sample.3D"
            path.write_bytes(b"old")
            document = SourceDocument("new", path=path)
            document.text = "changed"
            with mock.patch("icr2_3dedit.document.os.replace", side_effect=OSError("no")):
                with self.assertRaises(OSError):
                    document.save()
            self.assertEqual(path.read_bytes(), b"old")
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
