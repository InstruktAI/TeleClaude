# proficiency-to-expertise-cli — Input

## Summary

Update CLI commands for people management to support the new expertise structure instead of flat proficiency.

## CLI Changes

### Add person (`config_cli.py`, line 196-224)

Replace `--proficiency` with expertise flags. Support:
- `--expertise '{...}'` as JSON blob for full expertise structure
- Or domain-level flags: `--expertise-teleclaude novice --expertise-software-development '{"default": "expert", "frontend": "intermediate"}'`

### Edit person (`config_cli.py`, line 290-349)

Support editing individual domain/sub-area levels:
- Dot-path: `telec config people edit "Maurice" --expertise software-development.frontend=intermediate`
- Or full replace: `telec config people edit "Maurice" --expertise '{...}'`

### List people (`config_cli.py`, line 153-179)

Serialize full expertise structure in JSON output (line 163).

### PersonInfo dataclass (`config_cli.py`, line 79-90)

`proficiency: str | None` -> restructure for nested expertise data in JSON output.

## Touchpoints

| Component | File | Lines | Change needed |
|-----------|------|-------|--------------|
| CLI add | `config_cli.py` | 196-224 | New expertise flags |
| CLI edit | `config_cli.py` | 290-349 | Dot-path expertise editing |
| CLI list | `config_cli.py` | 153-179 | Serialize expertise in output |
| PersonInfo | `config_cli.py` | 79-90 | Restructure dataclass |
| CLI tests | `test_config_cli.py` | 357-411 | New flag tests |

## Dependency

Requires `proficiency-to-expertise-schema` (the Pydantic model) to be complete first.
