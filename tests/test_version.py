import unittest
import os
import json

class TestVersionEndpoint(unittest.TestCase):
    def setUp(self):
        # Set WEBHOOK_SECRET in environment if not present so server can import
        if "WEBHOOK_SECRET" not in os.environ:
            os.environ["WEBHOOK_SECRET"] = "test_webhook_secret_for_tests"
        import server
        self.app = server.app.test_client()
        self.app.testing = True

    def test_version_file_exists(self):
        version_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "VERSION")
        self.assertTrue(os.path.exists(version_path), "VERSION file should exist in project root")
        with open(version_path, "r") as f:
            v = f.read().strip()
        self.assertEqual(v, "v2.0.0")

    def test_version_endpoint(self):
        res = self.app.get('/version')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get("version"), "v2.0.0")
        self.assertIn("status", data)

    def test_health_includes_version(self):
        res = self.app.get('/health')
        self.assertEqual(res.status_code, 200)
        data = json.loads(res.data)
        self.assertEqual(data.get("version"), "v2.0.0")

if __name__ == '__main__':
    unittest.main()
