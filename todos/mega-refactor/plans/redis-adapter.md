# redis_adapter.py

- Extract Redis client setup to `redis_connection.py`.
- Extract message serialization to `redis_codec.py`.
- Extract stream polling loops to `redis_streams.py`.
- Extract peer registry/heartbeat to `redis_peers.py`.
- Extract output stream listeners to `redis_output.py`.
- Keep `RedisAdapter` as thin facade.
