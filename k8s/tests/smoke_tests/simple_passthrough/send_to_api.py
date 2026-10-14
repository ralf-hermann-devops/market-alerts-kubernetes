import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen


request_count = int(os.environ["REQUEST_COUNT"])
if request_count < 1:
    raise ValueError("REQUEST_COUNT must be at least 1")

payload = json.dumps(
    {
        "secret": os.environ["WEBHOOK_SECRET"],
        "symbol": "AAPL",
        "action": "long",
        "price": 123.45,
        "timeframe": "1h",
    }
).encode()

for request_number in range(1, request_count + 1):
    request = Request(
        "http://api:8000/webhook/tradingview",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            print(
                f"Request {request_number}/{request_count}: "
                f"HTTP {response.status} {response.reason}"
            )
            print(response.read().decode())
    except HTTPError as error:
        print(
            f"Request {request_number}/{request_count}: "
            f"HTTP {error.code} {error.reason}"
        )
        print(error.read().decode())
        sys.exit(1)
