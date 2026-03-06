# Demo: clickable-sprites

## Validation

```bash
# 1. Verify sprite validation catches errors
python -c "
from teleclaude.cli.tui.animations.sprites import get_sky_entities
sprites = get_sky_entities()
print(f'Loaded {len(sprites)} sky entities')
assert len(sprites) > 0, 'No sprites loaded'
for s in sprites:
    url = getattr(s, 'source_url', None)
    print(f'  {type(s).__name__}: source_url={url}')
    assert url is not None, f'Missing source_url on {type(s).__name__}'
"
```

```bash
# 2. Verify source_url field exists on dataclasses
python -c "
from teleclaude.cli.tui.animations.sprites.composite import CompositeSprite, AnimatedSprite, SpriteLayer
s = CompositeSprite(layers=[SpriteLayer()], source_url='https://example.com')
print(f'CompositeSprite.source_url = {s.source_url}')
assert s.source_url == 'https://example.com'
a = AnimatedSprite(frames=[[' ']], source_url='https://example.com')
print(f'AnimatedSprite.source_url = {a.source_url}')
assert a.source_url == 'https://example.com'
print('source_url field works on both types')
"
```

```bash
# 3. Verify TUI starts without daemon (animation system works standalone)
# This tests that the import chain and sprite loading don't crash
python -c "
from teleclaude.cli.tui.animation_engine import AnimationEngine
engine = AnimationEngine()
print('AnimationEngine created successfully without daemon')
"
```

## Guided Presentation

### Step 1: Sprite Validation
Run `telec` with all sprites valid. Observe: TUI starts, Banner shows animated
sky with clouds, birds, possibly a UFO. No error messages.

Now introduce a malformed sprite (e.g., a SpriteGroup with weights that don't
sum to 1.0). Run `telec` again. Observe: stderr shows a clear error message
naming the broken sprite file and the specific validation error. The TUI still
starts with the remaining valid sprites.

### Step 2: Clickable Attribution
With the TUI running, observe a sprite crossing the Banner area (cloud, bird,
or UFO). Click on it. Observe: the default browser opens to the sprite's GitHub
source page.

### Step 3: Contributor Flow
Open the CONTRIBUTING.md in the sprites directory. Follow the instructions to
create a minimal sprite. Add it to `__init__.py`. Run `telec`. Observe: the new
sprite appears in the sky. If it has errors, they're shown clearly on startup.
