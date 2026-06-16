import unittest
from unittest.mock import patch

from lib.image_inspector import analyze_candidate_images, inspect_image_source


def png_bytes(width=800, height=800):
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 8 + width.to_bytes(4, "big") + height.to_bytes(4, "big") + b"\x00" * 16


class ImageInspectorTest(unittest.TestCase):
    def test_original_usable_when_size_and_url_are_clean(self):
        result = inspect_image_source("https://cbu01.alicdn.com/img/clean-product.jpg", png_bytes())

        self.assertEqual(result["status"], "original_usable")
        self.assertTrue(result["usable"])
        self.assertEqual(result["details"]["width"], 800)
        self.assertFalse(result["details"]["ocrAvailable"])

    def test_platform_marker_blocks_original_image(self):
        result = inspect_image_source("https://cbu01.alicdn.com/img/taobao-watermark.jpg", png_bytes())

        self.assertEqual(result["status"], "needs_cleanup")
        self.assertIn("存在平台标识", result["reasons"])
        self.assertIn("存在明显水印", result["reasons"])

    def test_small_image_needs_generation(self):
        result = inspect_image_source("https://cbu01.alicdn.com/img/clean-product.jpg", png_bytes(320, 320))

        self.assertEqual(result["status"], "needs_cleanup")
        self.assertIn("图片尺寸过小", result["reasons"])

    def test_candidate_needs_generation_when_usable_images_are_not_enough(self):
        candidate = {"images": ["https://cbu01.alicdn.com/img/a.jpg"]}
        with patch("lib.image_inspector.fetch_image", return_value=(png_bytes(), "image/png")):
            result = analyze_candidate_images(candidate)

        self.assertEqual(result["status"], "needs_generation")
        self.assertEqual(result["details"]["usableImages"], 1)
        self.assertIn("图片数量不足", result["reasons"])


if __name__ == "__main__":
    unittest.main()
