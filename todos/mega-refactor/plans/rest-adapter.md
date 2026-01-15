# rest_adapter.py

- Extract routes to `adapters/rest/routes.py`.
- Extract websocket subscription tracking to `adapters/rest/subscriptions.py`.
- Extract DTO mapping to `adapters/rest/serializers.py`.
- Keep `RESTAdapter` as server lifecycle + wiring.
