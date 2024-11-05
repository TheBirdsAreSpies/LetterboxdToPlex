# plex settings
baseurl = 'http://127.0.0.1:32400'
token = 'YOUR_PLEX_TOKEN'

# letterboxd api
use_api = False
api_username = 'USERNAME'
api_password = 'PASSWORD'
api_use_2fa_code = False

# general settings
use_playlist_as_watchlist = True  # creates a playlist by the watchlist on letterboxd
use_builtin_watchlist = False  # uses the builtin watchlist feature in plex
sort_by_title = True  # sorts the playlist by name - for watchlist as playlist only
ignore_words = ["the", "a", "ein", "eine", "die", "das", "der", "le", "les", "il", "lo", "la"]  # if movie starts with one of those words, ignore them and sort by the second word - for playlist only
ignore_movies_in_existing_watchlist = True  # for playlist only
include_watched_not_rated = True  # include movies that have been flagged as watched but are not rated on letterboxd

# plex watchlist as playlist settings
existing_watchlist_name = 'Watchlist'  # the name of the playlist used as watchlist
watchlist_name_to_create = 'Letterboxd Watchlist'  # the new playlist to create with data form letterboxd

# tmdb
tmdb_use_api = False
tmdb_cache = True
tmdb_invalidate_cache = False
tmdb_invalidate_cache_days = 30
tmdb_api_key = 'YOUR_TMDB_TOKEN'
tmdb_language_code = 'DE'  # Look up Alpha-2 codes: https://en.wikipedia.org/wiki/ISO_3166-1#Codes

# existing files, used from letterboxd export
watchlist_path = 'watchlist.csv'
watched_path = 'watched.csv'
ratings_path = 'ratings.csv'

# files to create
missing_path = 'missing.json'
ignore_path = 'ignore.json'
mapping_path = 'mapping.json'
autoselection_path = 'autoselection.json'
