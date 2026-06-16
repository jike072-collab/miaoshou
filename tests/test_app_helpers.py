import unittest

import app


class AppHelperTest(unittest.TestCase):
    def test_1688_keyword_uses_gbk_encoding_for_search_endpoint(self):
        self.assertEqual(app.encode_1688_keyword("运动鞋"), "%D4%CB%B6%AF%D0%AC")


if __name__ == "__main__":
    unittest.main()
