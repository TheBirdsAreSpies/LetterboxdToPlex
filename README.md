
# Letterboxd to Plex
## Summary

As its name says: **Letterboxd to Plex** will import your (pre exported) Letterboxd watchlist to Plex. Since Plex does not offer the watchlist feature since the beginning, I started to create my own as a playlist some time ago. Somehow I still prefer that playlist style to the newer builtin feature.

This script will also support the default watchlist. Read `Other features` and `Configuration` for further information.

Somewhat similar to [PlexImportWatchlist](https://github.com/techkek/PlexImportWatchlist).
## How to use

1. Install needed third party libraries
```
pip install -r requirements.txt
```

2. Open file `config.py` and edit the fields `baseurl`, as well as `token`. You can retrieve your token by following the [official Plex support article](https://support.plex.tv/articles/204059436-finding-an-authentication-token-x-plex-token/).

2.1 **_Optional_**: Change other settings in `config.py` (see section `Configuration`).

3. Export your personal data from [Letterboxd](https://letterboxd.com/data/export/). You can also do this by navigating to your Letterboxd settings page and click on `Import & Export`. This will download a zip file, containing all your data.

4. Extract data and copy the files `watched.csv`, `watchlist.csv` and `ratings.csv` next to `main.py`.

Or else you can also:

3.1 Update `config.py` and set the field `use_api` to `True`. Also update fields `api_username` and `api_password` to download the zip file automatically.

5. Run `python main.py`
## Other features

- You decide whether this script will use the default watchlist or create a brand-new playlist. If there is another playlist that you have created previously, you can also skip the movies that were already added to that existing list.
- Letterboxd lists some TV shows also. Since this script only supports movies, it will exclude those shows and saves them in a file called `ignore.json`. This will skip those shows and prevents unnecessary API calls in the future.
- You will add movies to your watchlist that are not on your Plex server yet. This script will add all missing movies to a file called `missing.json`.
- Unfortunately Plex' search feature is not perfect. Sometimes a search query will find more than one movie in your collection. This script will ask you which of your movies is the correct one. Afterwards it will memorize your decision and stops to ask when running the script again. This information is stored in a file called `autoselection.json`. You can also enter "0" when it asks for the mapping to skip the procedure (e.g. movie is not present but search still finds movies).
- Since Letterboxd stores all of its information in English, this script may encounter difficulties in finding foreign language movies. You can map those movies yourself and this script will find them in the next run. The most easy way is to cut the entry from `missing.json` and copy it to `mapping.json`. Afterwards you have to enter the correct titles. Take a look to `Examples`.
## Needed Configuration

Edit `config.py` to change your settings.

- **`baseurl`** - Your Plex servers URL
- **`token`** - Your token to get access to your Plex server (see section `How to use`)


### Optional Configuration

- **`use_api`** - If True: The script will try to sign in to your Letterboxd account and download the zip-file automatically
- **`api_username`** - Your Letterboxd username to download the zip file 
- **`api_password`** - Your Letterboxd password
- **`api_use_2fa_code `** - Set this to True if you have enabled Two-Factor-Authentication

- **`use_playlist_as_watchlist`** - If True: This will create a new playlist with your Letterboxd items
- **`use_builtin_watchlist`** - If True: All Letterboxd items will get added to the default watchlist on Plex
- **`sort_by_title`** - If True: Sort the items by titles - this is only relevant if `use_playlist_as_watchlist == True`
- **`ignore_words`** - A list with words that get ignored while sorting to produce proper sorted lists - this is only relevant if `use_playlist_as_watchlist == True` (See `Examples`)
- **`ignore_movies_in_existing_watchlist`** - If True: If there is another watchlist as playlist, this will only add missing items to the created playlist - this is only relevant if `use_playlist_as_watchlist == True`
- **`include_watched_not_rated`** - If True: Adds movies that have been flagged as watched but are not rated on Letterboxd also

- **`existing_watchlist_name`** - The name of the existing playlist used as watchlist - this is only relevant if `ignore_movies_in_existing_watchlist == True`
- **`watchlist_name_to_create`** - The name of the new playlist that will be created - this is only relevant if `use_playlist_as_watchlist == True`

- **`watchlist_path`** - The path of the exported `watchlist.csv`
- **`watched_path`** - The path of the exported `watched.csv`
- **`ratings_path`** - The path of the exported `ratings.csv`

- **`missing_path`** - The path of the created `missing.json`
- **`ignore_path`** - The path of the created `ignore.json`
- **`mapping_path`** - The path of the created `mapping.json`
- **`autoselection_path`** - The path of the created `autoselection.json`

    
## Used libraries

[PlexAPI](https://github.com/pkkid/python-plexapi/)

[tqdm](https://github.com/tqdm/tqdm)

## Examples

`ignore_words = True` will produce the following output:
```
- Desperado
- The Disaster Artist
- Dogville
```
Instead of
```
- Desperado
- Dogville
- The Disaster Artist
```

---

Map foreign language movies in `mapping.json`. You can also add the year of the movie if needed:
```
[
   {
      "letterboxd_title": "Head-On",
      "plex_title": "Gegen die Wand"
   },
   {
      "letterboxd_title": "Portrait of a Lady on Fire",
      "plex_title": "Portrait de la jeune fille en feu"
   },
   {
      "letterboxd_title": "Hercules in New York",
      "plex_title": "Hercules in New York",
      "year": 1975
  }
]
```