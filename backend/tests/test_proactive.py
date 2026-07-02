"""Pure-function tests for the /plan calorie/protein math (no DB, no LLM)."""

from agents.proactive import _bmr_kcal, _calorie_tiers, _protein_target_g


def test_bmr_matches_mifflin_st_jeor_male():
    # 51yo male, 171cm, ~146.76kg (323.6 lbs) -- the /plan worked example.
    bmr = _bmr_kcal(weight_kg=146.76, height_cm=171, age=51, sex="male")
    assert round(bmr) == 2286  # 10*146.76 + 6.25*171 - 5*51 + 5


def test_bmr_female_offset_is_lower_than_male():
    male = _bmr_kcal(70, 165, 30, "male")
    female = _bmr_kcal(70, 165, 30, "female")
    assert female == male - 166  # +5 vs -161 constant differs by 166


def test_calorie_tiers_ordered_and_within_deficit_conventions():
    tiers = _calorie_tiers(bmr=2286)
    maintenance = tiers["maintenance"]
    assert maintenance == round(2286 * 1.2)
    # Each tier's ceiling sits below maintenance, and floor below ceiling.
    assert tiers["moderate_high"] < maintenance
    assert tiers["moderate_low"] < tiers["moderate_high"]
    assert tiers["aggressive_high"] <= tiers["moderate_low"]
    assert tiers["aggressive_low"] <= tiers["aggressive_high"]
    # Standard 500/750 kcal deficits (3,500 kcal/lb rule).
    assert tiers["moderate_high"] == maintenance - 250
    assert tiers["moderate_low"] == maintenance - 500
    assert tiers["aggressive_high"] == maintenance - 500
    assert tiers["aggressive_low"] == maintenance - 750


def test_calorie_tiers_never_recommend_below_safety_floor():
    tiers = _calorie_tiers(bmr=900)  # a very light person -- maintenance ~1080
    assert tiers["aggressive_low"] >= 1200
    assert tiers["aggressive_high"] >= 1200


def test_protein_target_scales_with_weight_and_is_bounded():
    lo, hi = _protein_target_g(weight_kg=146.76)
    assert 130 <= lo <= hi <= 160  # roughly 1g/kg, matches the /plan worked example
    # Range stays valid (low <= high) and within [90, 200] even for extreme inputs --
    # regression check for a clamping bug where each bound was capped independently.
    tiny_lo, tiny_hi = _protein_target_g(weight_kg=40)
    assert 90 <= tiny_lo <= tiny_hi
    huge_lo, huge_hi = _protein_target_g(weight_kg=250)
    assert huge_lo <= huge_hi <= 200
