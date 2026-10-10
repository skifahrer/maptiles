import unittest

from load import needs, worker


@needs("mwparserfromhell")
class ToText(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.to_text = staticmethod(worker("wiki/articles.py").to_text)

    def test_picture_with_caption(self):
        # fix 1718: image captions stayed in the text
        text = self.to_text("Hrad.\n[[Súbor:Devin.jpg|náhľad|Hrad [[Devín]] v lete]]\nKoniec.")
        self.assertNotIn("náhľad", text)
        self.assertNotIn("v lete", text)
        self.assertIn("Hrad.", text)
        self.assertIn("Koniec.", text)

    def test_category_line(self):
        self.assertEqual(self.to_text("Text.\n[[Kategória:Hrady na Slovensku]]"), "Text.")

    def test_nested_tables(self):
        text = self.to_text("Pred.\n{| class=x\n| a\n{|\n| b\n|}\n| c\n|}\nPo.")
        self.assertEqual(text.split(), ["Pred.", "Po."])

    def test_gallery(self):
        text = self.to_text("A.\n<gallery>\nFile:x.jpg|caption\n</gallery>\nB.")
        self.assertNotIn("caption", text)

    def test_blank_lines_collapse(self):
        self.assertEqual(self.to_text("A.\n\n\n\n\nB."), "A.\n\nB.")

    def test_link_keeps_text(self):
        self.assertEqual(self.to_text("Leží pri [[Dunaj|Dunaji]] a [[Morava]]."),
                         "Leží pri Dunaji a Morava.")


if __name__ == "__main__":
    unittest.main()
