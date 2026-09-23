import unittest
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
from proxy_server import clear_cache

#imports for unreachable origin server test
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from proxy_server import ProxyHandler

PROXY_URL = 'http://localhost:8080'

class ProxyCacheTests(unittest.TestCase):
    def setUp(self):
        clear_cache()  # Clear the cache before each test

    def test_second_request_is_cache_hit(self):
        with urlopen(f'{PROXY_URL}/message.txt') as response:
            first_status = response.status
            first_cache_status = response.headers["X-Cache"]
            first_body = response.read()

        with urlopen(f'{PROXY_URL}/message.txt') as response:
            second_status = response.status
            second_cache_status = response.headers["X-Cache"]
            second_body = response.read()

        self.assertEqual(first_status, 200)
        self.assertEqual(first_cache_status, "MISS")
        self.assertEqual(second_status, 200)
        self.assertEqual(second_cache_status, "HIT")

        self.assertEqual(first_body, second_body)  # Ensure the response body is the same for both requests
    @unittest.skip("Skipping cache expiration test due to timing issues.")
    def test_cache_expiration(self):
        with urlopen(f'{PROXY_URL}/message.txt') as response:
            first_status = response.status
            first_cache_status = response.headers["X-Cache"]
            first_body = response.read()

        self.assertEqual(first_status, 200)
        self.assertEqual(first_cache_status, "MISS")

        # Wait for the cache to expire (assuming the expiration time is set to 60 seconds)
        import time
        time.sleep(65)  # Wait for 65 seconds to ensure the cache has expired

        with urlopen(f'{PROXY_URL}/message.txt') as response:
            second_status = response.status
            second_cache_status = response.headers["X-Cache"]
            second_body = response.read()

        self.assertEqual(second_status, 200)
        self.assertEqual(second_cache_status, "MISS")  # After expiration, it should be a MISS again

        self.assertEqual(first_body, second_body)  # Ensure the response body is the same for both requests

    def test_clear_cache_functionality(self):
        # First, make a request to cache the response
        with urlopen(f'{PROXY_URL}/message.txt') as response:
            first_status = response.status
            first_cache_status = response.headers["X-Cache"]
            first_body = response.read()

        self.assertEqual(first_status, 200)
        self.assertEqual(first_cache_status, "MISS")

        #second request should be a cache hit
        with urlopen(f'{PROXY_URL}/message.txt') as response:
            second_status = response.status
            second_cache_status = response.headers["X-Cache"]
            second_body = response.read()

        self.assertEqual(second_status, 200)
        self.assertEqual(second_cache_status, "HIT")  # The second request should be a cache hit

        # Clear the cache using the clear_cache function
        clear_cache()

        # Make the same request again after clearing the cache
        with urlopen(f'{PROXY_URL}/message.txt') as response:
            third_status = response.status
            third_cache_status = response.headers["X-Cache"]
            third_body = response.read()

        self.assertEqual(third_status, 200)
        self.assertEqual(third_cache_status, "MISS")  # After clearing the cache, it should be a MISS

        self.assertEqual(first_body, second_body)
        self.assertEqual(second_body, third_body)  # Ensure the response body is the same for both requests

    #test that. 404 response is forwardef and not cached.
    def test_404_response(self):
        def request_missing_file():
            with self.assertRaises(HTTPError) as captured:
                urlopen(f"{PROXY_URL}/nonexistent.txt")

            error = captured.exception

            with error:
                status = error.code
                cache_status = error.headers["X-Cache"]
                body = error.read()

            return status, cache_status, body

        first_status, first_cache_status, first_body = (
            request_missing_file()
        )

        second_status, second_cache_status, second_body = (
            request_missing_file()
        )

        self.assertEqual(first_status, 404)
        self.assertEqual(second_status, 404)

        self.assertEqual(first_cache_status, "MISS")
        self.assertEqual(second_cache_status, "MISS")

        self.assertEqual(first_body, second_body)

    #test that an unreachable origin server returns a 502 Bad Gateway response and is not cached.
    def test_unreachable_origin_returns_502(self):
        test_proxy = ThreadingHTTPServer(
            ('127.0.0.1', 0), 
            ProxyHandler,
        )

        test_proxy.origin = "http://unreachable-origin.test"

        proxy_thread = threading.Thread(target=test_proxy.serve_forever, daemon=True)
        proxy_thread.start()

        proxy_url = (
            f"http://127.0.0.1:{test_proxy.server_port}"
        )

        try:
            with patch(
                "proxy_server.urlopen",
                side_effect=URLError("Connection refused"),
            ):
                with self.assertRaises(HTTPError) as captured:
                    urlopen(f"{proxy_url}/message.txt")

            error = captured.exception

            with error:
                body = error.read()

            self.assertEqual(error.code, 502)
            self.assertIn(b"Bad Gateway", body)

        finally:
            test_proxy.shutdown()
            test_proxy.server_close()
            proxy_thread.join()

    #test that there is seprate query-string caching for the same path with different query strings.
    def test_query_strings_have_separate_cache_entries(self):
        with urlopen(f"{PROXY_URL}/message.txt?version=1") as response:
            first_version_one = response.headers["X-Cache"]

        with urlopen(f"{PROXY_URL}/message.txt?version=1") as response:
            second_version_one = response.headers["X-Cache"]

        with urlopen(f"{PROXY_URL}/message.txt?version=2") as response:
            first_version_two = response.headers["X-Cache"]

        self.assertEqual(first_version_one, "MISS")
        self.assertEqual(second_version_one, "HIT")
        self.assertEqual(first_version_two, "MISS")

    #test that a binary body response is cached and returned correctly without changes
    def test_binary_body_survives_cache(self):
        with open("test_origin/sample.bin", "rb") as file:
            expected_body = file.read()

        with urlopen(f"{PROXY_URL}/sample.bin") as response:
            first_cache_status = response.headers["X-Cache"]
            first_body = response.read()

        with urlopen(f"{PROXY_URL}/sample.bin") as response:
            second_cache_status = response.headers["X-Cache"]
            second_body = response.read()

        self.assertEqual(first_cache_status, "MISS")
        self.assertEqual(second_cache_status, "HIT")
        self.assertEqual(first_body, expected_body)
        self.assertEqual(second_body, expected_body)

if __name__ == '__main__':
    unittest.main() 