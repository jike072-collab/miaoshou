import json
import unittest
from unittest.mock import patch

from lib.collector import ProductHTMLParser, _meta_value, _product_json_ld, _validate_public_url, _weight_grams


class CollectorParserTest(unittest.TestCase):
    def test_extracts_meta_and_product_json_ld(self):
        payload = {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "测试商品",
            "sku": "SKU-100",
            "weight": {"value": 1.2, "unitCode": "KGM"},
        }
        html = """
        <html><head>
          <meta property="og:title" content="Open Graph 标题">
          <script type="application/ld+json">%s</script>
        </head></html>
        """ % json.dumps(payload, ensure_ascii=False)
        parser = ProductHTMLParser()
        parser.feed(html)

        self.assertEqual(_meta_value(parser, "og:title"), "Open Graph 标题")
        self.assertEqual(_product_json_ld(parser)["sku"], "SKU-100")
        self.assertEqual(_weight_grams(_product_json_ld(parser)), 1200)

    def test_pound_weight_conversion(self):
        product = {"weight": {"value": 2, "unitText": "lb"}}
        self.assertAlmostEqual(_weight_grams(product), 907.18, places=2)

    def test_allows_1688_public_domains_without_dns_lookup(self):
        with patch("lib.collector.socket.getaddrinfo") as lookup:
            parsed = _validate_public_url("https://detail.1688.com/offer/123.html")
        self.assertEqual(parsed.hostname, "detail.1688.com")
        lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
