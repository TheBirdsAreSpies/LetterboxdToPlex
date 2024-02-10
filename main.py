import argparse
import config
import owned
import watchlist
import zipfile
from session import Session
from plexapi.myplex import PlexServer


def main():
    plex = PlexServer(config.baseurl, config.token)
    movies = plex.library.section('Movies')

    parser = argparse.ArgumentParser(prog='LetterboxdToPlex',
                                     description='Tool to export movie information from Plex to Letterboxd and vice versa')
    parser.add_argument('-r', '--rating', action='store_true', help='exports Letterboxd ratings to Plex movies')
    parser.add_argument('-o', '--owned', type=int, nargs='?', const=-1,
                        help='creates a csv file to import to a Letterboxd list. ' +
                             'Used to get the \'owned\' filter. If number is passed after, only that amount of recent movies ' +
                             'will get processed')
    parser.add_argument('-w', '--watchlist', action='store_true',
                        help='exports movies from Letterboxd watchlist to Plex')
    args = parser.parse_args()

    if args.watchlist or (args.owned is None and not args.rating):
        if config.use_api:
            zipfile_name = 'letterboxd_export.zip'
            session = Session(config.api_username, config.api_password, config.api_use_2fa_code)
            session.download_export_data(zipfile_name)

            with zipfile.ZipFile(zipfile_name, 'r') as zip_ref:
                zip_ref.extractall('.')

        watchlist.watchlist(plex, movies)
    if args.owned is not None:
        owned.create_csv(movies, args.owned)
    if args.rating:
        # todo implement
        pass

    print("Done")


if __name__ == "__main__":
    main()
