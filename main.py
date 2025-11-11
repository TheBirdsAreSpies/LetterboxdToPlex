import argparse
import os
import json
import logging

from flask import Flask, jsonify, request, send_file, Response, render_template
from enum import Enum
import queue
import threading

import config
import letterboxd
import owned
import rating
import tmdb
import watchlist
import zipfile

from session import Session
from plexapi.myplex import PlexServer

app = Flask(__name__)
progress_queues = {}

plex = None
movies = None


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=3, ensure_ascii=False)


def run_watchlist(logger, progress_callback=None):
    if config.use_api:
        zipfile_name = 'letterboxd_export.zip'
        session = Session(config.api_username, config.api_password, config.api_use_2fa_code)
        session.download_export_data(zipfile_name)

        with zipfile.ZipFile(zipfile_name, 'r') as zip_ref:
            zip_ref.extractall('.')

    logger.name = 'WATCHLIST'
    watchlist.watchlist(plex, movies, logger, progress_callback)
    return "Imported watchlist"


def run_owned(logger, amount=-1):
    logger.name = 'OWNED'
    owned.create_csv(movies, amount, logger)
    return "Created owned list"


def run_rating(logger):
    logger.name = 'RATING'
    rating.rating(plex, movies, logger)
    return "Updated ratings"

@app.route("/")
def index():
    missing = load_json(config.missing_path)
    return render_template("index.html", missing=missing)

@app.route("/ignore", methods=["POST"])
def ignore():
    data = request.get_json()
    name = data.get("name")

    missing = load_json(config.missing_path)
    ignore_list = load_json(config.ignore_path)

    for item in missing:
        if item["name"] == name:
            ignore_list.append(item)
            missing.remove(item)
            break

    save_json(config.missing_path, missing)
    save_json(config.ignore_path, ignore_list)
    return jsonify(success=True)

@app.route("/action/<name>", methods=["POST"])
def action(name):
    logger = logging.getLogger('')
    logger.setLevel(logging.INFO)

    if name == "watchlist":
        if 'watchlist' in progress_queues and progress_queues['watchlist'] is not None:
            return jsonify(success=False, message="Watchlist sync already running")

        q = queue.Queue()
        progress_queues['watchlist'] = q

        def progress_callback(msg):
            q.put(msg)

        def run_task():
            try:
                run_watchlist(logger, progress_callback)
            finally:
                q.put(None)
                progress_queues['watchlist'] = None  # mark done

        threading.Thread(target=run_task, daemon=True).start()
        return jsonify(success=True)


@app.route("/stream/watchlist")
def stream_watchlist():
    q = progress_queues.get('watchlist')
    if not q:
        return "No watchlist running", 404

    def generate():
        while True:
            msg = q.get()
            if msg is None:
                break
            yield f"data: {msg}\n\n"

    return Response(generate(), mimetype='text/event-stream')

@app.route("/config", methods=["GET"])
def config_page():
    # return HTML page
    return render_template("config.html")

@app.route("/config/data")
def config_data():
    if os.path.exists(config.config_path):
        with open(config.config_path, encoding="utf-8") as f:
            cfg = json.load(f)
    else:
        cfg = {}
        for key in dir(config):
            if key.startswith("_") or not key.islower():
                continue
            value = getattr(config, key)

            if isinstance(value, type(config)):
                continue

            # convert enums to string
            if isinstance(value, Enum):
                value = str(value)

            cfg[key] = value
    return jsonify(cfg)

@app.route("/config/save", methods=["POST"])
def config_save():
    try:
        cfg = request.get_json()
        with open(config.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})


def main():
    global plex, movies

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler('ltp.log', encoding='utf-8')]
    )

    parser = argparse.ArgumentParser(prog='LetterboxdToPlex',
                                     description='Tool to export movie information from Plex to Letterboxd and vice versa')
    parser.add_argument('-r', '--rating', action='store_true', help='exports Letterboxd ratings to Plex movies')
    parser.add_argument('-o', '--owned', type=int, nargs='?', const=-1,
                        help='creates a csv file to import to a Letterboxd list. ' +
                             'Used to get the \'owned\' filter. If number is passed after, only that amount of recent movies ' +
                             'will get processed')
    parser.add_argument('-w', '--watchlist', action='store_true',
                        help='exports movies from Letterboxd watchlist to Plex')
    parser.add_argument('--web', action='store_true', help='starting web server')
    args = parser.parse_args()

    logger = logging.getLogger('')
    logger.setLevel(level=logging.INFO)

    plex = PlexServer(config.baseurl, config.token)
    movies = plex.library.section('Movies')

    if args.web:
        print("Starting server http://localhost:5000 ...")
        app.run(debug=False, port=5000)
        return

    if config.tmdb_use_api:
        tmdb.create_table()
        tmdb.reorganize_indexes()
        tmdb.invalidate_cache()
        letterboxd.create_table()

    if not args.web:
        if args.watchlist or (args.owned is None and not args.rating):
            run_watchlist(logger)
        if args.owned is not None:
            run_owned(logger, args.owned)
        if args.rating:
            run_rating(logger)

    print("Done")


if __name__ == "__main__":
    main()
