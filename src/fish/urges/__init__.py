"""Her urges (decision 46): why she would want to do something, and how much. Never calls a
model, never imports the brain or the channels. Whoever wants to know asks; whether she acts
on it is still hers to decide. docs/urges_design_zh.md is the plan."""

from fish.urges.him import about_him
from fish.urges.urge import HIM, Scene, Urge

__all__ = ["HIM", "Scene", "Urge", "about_him"]
