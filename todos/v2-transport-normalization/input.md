# V2 Transport Normalization (REST/Redis as transport only)

Goal: normalize external inputs (REST, Redis/MCP, Telegram) into internal command models without introducing the command outbox yet. Remove the notion of REST/Redis as “adapters” and treat them as transports only. Reduce metadata/payload sprawl and route all external requests through a single internal command shape and dispatcher.
