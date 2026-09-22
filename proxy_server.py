from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
#import requests for forwarding requests to the origin server
from urllib.request import urlopen
from urllib.error import HTTPError, URLError


ORIGIN = 'http://localhost:8001'  #origin server URL from test_origin 
CACHE = {}  #cache to store responses from the origin server
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

    #send response function to send response back to the client
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
        target_url = ORIGIN + incoming_path

        cache_key = incoming_path
        if cache_key in CACHE:
            print(f'X-Cache: Hit for {cache_key}')
            cached_response = CACHE[cache_key]
            self.send_proxy_response(
                cached_response['status'],
                cached_response['headers'],
                cached_response['body'],
                "HIT"
            )
            return

        try:
            origin_response = urlopen(target_url)

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
                CACHE[cache_key] = {
                    'status': status,
                    'headers': headers,
                    'body': body
                }

        print (f'X-Cache: Miss for {cache_key}')

        self.send_proxy_response(status, headers, body, "MISS")

        

server = ThreadingHTTPServer(('localhost', 8080), ProxyHandler)
print('Starting proxy server on http://localhost:8080')
try:
    server.serve_forever()
except KeyboardInterrupt:
    print('Shutting down proxy server...')
    server.server_close()
