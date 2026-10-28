"""Her window on the world: fetching only. No model calls, no knowledge of the brain.

feeds     RSS / Atom -> items            bilibili  popular / ranking videos, top comments
wiki      Chinese Wikipedia lookup       reader    a web page -> plain text
files     a file he shared (PDF, Word, text) -> plain text
sources   her subscription list (sources.json)
"""

from fish.world.bilibili import comments, is_bilibili, ranking, popular
from fish.world.feeds import fetch_rss
from fish.world.days import day_line
from fish.world.files import read_file
from fish.world.http import Fetch, FetchError, urllib_fetch
from fish.world.items import Item
from fish.world.place import load_home, load_places, places_line
from fish.world.reader import read_page
from fish.world.sources import gather, load_sources, open_item
from fish.world.wiki import Lookup, Searcher, WikiSearcher

__all__ = ["Fetch", "FetchError", "Item", "Lookup", "Searcher", "WikiSearcher", "comments", "day_line",
           "load_home", "load_places", "places_line",
           "fetch_rss", "gather", "is_bilibili", "load_sources", "open_item", "popular",
           "ranking", "read_file", "read_page", "urllib_fetch"]
