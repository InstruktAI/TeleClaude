# Demo: chartest-tui-animations

## Validation

```bash
make test-unit 2>&1 | tail -5
```

```bash
make lint 2>&1 | tail -3
```

## Guided Presentation

Run the characterization test suite for the TUI animation modules:

```bash
.venv/bin/pytest tests/unit/cli/tui/ -v --tb=short 2>&1 | tail -30
```

The tests cover 16 animation source files with 1:1 mapping:

- `animation_colors.py` → `test_animation_colors.py`
- `animation_engine.py` → `test_animation_engine.py`
- `animation_triggers.py` → `test_animation_triggers.py`
- `animations/base.py` → `animations/test_base.py`
- `animations/config.py` → `animations/test_config.py`
- `animations/agent.py` → `animations/test_agent.py`
- `animations/creative.py` → `animations/test_creative.py`
- `animations/general.py` → `animations/test_general.py`
- `animations/particles.py` → `animations/test_particles.py`
- `animations/sky.py` → `animations/test_sky.py`
- `animations/sprites/composite.py` → `animations/sprites/test_composite.py`
- `animations/sprites/birds.py` → `animations/sprites/test_birds.py`
- `animations/sprites/cars.py` → `animations/sprites/test_cars.py`
- `animations/sprites/celestial.py` → `animations/sprites/test_celestial.py`
- `animations/sprites/clouds.py` → `animations/sprites/test_clouds.py`
- `animations/sprites/ufo.py` → `animations/sprites/test_ufo.py`
