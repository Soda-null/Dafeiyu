"""Her window on the world: fetching only. No model calls, no knowledge of the brain.

feeds     RSS / Atom -> items            bilibili  popular / ranking videos, top comments
wiki      Chinese Wikipedia lookup       reader    a web page -> plain text
files     a file he shared (PDF, Word, text) -> plain text
sources   her subscription list (sources.json)
"""

from fish.world.bilibili import comments, is_bilibili, ranking, popular
from fish.world.feeds import fetch_rss
from fish.world.days import day_line, refresh_holidays
from fish.world.files import read_file
from fish.world.http import (Fetch, FetchBytes, FetchError, FetchPost, bot_fetch, urllib_fetch, urllib_fetch_bytes,
                             urllib_post)
from fish.world.items import Item
from fish.world.place import (Home, Place, load_home, load_places, locate, nearby, neighbourhood_map, places_line,
                              weather)
from fish.world.reader import read_page
from fish.world.sources import gather, load_sources, open_item
from fish.world.wiki import Lookup, Searcher, WikiSearcher
from fish.world.wikisource import find_book, page_url, read_part

__all__ = ["Fetch", "FetchBytes", "FetchError", "FetchPost", "Home", "Place", "bot_fetch", "find_book",
           "locate", "nearby", "neighbourhood_map", "page_url", "read_part", "refresh_holidays", "urllib_fetch_bytes",
           "urllib_post", "weather", "Item", "Lookup", "Searcher", "WikiSearcher", "comments", "day_line",
           "load_home", "load_places", "places_line",
           "fetch_rss", "gather", "is_bilibili", "load_sources", "open_item", "popular",
           "ranking", "read_file", "read_page", "urllib_fetch"]
