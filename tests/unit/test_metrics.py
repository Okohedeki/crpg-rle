"""Per-episode learning-metric contract (TyrannyAdapter.episode_metrics).

The metric name order must match the C Log field order in
puffer_fork/ocean/tyranny/{tyranny.h,binding.c}; this test locks the contract.
"""
from crpg_rle.adapters.tyranny.adapter import TyrannyAdapter
from crpg_rle.core.modes import Mode


def _adapter():
    a = TyrannyAdapter()
    a.reset(seed=0)
    return a


def test_log_metric_names_stable_order():
    a = _adapter()
    assert a.log_metric_names() == [
        "r_milestone", "r_faction_favor", "milestones_reached",
        "term_success", "term_failure", "term_timer",
        "frac_combat", "frac_dialogue", "frac_overworld", "frac_levelup",
    ]
    # every declared name must be produced by episode_metrics
    metrics = a.episode_metrics({"mode_counts": {}, "ep_len": 0,
                                 "reward_channel_totals": {}, "terminal_kind": None})
    assert set(metrics) == set(a.log_metric_names())


def test_episode_metrics_computation():
    a = _adapter()
    summary = {
        "mode_counts": {int(Mode.COMBAT): 6, int(Mode.DIALOGUE): 2,
                        int(Mode.OVERWORLD): 2},
        "ep_len": 10,
        "reward_channel_totals": {"milestone": 3.0, "faction_favor": 1.5},
        "terminal_kind": "success",
    }
    m = a.episode_metrics(summary)
    assert m["r_milestone"] == 3.0
    assert m["r_faction_favor"] == 1.5
    assert m["term_success"] == 1.0
    assert m["term_failure"] == 0.0
    assert m["term_timer"] == 0.0
    assert m["frac_combat"] == 0.6
    assert m["frac_dialogue"] == 0.2
    assert m["frac_overworld"] == 0.2
    assert m["frac_levelup"] == 0.0


def test_episode_metrics_terminal_kinds():
    a = _adapter()
    base = {"mode_counts": {}, "ep_len": 1, "reward_channel_totals": {}}
    assert a.episode_metrics({**base, "terminal_kind": "failure"})["term_failure"] == 1.0
    assert a.episode_metrics({**base, "terminal_kind": "failure_timer"})["term_timer"] == 1.0
    # truncation (no terminal_kind) → no terminal flag set
    trunc = a.episode_metrics({**base, "terminal_kind": None})
    assert trunc["term_success"] == trunc["term_failure"] == trunc["term_timer"] == 0.0
