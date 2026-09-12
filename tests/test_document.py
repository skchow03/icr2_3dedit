from pathlib import Path
import tempfile
import unittest

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


if __name__ == "__main__":
    unittest.main()

