import base64
import unittest

from lib.image_gateway import _extract_images, _path_value, _render_template


class ImageGatewayTest(unittest.TestCase):
    def test_custom_template_and_nested_response_path(self):
        template = {"model": "{{model}}", "input": {"prompt": "{{prompt}}", "image": "{{image_base64}}"}}
        rendered = _render_template(template, {"model": "img-test", "prompt": "square", "image_base64": "abc"})
        self.assertEqual(rendered["input"]["image"], "abc")
        payload = {"result": {"images": [{"b64_json": base64.b64encode(b"png").decode()}]}}
        self.assertEqual(_extract_images(payload, "result.images"), [("bytes", b"png")])

    def test_task_path_supports_nested_values_and_list_indexes(self):
        self.assertEqual(_path_value({"data": [{"task": {"id": "42"}}]}, "data.0.task.id"), "42")


if __name__ == "__main__":
    unittest.main()
