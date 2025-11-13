import json
import os
import tmdb
from enum import Enum

# plex settings
baseurl = "http://127.0.0.1:32400"
token = "YOUR_PLEX_TOKEN"

# letterboxd settings
use_api = False
api_username = "USERNAME"
api_password = "PASSWORD"
api_use_2fa_code = False

# general settings
use_playlist_as_watchlist = True   # creates a playlist by the watchlist on letterboxd
use_builtin_watchlist = False  # uses the builtin watchlist feature in plex
sort_by_title = True  # sorts the playlist by name - for watchlist as playlist only
ignore_words = ["the", "a", "ein", "eine", "die", "das", "der", "le", "les", "il", "lo", "la"]   # if movie starts with one of those words, ignore them and sort by the second word - for playlist only
ignore_movies_in_existing_watchlist = True  # for playlist only
include_watched_not_rated = True  # include movies that have been flagged as watched but are not rated on letterboxd

# plex watchlist as playlist settings
existing_watchlist_name = "Watchlist"  # the name of the playlist used as watchlist
watchlist_name_to_create = "Letterboxd Watchlist"  # the new playlist to create with data form letterboxd

# tmdb
tmdb_use_api = False
tmdb_cache = True
tmdb_invalidate_cache = False
tmdb_invalidate_cache_days = 30
tmdb_api_key = "YOUR_TMDB_TOKEN"
tmdb_language_code = "US"  # Look up Alpha-2 codes: https://en.wikipedia.org/wiki/ISO_3166-1#Codes
tmdb_release_country_code = "US"
tmdb_release_type: tmdb.ReleaseType = tmdb.ReleaseType.DIGITAL

# existing files, used from letterboxd export
watchlist_path = "watchlist.csv"
watched_path = "watched.csv"
ratings_path = "ratings.csv"

# files to create
config_path = "config/config.json"
missing_path = "data/missing.json"
ignore_path = "data/ignore.json"
mapping_path = "data/mapping.json"
autoselection_path = "data/autoselection.json"
db_path = "data/ltp.db"

web_mode = False

if os.path.exists(config_path):
    try:
        with open(config_path, encoding="utf-8") as f:
            cfg = json.load(f)

        for key, value in cfg.items():
            if key in globals():
                current_value = globals()[key]

                if isinstance(current_value, Enum) and isinstance(value, str) and '.' in value:
                    enum_class = type(current_value)
                    enum_name = value.split('.')[-1]
                    value = enum_class[enum_name]

                globals()[key] = value

    except json.JSONDecodeError:
        print(f"Warning: {config_path} is invalid JSON. Using defaults.")
    except Exception as e:
        print(f"Warning: Failed to load {config_path}: {e}")
