"""Characterization tests for teleclaude.adapters.qos.policy."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from teleclaude.adapters.qos.policy import QoSPolicy, discord_policy, telegram_policy, whatsapp_policy


class TestQoSPolicy:
    @pytest.mark.unit
    def test_default_mode_is_off(self):
        policy = QoSPolicy(adapter_key="test")
        assert policy.mode == "off"

    @pytest.mark.unit
    def test_default_group_mpm(self):
        policy = QoSPolicy(adapter_key="test")
        assert policy.group_mpm == 20

    @pytest.mark.unit
    def test_default_output_budget_ratio(self):
        policy = QoSPolicy(adapter_key="test")
        assert policy.output_budget_ratio == 0.8

    @pytest.mark.unit
    def test_default_reserve_mpm(self):
        policy = QoSPolicy(adapter_key="test")
        assert policy.reserve_mpm == 4

    @pytest.mark.unit
    def test_default_rounding_ms(self):
        policy = QoSPolicy(adapter_key="test")
        assert policy.rounding_ms == 100

    @pytest.mark.unit
    def test_adapter_key_stored(self):
        policy = QoSPolicy(adapter_key="telegram")
        assert policy.adapter_key == "telegram"

    @pytest.mark.unit
    def test_custom_values_override_defaults(self):
        policy = QoSPolicy(adapter_key="x", mode="strict", group_mpm=60, rounding_ms=200)
        assert policy.mode == "strict"
        assert policy.group_mpm == 60
        assert policy.rounding_ms == 200


class TestTelegramPolicy:
    @pytest.mark.unit
    def test_enabled_cfg_produces_strict_mode(self):
        cfg = MagicMock()
        cfg.enabled = True
        cfg.group_mpm = 30
        cfg.output_budget_ratio = 0.7
        cfg.reserve_mpm = 5
        cfg.min_session_tick_s = 2.0
        cfg.active_emitter_window_s = 15.0
        cfg.active_emitter_ema_alpha = 0.3
        cfg.rounding_ms = 200
        policy = telegram_policy(cfg)
        assert policy.mode == "strict"
        assert policy.adapter_key == "telegram"

    @pytest.mark.unit
    def test_disabled_cfg_produces_off_mode(self):
        cfg = MagicMock()
        cfg.enabled = False
        cfg.group_mpm = 20
        cfg.output_budget_ratio = 0.8
        cfg.reserve_mpm = 4
        cfg.min_session_tick_s = 3.0
        cfg.active_emitter_window_s = 10.0
        cfg.active_emitter_ema_alpha = 0.2
        cfg.rounding_ms = 100
        policy = telegram_policy(cfg)
        assert policy.mode == "off"

    @pytest.mark.unit
    def test_group_mpm_from_config(self):
        cfg = MagicMock()
        cfg.enabled = True
        cfg.group_mpm = 45
        cfg.output_budget_ratio = 0.8
        cfg.reserve_mpm = 4
        cfg.min_session_tick_s = 3.0
        cfg.active_emitter_window_s = 10.0
        cfg.active_emitter_ema_alpha = 0.2
        cfg.rounding_ms = 100
        policy = telegram_policy(cfg)
        assert policy.group_mpm == 45


class TestDiscordPolicy:
    @pytest.mark.unit
    def test_uses_cfg_mode(self):
        cfg = MagicMock()
        cfg.mode = "coalesce_only"
        policy = discord_policy(cfg)
        assert policy.mode == "coalesce_only"
        assert policy.adapter_key == "discord"

    @pytest.mark.unit
    def test_permissive_group_mpm(self):
        cfg = MagicMock()
        cfg.mode = "off"
        policy = discord_policy(cfg)
        assert policy.group_mpm == 50

    @pytest.mark.unit
    def test_high_output_budget_ratio(self):
        cfg = MagicMock()
        cfg.mode = "off"
        policy = discord_policy(cfg)
        assert policy.output_budget_ratio == 0.9


class TestWhatsAppPolicy:
    @pytest.mark.unit
    def test_uses_cfg_mode(self):
        cfg = MagicMock()
        cfg.mode = "off"
        policy = whatsapp_policy(cfg)
        assert policy.mode == "off"
        assert policy.adapter_key == "whatsapp"

    @pytest.mark.unit
    def test_default_group_mpm(self):
        cfg = MagicMock()
        cfg.mode = "off"
        policy = whatsapp_policy(cfg)
        assert policy.group_mpm == 20

    @pytest.mark.unit
    def test_placeholder_min_session_tick(self):
        cfg = MagicMock()
        cfg.mode = "off"
        policy = whatsapp_policy(cfg)
        assert policy.min_session_tick_s == 3.0
