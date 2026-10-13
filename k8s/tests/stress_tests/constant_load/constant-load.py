import json
import math
import os
import sys
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


request_interval_seconds = int(os.environ["REQUEST_INTERVAL_MS"]) / 1000
duration_seconds = float(os.environ["DURATION_SECONDS"])
if not math.isfinite(request_interval_seconds) or request_interval_seconds <= 0:
    raise ValueError("REQUEST_INTERVAL_MS must be a positive integer")
if not math.isfinite(duration_seconds) or duration_seconds <= 0:
    raise ValueError("DURATION_SECONDS must be a positive number")

payload = json.dumps(
    {
        "secret": os.environ["WEBHOOK_SECRET"],
        "symbol": "AAPL",
        "action": "long",
        "price": 123.45,
        "timeframe": "1h",
    }
).encode()

start_time = time.monotonic()
end_time = start_time + duration_seconds
next_request_time = start_time
request_count = 0

print(
    f"Sending requests approx. every {request_interval_seconds * 1000:g} ms "
    f"for {duration_seconds:g} seconds",
    flush=True,
)


while next_request_time < end_time:
    delay = next_request_time - time.monotonic()
    if delay > 0:
        time.sleep(delay)
    if time.monotonic() >= end_time:
        break

    request_count += 1
    request = Request(
        "http://api:8000/webhook/tradingview",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            time_passed = time.monotonic() - start_time
            print(f"{time_passed:.2f}s of {duration_seconds:.2f}s passed - "
                  f"Request {request_count}: HTTP {response.status} "
                  f"{response.reason}")
            response.read()
    except HTTPError as error:
        print(
            f"Request {request_count}: HTTP {error.code} {error.reason}",
            file=sys.stderr,
        )
        print(error.read().decode(), file=sys.stderr)
        sys.exit(1)

    next_request_time += request_interval_seconds
    now = time.monotonic()
    if next_request_time < now:
        missed_intervals = math.floor(
            (now - next_request_time) / request_interval_seconds
        ) + 1
        next_request_time += missed_intervals * request_interval_seconds


elapsed_seconds = time.monotonic() - start_time
print(
    f"Sent {request_count} requests in {elapsed_seconds:.2f} seconds "
    f"(target interval {request_interval_seconds * 1000:g} ms).",
    flush=True,
)
