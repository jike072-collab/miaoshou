import unittest

from lib.text_gateway import TextGatewayError, parse_localization


class TextGatewayTest(unittest.TestCase):
    def test_parses_fenced_json(self):
        value = parse_localization('```json\n{"en":{"title":"Shoe"},"th":{"title":"รองเท้า"},"vi":{"title":"Giày"}}\n```')
        self.assertEqual(value["en"]["title"], "Shoe")
        self.assertEqual(value["vi"]["description"], "")

    def test_rejects_missing_language(self):
        with self.assertRaises(TextGatewayError):
            parse_localization('{"en":{"title":"Shoe"}}')


if __name__ == "__main__":
    unittest.main()
