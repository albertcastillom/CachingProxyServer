from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
#import requests for forwarding requests to the origin server
from urllib.request import urlopen
from urllib.error import HTTPError, URLError
import redis
import json
import argparse

#redis client to connect to the Redis server
redis_client = redis.Redis(
    host='localhost',
    port=6379,
    db=0,
    decode_responses=False 
)#keeping decoding as bytes to avoid issues with binary data in responses and feeds straight into self.wfile.write()

def parse_arguments():
    parser = argparse.ArgumentParser(description='Caching Proxy Server')
    parser.add_argument('--origin', type=str, default='http://localhost:8001', help='Origin server URL')
    parser.add_argument('--port', type=int, default=8080, help='Port to run the proxy server on')
    parser.add_argument('--clear-cache', action='store_true', help='Clear all cached responses in Redis and exit')
    return parser.parse_args()


#clear cache function to clear all cached responses in Redis
def clear_cache():
    keys = list(redis_client.scan_iter(match='caching-proxy:*'))
    if not keys:
        print('No cached responses found in Redis.')
        return
    deleted_count = redis_client.delete(*keys)
    print(f'Cleared {deleted_count} cached responses from Redis.')

#skip origin server headers that are not relevant to the client
SKIPPED_RESPONSE_HEADERS = {
    "server",
    "date",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
     "upgrade",
    "content-length",
}      

#Proxy Handler class to handle incoming requests and forward them to the origin server
#inherits from baseHTTPRequestHandler to handle HTTP requests
#do_GET method to handle GET requests and forward them to the origin server
#do_* methods can be implemented for other HTTP methods like POST, PUT, DELETE, etc.
class ProxyHandler(BaseHTTPRequestHandler):

    #send response back to the client function
    def send_proxy_response(self, status, headers, body, cache_status):
        self.send_response(status)
        
        for header_name, header_value in headers:
            print(f"{header_name} = {header_value}")
            if header_name.lower() in SKIPPED_RESPONSE_HEADERS:
                continue
            self.send_header(header_name, header_value)

        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Cache", cache_status)        
        self.end_headers() 
        self.wfile.write(body)

    #handle get requests here
    def do_GET(self):
        #get target URL from the incoming request and forward it to the origin server
        incoming_path = self.path
        target_url = self.server.origin + incoming_path
        cache_key = f"caching-proxy:{self.server.origin}:GET:{incoming_path}"

        cached_response = redis_client.hgetall(cache_key)
        if cached_response:
            print(f'X-Cache: Hit for {cache_key}')
            self.send_proxy_response(
                int(cached_response[b'status']),
                json.loads(cached_response[b'headers'].decode()),
                cached_response[b'body'],
                "HIT"
            )
            return

        try:
            origin_response = urlopen(target_url, timeout=10)

        except HTTPError as e:
            print(f'HTTPError: {e.code} - {e.reason}!!!')
            origin_response = e

        except URLError as e:
            print(f'URLError: {e.reason}!!!')
            self.send_error(502, f'Bad Gateway: {e.reason}')
            return

        except Exception as e:
            print(f'Unexpected error: {e}!!!')
            self.send_error(500, f'Internal Server Error: {e}')
            return

        print(f'Forwarding request to origin server: {target_url}')

        # A successful response and an HTTPError are both file-like response
        # objects. Using one context manager ensures either one is closed.
        with origin_response:
            status = origin_response.status
            headers = list(origin_response.headers.items())
            body = origin_response.read()

            if status == 200:
                print(f'Caching response for {cache_key}')

                redis_client.hset(
                    cache_key,
                    mapping={
                        'status': str(status),
                        'headers': json.dumps(headers),
                        'body': body,
                    },
                )
                redis_client.expire(cache_key, 60)  # Set expiration time to 60 seconds

        print (f'X-Cache: Miss for {cache_key}')
        self.send_proxy_response(status, headers, body, "MISS")

def main():
    arguments = parse_arguments()

    if arguments.clear_cache:
        try:
            clear_cache()
        finally:
            redis_client.close()

        return

    server = ThreadingHTTPServer(('localhost', arguments.port), ProxyHandler)

    #normalize the origin URL to ensure it doesn't end with a slash
    server.origin = arguments.origin.rstrip('/')

    print(f'Starting proxy server on http://localhost:{arguments.port}...')

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('Shutting down proxy server...')
    finally:
        redis_client.close()
        server.server_close()

if __name__ == '__main__':
    main()

