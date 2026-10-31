"""The numbers of her urges (decision 46). docs/urges_design_zh.md says why."""

# about him: the reach-out triggers of decisions 10, 26 and 30, moved here unchanged
SILENCE_HOURS = 18  # he has not written for this long
BORED_LEVEL, BORED_SILENCE_HOURS = 60, 6  # bored, and he has been quiet a while
SHARE_IMPORTANCE = 4  # something she saw today, worth telling him
SHARE_AT_MOST = 3
ANNIVERSARIES = (7, 30, 100, 365, 730)  # and every hundred days
