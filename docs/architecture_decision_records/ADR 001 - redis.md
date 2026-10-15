# ADR 001: Redis over RabbitMQ

## Context

The API receives alerts via webhook and should not process them itself. I need a queue between the API and the worker for this.

## Decision

I will use Redis (Streams with consumer groups).

## Rationale

- I have only one message type and one worker, so I do not need routing.
- Redis is simple to set up. It only needs one deployment and one service.
- I can also use Redis later for deduplication or rate limiting.

## Trade-offs

- RabbitMQ has built-in dead-letter queues and retries. With Redis I have to implement these in the worker myself.
- RabbitMQ provides stronger delivery guarantees. Redis requires AOF, and about one second of data could still be lost in a failure. On the other hand, the application is not affected if some alerts go unprocessed.
- RabbitMQ involves a few more concepts (exchanges and bindings) and uses more memory when idle. However, operating it with the Cluster Operator would not be much more complex.

## Implementation

- Redis runs without persistence. A small amount of data loss is acceptable and will be tolerated without extra handling
- The worker acknowledges a message only after it has been stored in Postgres.
- The worker reads stuck messages from the pending list. It discards and logs malformed messages and retries the others.
- KEDA reads Redis consumer-group lag and scales the Worker deployment. The Redis exporter sidecar independently reports unread lag, pending entries, and oldest outstanding message age to Prometheus through the `redis-metrics` Service.
- Redis client traffic and Prometheus scraping use separate Services so the metrics endpoint is distinct from the Redis client endpoint.

## When to Revisit This Decision

If I have multiple message types with different consumers, or if the retry logic in the worker becomes too complex.