CREATE TABLE alerts (
  id         BIGSERIAL PRIMARY KEY,
  stream_id  TEXT UNIQUE NOT NULL,
  symbol     TEXT NOT NULL,
  action     TEXT NOT NULL,
  price      NUMERIC,
  timeframe  TEXT,
  received_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE candles (
  symbol TEXT, ts TIMESTAMPTZ, o NUMERIC, h NUMERIC, l NUMERIC, c NUMERIC, v BIGINT,
  PRIMARY KEY (symbol, ts)
);
