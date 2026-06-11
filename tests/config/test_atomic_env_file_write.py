from __future__ import annotations

import pytest

from teleclaude.cli.config_handlers import set_env_var

VAL_1_LINE = "TEST_VAR=value1\n"
VAL_2_LINE = "TEST_VAR=value2\n"
EXPORT_NEW_LINE = "export EXPORTED_VAR=new\n"


@pytest.mark.spec("project/spec/feature/config/atomic-env-file-write", "UC-AEFW-1")
@pytest.mark.spec("project/spec/feature/config/atomic-env-file-write", "UC-AEFW-2")
def test_set_env_var_success(tmp_path):
    env_file = tmp_path / ".env"

    # 1. Set new var
    set_env_var("TEST_VAR", "value1", env_path=env_file)
    assert env_file.exists()
    content = env_file.read_text(encoding="utf-8")
    assert VAL_1_LINE in content

    # 2. Update existing var
    set_env_var("TEST_VAR", "value2", env_path=env_file)
    content = env_file.read_text(encoding="utf-8")
    assert VAL_2_LINE in content
    assert "TEST_VAR=value1" not in content

    # 3. Update export style var
    env_file.write_text("export EXPORTED_VAR=old\n", encoding="utf-8")
    set_env_var("EXPORTED_VAR", "new", env_path=env_file)
    content = env_file.read_text(encoding="utf-8")
    assert EXPORT_NEW_LINE in content
    assert "old" not in content


@pytest.mark.spec("project/spec/feature/config/atomic-env-file-write", "UC-AEFW-3")
def test_set_env_var_validation(tmp_path):
    env_file = tmp_path / ".env"

    # Name validation
    with pytest.raises(ValueError, match="Invalid env var name"):
        set_env_var("", "value", env_path=env_file)
    with pytest.raises(ValueError, match="Invalid env var name"):
        set_env_var("VAR=1", "value", env_path=env_file)
    with pytest.raises(ValueError, match="Invalid env var name"):
        set_env_var("VAR\nNAME", "value", env_path=env_file)

    # Value validation
    with pytest.raises(ValueError, match="Env var value cannot contain newlines"):
        set_env_var("VAR", "val\nue", env_path=env_file)


@pytest.mark.spec("project/spec/feature/config/atomic-env-file-write", "UC-AEFW-4")
def test_set_env_var_failure(tmp_path):
    # Setup parent file to trigger mkdir failure
    parent_file = tmp_path / "parent_file"
    parent_file.write_text("not a dir", encoding="utf-8")
    env_file = parent_file / ".env"

    with pytest.raises(OSError):
        set_env_var("VAR", "value", env_path=env_file)

    # Verify no leaked files
    assert not env_file.exists()
    assert not env_file.with_suffix(".tmp").exists()
    assert not env_file.with_suffix(".lock").exists()
