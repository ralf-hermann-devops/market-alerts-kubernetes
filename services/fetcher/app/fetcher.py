# services/fetcher/main.py
import datetime
import os
from decimal import Decimal

import psycopg
import yfinance as yf

SYMBOLS = os.environ["SYMBOLS"].split(",")          # from ConfigMap


def fetch_candles(symbol: str) -> list[tuple[datetime.datetime, Decimal, Decimal, Decimal, Decimal, int]]:
    history = yf.Ticker(symbol).history(
        period="1d",
        interval="1m",
        auto_adjust=False,
    )
    if history.empty:
        raise ValueError(f"No candle data returned for {symbol!r}")

    return [
        (
            datetime.datetime.fromisoformat(str(timestamp)),
            Decimal(str(row["Open"])),
            Decimal(str(row["High"])),
            Decimal(str(row["Low"])),
            Decimal(str(row["Close"])),
            int(row["Volume"]),
        )
        for timestamp, row in history.iterrows()
    ]


def main():
    with psycopg.connect(
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        host=os.environ["POSTGRES_HOST"],
        port=os.environ["POSTGRES_PORT"],
    ) as db:
        for s in SYMBOLS:
            for c in fetch_candles(s):
                db.execute(
                    "INSERT INTO candles (symbol, ts, o, h, l, c, v) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                    "ON CONFLICT (symbol, ts) DO UPDATE SET c=EXCLUDED.c, v=EXCLUDED.v", (s, *c))
    print("done")

if __name__ == "__main__":
    main()