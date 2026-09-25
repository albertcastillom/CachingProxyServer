from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
#import requests for forwarding requests to the origin server
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
import redis
import json
import argparse
import logging


logger = logging.getLogger(__name__)

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
    parser.add_argument('--ttl', type=int, default=60, help='Time-to-live (TTL) for cached responses in seconds')
    parser.add_argument(
        '--log-level',
        choices=('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'),
        default='INFO',
        help='Logging level (default: INFO)',
    )
    return parser.parse_args()


#clear cache function to clear all cached responses in Redis
def clear_cache():
    try:
        keys = list(redis_client.scan_iter(match='caching-proxy:*'))
        if not keys:
            logger.info('No cached responses found in Redis.')
            return
        deleted_count = redis_client.delete(*keys)
        logger.info('Cleared %s cached responses from Redis.', deleted_count)
    except redis.RedisError as e:
        logger.error('Error clearing cache in Redis: %s', e)

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

SKIPPED_REQUEST_HEADERS = SKIPPED_RESPONSE_HEADERS | {
    "host",
    "expect",
}

#Proxy Handler class to handle incoming requests and forward them to the origin server
#inherits from baseHTTPRequestHandler to handle HTTP requests
#do_GET method to handle GET requests and forward them to the origin server
#do_* methods can be implemented for other HTTP methods like POST, PUT, DELETE, etc.
class ProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, message_format, *args):
        message = message_format % args
        message = message.replace('\r', '\\r').replace('\n', '\\n')
        logger.info('%s - %s', self.address_string(), message)

    #send response back to the client function
    def send_proxy_response(self, status, headers, body, cache_status):
        self.send_response(status)
        
        for header_name, header_value in headers:
            logger.debug('Forwarding response header %s=%s', header_name, header_value)
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
        cache_status = "MISS"

        try:
            cached_response = redis_client.hgetall(cache_key)
            if cached_response:
                logger.info('Cache hit for %s', cache_key)
                self.send_proxy_response(
                    int(cached_response[b'status']),
                    json.loads(cached_response[b'headers'].decode()),
                    cached_response[b'body'],
                    "HIT"
                )
                return
        except redis.RedisError as e:
            cache_status = "BYPASS"
            logger.warning('Unable to read Redis cache; bypassing it: %s', e)
            # Continue to fetch from origin server if cache access fails

        try:
            origin_response = urlopen(target_url, timeout=10)

        except HTTPError as e:
            logger.info('Origin returned HTTP %s: %s', e.code, e.reason)
            origin_response = e

        except URLError as e:
            logger.error('Unable to reach origin %s: %s', target_url, e.reason)
            self.send_error(502, 'Bad Gateway')
            return

        except Exception:
            logger.exception('Unexpected error while contacting %s', target_url)
            self.send_error(500, 'Internal Server Error')
            return

        logger.info('Forwarding GET request to %s', target_url)

        # A successful response and an HTTPError are both file-like response
        # objects. Using one context manager ensures either one is closed.
        with origin_response:
            status = origin_response.status
            headers = list(origin_response.headers.items())
            body = origin_response.read()

            if status == 200 and cache_status != "BYPASS":
                logger.debug('Caching response for %s', cache_key)

                try:
                    with redis_client.pipeline(transaction=True) as pipe:
                        pipe.hset(
                            cache_key,
                            mapping={
                                'status': str(status),
                                'headers': json.dumps(headers),
                                'body': body,
                            },
                        )
                        pipe.expire(cache_key, self.server.cache_ttl)
                        pipe.execute()
                        logger.info('Cached response for %s', cache_key)
                except redis.RedisError as e:
                    cache_status = "BYPASS"
                    logger.warning('Unable to cache response in Redis: %s', e)

        logger.info('Cache %s for %s', cache_status.lower(), cache_key)
        self.send_proxy_response(status, headers, body, cache_status)

    def forward_mutating_request(self):
        incoming_path = self.path
        target_url = self.server.origin + incoming_path

        content_length = self.headers.get('Content-Length')
        if content_length is None:
            request_body = None
        else:
            try:
                body_length = int(content_length)
                if body_length < 0:
                    raise ValueError
            except ValueError:
                logger.warning('Invalid Content-Length received: %r', content_length)
                self.send_error(400, 'Invalid Content-Length')
                return

            request_body = self.rfile.read(body_length)

        request_headers = {
            header_name: header_value
            for header_name, header_value in self.headers.items()
            if header_name.lower() not in SKIPPED_REQUEST_HEADERS
        }

        origin_request = Request(
            target_url,
            data=request_body,
            headers=request_headers,
            method=self.command,
        )

        try:
            origin_response = urlopen(origin_request, timeout=10)
        except HTTPError as e:
            logger.info('Origin returned HTTP %s: %s', e.code, e.reason)
            origin_response = e
        except URLError as e:
            logger.error('Unable to reach origin %s: %s', target_url, e.reason)
            self.send_error(502, 'Bad Gateway')
            return
        except Exception:
            logger.exception(
                'Unexpected error while forwarding %s to %s',
                self.command,
                target_url,
            )
            self.send_error(500, 'Internal Server Error')
            return

        logger.info('Forwarding %s request to %s', self.command, target_url)

        with origin_response:
            status = origin_response.status
            headers = list(origin_response.headers.items())
            body = origin_response.read()

        if 200 <= status < 300:
            get_cache_key = (
                f"caching-proxy:{self.server.origin}:GET:{incoming_path}"
            )
            try:
                deleted_count = redis_client.delete(get_cache_key)
                if deleted_count:
                    logger.info('Invalidated cached GET response %s', get_cache_key)
            except redis.RedisError as e:
                logger.warning('Unable to invalidate Redis cache: %s', e)

        self.send_proxy_response(status, headers, body, 'BYPASS')

    def do_POST(self):
        self.forward_mutating_request()

    def do_PUT(self):
        self.forward_mutating_request()

    def do_DELETE(self):
        self.forward_mutating_request()

def main():
    arguments = parse_arguments()

    logging.basicConfig(
        level=getattr(logging, arguments.log_level),
        format='%(asctime)s %(levelname)s %(threadName)s %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
    )

    if arguments.clear_cache:
        try:
            clear_cache()
        finally:
            redis_client.close()

        return

    server = ThreadingHTTPServer(('localhost', arguments.port), ProxyHandler)

    #normalize the origin URL to ensure it doesn't end with a slash
    server.origin = arguments.origin.rstrip('/')
    server.cache_ttl = arguments.ttl

    logger.info(
        'Starting proxy server on http://localhost:%s; origin=%s; ttl=%ss',
        arguments.port,
        server.origin,
        server.cache_ttl,
    )

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info('Shutting down proxy server...')
    finally:
        redis_client.close()
        server.server_close()

if __name__ == '__main__':
    main()
