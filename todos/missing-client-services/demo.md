# Demo: missing-client-services

## Validation

```bash
# Verify all new service modules exist
test -f teleclaude/services/discord.py && echo "discord service: OK" || echo "MISSING"
test -f teleclaude/services/whatsapp.py && echo "whatsapp service: OK" || echo "MISSING"
```

```bash
# Verify all new delivery adapters exist
test -f teleclaude_events/delivery/discord.py && echo "discord delivery: OK" || echo "MISSING"
test -f teleclaude_events/delivery/whatsapp.py && echo "whatsapp delivery: OK" || echo "MISSING"
```

```bash
# Verify exports include new adapters
python -c "from teleclaude_events.delivery import DiscordDeliveryAdapter, WhatsAppDeliveryAdapter; print('exports: OK')"
```

```bash
# Verify service functions are importable with correct signatures
python -c "
from teleclaude.services.discord import send_discord_dm
from teleclaude.services.whatsapp import send_whatsapp_message
import inspect
sig_d = inspect.signature(send_discord_dm)
sig_w = inspect.signature(send_whatsapp_message)
assert 'user_id' in sig_d.parameters, 'missing user_id param'
assert 'phone_number' in sig_w.parameters, 'missing phone_number param'
print('service signatures: OK')
"
```

```bash
# Run the unit tests for all new modules
python -m pytest tests/unit/test_discord_service.py tests/unit/test_whatsapp_service.py tests/unit/test_teleclaude_events/test_discord_adapter.py tests/unit/test_teleclaude_events/test_whatsapp_adapter.py -v
```

## Guided Presentation

### Step 1: Service layer parity

Show `teleclaude/services/` directory listing. Before this change there were two services
(telegram.py, email.py). Now there are four (+ discord.py, whatsapp.py). Each service is
a standalone httpx-based helper with no imports from core or adapters.

### Step 2: Delivery adapter parity

Show `teleclaude_events/delivery/` directory listing. Before this change there was only
TelegramDeliveryAdapter. Now Discord and WhatsApp delivery adapters exist with the
identical callback interface.

### Step 3: Daemon wiring

Show the daemon's `_start_event_processing` push_callbacks section. All three platform
delivery adapters are registered for admin people who have the corresponding credentials
configured. The pattern is consistent across all three.

### Step 4: Test coverage

Run the test suite. All new modules have unit tests covering success, error, threshold
filtering, and graceful exception handling paths.
