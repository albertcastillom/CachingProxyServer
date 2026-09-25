# Caching Proxy Server

A small Redis-backed HTTP caching proxy written in Python. The project forwards
GET requests to an origin server, stores successful responses in Redis, and
serves repeated requests from the cache until their time-to-live (TTL) expires.

This project was built as a learning exercise based on the roadmap.sh caching
proxy project.

## How it works

```text
Client
  |
  v
Caching proxy (localhost:8080)
  |                         |
  | cache miss              | cache hit
  v                         v
Origin server             Redis
```

For each GET request, the proxy:

1. Builds a cache key from the origin, HTTP method, path, and query string.
2. Checks Redis for a cached response.
3. Returns the cached status, headers, and body when the key exists.
4. Otherwise forwards the request to the origin server.
5. Stores successful `200 OK` responses in Redis with a configurable TTL.

Responses include one of these headers:

```http
X-Cache: MISS
X-Cache: HIT
```

## Requirements

- Python 3.10 or newer
- Redis running on `localhost:6379`

The project uses Python's standard-library HTTP server and the `redis` Python
package.

## Installation

Create and activate a virtual environment:

```bash
python3 -m venv env
source env/bin/activate
```

Install the project in editable mode:

```bash
python -m pip install -e .
```

This installs the Python dependency declared in `pyproject.toml` and creates the
`caching-proxy` command inside the active virtual environment.

Verify the command:

```bash
caching-proxy --help
```

## Starting Redis

For local development, Redis can run in the foreground without persistence:

```bash
redis-server \
  --bind 127.0.0.1 \
  --port 6379 \
  --save "" \
  --appendonly no
```

In another terminal, verify the connection:

```bash
redis-cli ping
```

Redis should respond with:

```text
PONG
```

## Running the proxy

Start the proxy by providing a listening port and origin URL:

```bash
caching-proxy \
  --port 8080 \
  --origin http://localhost:8001 \
  --ttl 60
```

The available arguments are:

| Argument        | Default                 | Description                              |
| --------------- | ----------------------- | ---------------------------------------- |
| `--port`        | `8080`                  | Port on which the proxy listens          |
| `--origin`      | `http://localhost:8001` | Server to which requests are forwarded   |
| `--ttl`         | `60`                    | Cache lifetime in seconds                |
| `--clear-cache` | disabled                | Clear the proxy's Redis entries and exit |

You can also run the module without installing the CLI command:

```bash
python proxy_server.py --port 8080 --origin http://localhost:8001 --ttl 60
```

## Local example

The repository contains a small `test_origin` directory. Serve it on port 8001:

```bash
python3 -m http.server 8001 --directory test_origin
```

With Redis and the proxy running, make the same request twice:

```bash
curl -i http://localhost:8080/message.txt
curl -i http://localhost:8080/message.txt
```

The first response should contain:

```http
X-Cache: MISS
```

The second should contain:

```http
X-Cache: HIT
```

Requests with different query strings use different cache entries. For example,
these URLs are cached separately:

```text
/message.txt?version=1
/message.txt?version=2
```

## Clearing the cache

From another terminal, run:

```bash
caching-proxy --clear-cache
```

Only Redis keys beginning with `caching-proxy:` are removed. Other keys in the
same Redis database are left untouched.

You can inspect the proxy's keys manually:

```bash
redis-cli SCAN 0 MATCH "caching-proxy:*"
```

## Running the tests

The current integration tests expect the following services:

1. Redis on `localhost:6379`.
2. The test origin on `localhost:8001`.
3. The proxy on `localhost:8080`.

For a fast expiration test, remove its temporary `@unittest.skip` decorator and
start the proxy with a one-second TTL:

```bash
caching-proxy \
  --port 8080 \
  --origin http://localhost:8001 \
  --ttl 1
```

Run the test suite from the repository root:

```bash
python -m unittest discover -s tests -v
```

The suite covers:

- Cache misses followed by cache hits
- Cache expiration
- Cache clearing
- Forwarded 404 responses
- Unreachable origins and 502 responses
- Separate query-string cache entries
- Binary response bodies

## Error behavior

- Origin HTTP errors such as `404 Not Found` are forwarded to the client and
  are not cached.
- An unreachable origin produces `502 Bad Gateway`.
- If Redis cannot be read or written, the proxy logs the cache error and still
  attempts to return the origin response.

## Current limitations

- Only GET requests are implemented.
- Only `200 OK` responses are cached.
- Redis connection settings are currently fixed to `localhost:6379`, database 0.
- Responses are loaded fully into memory before being returned.
- Advanced HTTP caching directives such as `Cache-Control`, `Vary`, and
  conditional requests are not yet implemented.
- Python's `http.server` is intended for learning and development, not
  production deployment.

## Project structure

```text
.
├── proxy_server.py          # CLI, proxy handler, and Redis cache logic
├── pyproject.toml           # Package metadata, dependencies, and CLI entry point
├── tests/
│   └── test_proxy_server.py # Integration tests
└── test_origin/             # Files served by the local test origin
```
