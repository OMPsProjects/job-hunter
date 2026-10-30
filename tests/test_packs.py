"""Ready-made employer and recruiter lists."""
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from jobhunter import packs, setup  # noqa: E402
from jobhunter.sources import ats  # noqa: E402
from jobhunter.targets import Targets  # noqa: E402


def test_every_pack_entry_is_usable():
    assert packs.all_packs(), "no packs shipped"
    for pid, p in packs.all_packs().items():
        assert p.get("name") and p.get("keywords"), pid
        for e in (p.get("employers") or []) + (p.get("recruiters") or []):
            if e.get("ats"):
                assert e["ats"] in ats.FETCHERS and ats.valid_slug(e["ats"], e["slug"]), (pid, e)
            else:
                assert str(e.get("url", "")).startswith("https://"), (pid, e)


def test_matching_and_apply(tmp_path):
    assert packs.matching("Commercial real estate lending") == ["cre-finance"]
    assert packs.matching("", ["Multifamily Underwriter"]) == ["cre-finance"]
    assert packs.matching("Nursing", ["Charge Nurse"]) == []
    t = Targets(tmp_path / "companies.yaml")
    direct, browse = packs.apply(t, "cre-finance", skip=["Freddie Mac"])
    s = packs.summary("cre-finance")
    assert direct == s["readable"] - 1 and browse == s["employers"] + s["recruiters"] - s["readable"]
    assert not any(c["name"] == "Freddie Mac" for c in t.companies)
    assert packs.apply(t, "cre-finance") == (1, 0)  # only the skipped one is new; nothing doubles up


def test_setup_adds_packs_and_linkedin(tmp_path):
    setup.run_setup(tmp_path, {"titles": ["Commercial Real Estate Underwriter"], "packs": ["cre-finance", "nope"],
                               "linkedin": True, "avoid_companies": ["Berkadia"]}, ask=None, say=lambda *_: None)
    prof = yaml.safe_load((tmp_path / "profile.yaml").read_text().split("\n", 4)[-1])
    assert prof["search"]["sites"] == ["indeed"] and prof["search"]["linkedin_browser"] is True
    comps = yaml.safe_load((tmp_path / "companies.yaml").read_text())
    names = {c["name"] for c in comps["companies"]}
    assert "Walker & Dunlop" in names and "Berkadia" not in names
