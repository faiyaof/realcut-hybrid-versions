import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import web_server


class WebRequestSecurityTests(unittest.TestCase):
    def test_default_listener_is_loopback(self):
        self.assertEqual(web_server.DEFAULT_HOST, "127.0.0.1")

    def test_host_validation_blocks_dns_rebinding(self):
        self.assertTrue(
            web_server.request_host_allowed(
                "127.0.0.1:8765", 8765, "127.0.0.1"
            )
        )
        self.assertTrue(
            web_server.request_host_allowed("localhost:8765", 8765, "127.0.0.1")
        )
        self.assertTrue(
            web_server.request_host_allowed(
                "192.168.1.20:8765", 8765, "192.168.1.20"
            )
        )
        self.assertFalse(
            web_server.request_host_allowed(
                "attacker.example:8765", 8765, "127.0.0.1"
            )
        )
        self.assertFalse(
            web_server.request_host_allowed(
                "127.0.0.1:9999", 8765, "127.0.0.1"
            )
        )

    def test_origin_must_match_host(self):
        self.assertTrue(
            web_server.origin_matches_host(
                "http://127.0.0.1:8765", "127.0.0.1:8765"
            )
        )
        self.assertFalse(
            web_server.origin_matches_host(
                "https://attacker.example", "127.0.0.1:8765"
            )
        )

    def test_post_requires_marker_and_same_origin(self):
        server = ThreadingHTTPServer(
            ("127.0.0.1", 0), web_server.RealCutHandler
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        port = server.server_address[1]
        try:
            status, _ = self._post(port, headers={})
            self.assertEqual(status, 403)

            status, _ = self._post(
                port,
                headers={
                    "X-RealCut-Request": "1",
                    "Origin": "http://attacker.example",
                },
            )
            self.assertEqual(status, 403)

            with mock.patch.object(
                web_server, "run_environment_check", return_value={"ok": True}
            ):
                status, body = self._post(
                    port,
                    headers={
                        "X-RealCut-Request": "1",
                        "Origin": f"http://127.0.0.1:{port}",
                    },
                )
            self.assertEqual(status, 200)
            self.assertIn(b'"ok": true', body)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)

    @staticmethod
    def _post(port: int, headers: dict[str, str]) -> tuple[int, bytes]:
        connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        request_headers = {"Content-Type": "application/json", **headers}
        try:
            connection.request("POST", "/api/check", body="{}", headers=request_headers)
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
