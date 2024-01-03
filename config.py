# plex settings
baseurl = 'http://127.0.0.1:32400'
token = 'YOUR_PLEX_TOKEN'

# general settings
use_playlist_as_watchlist = True  # creates a playlist by the watchlist on letterboxd
use_builtin_watchlist = False  # uses the builtin watchlist feature in plex
sort_by_title = True  # sorts the playlist by name - for watchlist as playlist only
ignore_words = ["the", "a", "ein", "eine", "die", "das", "der"]  # if movie starts with one of those words, ignore them and sort by the second word - for playlist only
ignore_movies_in_existing_watchlist = True  # for playlist only
include_watched_not_rated = True  # include movies that have been flagged as watched but are not rated on letterboxd

# plex watchlist as playlist settings
existing_watchlist_name = 'Watchlist'  # the name of the playlist used as watchlist
watchlist_name_to_create = 'Letterboxd Watchlist'  # the new playlist to create with data form letterboxd

# existing files, used from letterboxd export
watchlist_path = 'watchlist.csv'
watched_path = 'watched.csv'
ratings_path = 'ratings.csv'

# files to create
missing_path = 'missing.json'
ignore_path = 'ignore.json'
mapping_path = 'mapping.json'
autoselection_path = 'autoselection.json'
