from datetime import date

from swing.config import load_config


def test_config_loads_and_validates():
    cfg = load_config()
    assert cfg.swing.atr_period == 14
    assert cfg.swing.stop_atr_mult == 2.0
    assert cfg.swing.target_r_mult == 2.0
    assert cfg.swing.horizon_days == 10
    assert cfg.universe.source == "nse_fno"


def test_stt_rate_selection_by_trade_date():
    cfg = load_config()
    old = cfg.costs.stt_for(date(2025, 1, 15))
    new = cfg.costs.stt_for(date(2026, 5, 1))
    assert old.effective == date(2004, 10, 1)
    assert new.effective == date(2026, 4, 1)
