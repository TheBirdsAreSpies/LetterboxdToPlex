import argparse
import os
import json
import logging
import queue
import threading
import time

from flask import Flask, jsonify, request, Response, render_template
from enum import Enum

import csv
import config
import letterboxd
import owned
import rating
import tmdb
import watchlist
import zipfile
import selector

from session import Session
from plexapi.myplex import PlexServer

app = Flask(__name__)

plex = None
movies = None

TASK_LOG_LIMIT = 200
THREAD_TASKS = {"watchlist", "rating"}
task_states = {}
task_listeners = {}
task_state_lock = threading.Lock()


def load_json(path):
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=3, ensure_ascii=False)


def log_progress(progress_callback, message):
    if progress_callback:
        progress_callback(str(message))


def _existing_paths(paths):
    return [path for path in paths if os.path.exists(path)]


def _extract_export_archive(zipfile_name, progress_callback=None):
    log_progress(progress_callback, f"Extracting Letterboxd export archive from '{zipfile_name}'...")
    with zipfile.ZipFile(zipfile_name, 'r') as zip_ref:
        zip_ref.extractall('.')


def _required_export_paths(task_name):
    required = []

    if task_name == "watchlist":
        required.append(config.watchlist_path)
        if config.include_watched_not_rated:
            required.extend([config.watched_path, config.ratings_path])
    elif task_name == "rating":
        required.append(config.ratings_path)

    seen = set()
    unique_required = []
    for path in required:
        if path not in seen:
            unique_required.append(path)
            seen.add(path)
    return unique_required


def lb_export(task_name=None, progress_callback=None):
    if not config.use_api:
        return

    zipfile_name = 'letterboxd_export.zip'
    skip_download = False
    required_paths = _required_export_paths(task_name)

    if os.path.exists(zipfile_name):
        mtime = os.path.getmtime(zipfile_name)
        age_seconds = time.time() - mtime
        if age_seconds < 5 * 60:
            skip_download = True

    if skip_download:
        log_progress(progress_callback, "Using recent Letterboxd export from disk...")
        _extract_export_archive(zipfile_name, progress_callback)
        return

    try:
        log_progress(progress_callback, "Signing in to Letterboxd...")
        session = Session(config.api_username, config.api_password, config.api_use_2fa_code)
        log_progress(progress_callback, "Downloading latest Letterboxd export...")
        session.download_export_data(zipfile_name)
        _extract_export_archive(zipfile_name, progress_callback)
        return
    except Exception as exc:
        log_progress(progress_callback, f"Letterboxd download blocked, checking local fallback... ({exc})")

    if os.path.exists(zipfile_name):
        log_progress(progress_callback, "Using existing export ZIP as fallback because live login/download failed.")
        _extract_export_archive(zipfile_name, progress_callback)
        return

    existing_required = _existing_paths(required_paths)
    if required_paths and len(existing_required) == len(required_paths):
        log_progress(progress_callback, "Using existing extracted Letterboxd CSV files as fallback because live login/download failed.")
        return

    missing_required = [path for path in required_paths if path not in existing_required]
    if missing_required:
        raise Exception(
            "Letterboxd login/download was blocked by Cloudflare and no usable local export fallback was found. "
            f"Missing files: {', '.join(missing_required)}"
        )

    raise Exception(
        "Letterboxd login/download was blocked by Cloudflare and no usable local export fallback was found."
    )


def run_watchlist(logger, progress_callback=None):
    lb_export("watchlist", progress_callback)

    logger.name = 'WATCHLIST'
    watchlist.watchlist(plex, movies, logger, progress_callback)
    return "Imported watchlist"

def run_owned(logger, amount=200):
    logger.name = 'OWNED'
    return owned.create_csv(movies, amount, logger)

def run_rating(logger, progress_callback=None):
    lb_export("rating", progress_callback)

    logger.name = 'RATING'
    rating.rating(plex, movies, logger, progress_callback)
    return "Updated ratings"

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/missing")
def get_missing():
    return jsonify(load_json(config.missing_path))

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

def load_csv_names(path):
    names = set()
    if not os.path.exists(path):
        return names
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("Name", "").strip().lower()
            if name:
                names.add(name)
    return names


def _empty_task_state(task_name):
    return {
        "name": task_name,
        "running": False,
        "status": "idle",
        "message": "",
        "logs": [],
        "started_at": None,
        "finished_at": None,
        "updated_at": None,
    }


def _copy_task_state(task_name):
    with task_state_lock:
        state = dict(task_states.get(task_name, _empty_task_state(task_name)))
    state["logs"] = list(state.get("logs", []))
    return state


def _append_task_log(task_name, message, notify=True):
    if message is None:
        return

    text = str(message)
    with task_state_lock:
        state = task_states.setdefault(task_name, _empty_task_state(task_name))
        state["logs"] = (state.get("logs", []) + [text])[-TASK_LOG_LIMIT:]
        state["message"] = text
        state["updated_at"] = time.time()
        listeners = list(task_listeners.get(task_name, [])) if notify else []

    for listener in listeners:
        listener.put(text)


def _start_task_state(task_name, message):
    with task_state_lock:
        state = task_states.setdefault(task_name, _empty_task_state(task_name))
        state.update({
            "running": True,
            "status": "running",
            "message": message,
            "logs": [message],
            "started_at": time.time(),
            "finished_at": None,
            "updated_at": time.time(),
        })


def _finish_task_state(task_name, status, message):
    with task_state_lock:
        state = task_states.setdefault(task_name, _empty_task_state(task_name))
        state["running"] = False
        state["status"] = status
        state["message"] = message
        state["finished_at"] = time.time()
        state["updated_at"] = time.time()


def _is_task_running(task_name):
    with task_state_lock:
        return bool(task_states.get(task_name, {}).get("running"))


def _add_task_listener(task_name, listener):
    with task_state_lock:
        task_listeners.setdefault(task_name, []).append(listener)


def _remove_task_listener(task_name, listener):
    with task_state_lock:
        listeners = task_listeners.get(task_name)
        if not listeners:
            return
        if listener in listeners:
            listeners.remove(listener)
        if not listeners:
            task_listeners.pop(task_name, None)


def _close_task_streams(task_name):
    with task_state_lock:
        listeners = task_listeners.pop(task_name, [])

    for listener in listeners:
        listener.put(None)


def _most_recent_task_name(task_details):
    latest_name = None
    latest_ts = None

    for task_name, state in task_details.items():
        updated_at = state.get("updated_at")
        if updated_at is None:
            continue
        if latest_ts is None or updated_at > latest_ts:
            latest_name = task_name
            latest_ts = updated_at

    return latest_name


def _task_status_payload():
    task_details = {task_name: _copy_task_state(task_name) for task_name in sorted(THREAD_TASKS)}
    running_tasks = [task_name for task_name, state in task_details.items() if state.get("running")]
    active_task = running_tasks[0] if running_tasks else _most_recent_task_name(task_details)

    return {
        "running": bool(running_tasks),
        "task_name": active_task,
        "tasks": running_tasks,
        "active_task": active_task,
        "details": task_details,
    }


def _run_threaded_task(name):
    task_runners = {
        "watchlist": run_watchlist,
        "rating": run_rating,
    }

    if name not in task_runners:
        raise ValueError(f"Unknown threaded task '{name}'")

    if _is_task_running(name):
        return False, f"{name.capitalize()} task already running"

    start_message = f"{name.capitalize()} task started"
    _start_task_state(name, start_message)

    def run_task():
        logger = logging.getLogger(name.upper())
        logger.setLevel(logging.INFO)

        try:
            result = task_runners[name](logger, lambda msg: _append_task_log(name, msg))
            if result:
                _append_task_log(name, result)
            _finish_task_state(name, "completed", result or f"{name.capitalize()} task completed")
        except Exception as exc:
            logging.exception("Task %s failed", name)
            error_message = f"{name.capitalize()} task failed: {exc}"
            _append_task_log(name, error_message)
            _finish_task_state(name, "failed", error_message)
        finally:
            _close_task_streams(name)

    threading.Thread(target=run_task, daemon=True).start()
    return True, start_message


@app.route("/action/<name>", methods=["POST"])
def action(name):
    if name not in [
        "watchlist",
        "owned",
        "rating",
        "cleanup_missing",
        "strip_missing_years"
    ]:
        return jsonify(success=False, message=f"Unknown action '{name}'")

    if name in THREAD_TASKS:
        started, message = _run_threaded_task(name)
        return jsonify(success=started, message=message)

    elif name == "owned":
        logger = logging.getLogger('OWNED')
        logger.setLevel(logging.INFO)
        csv_data = run_owned(logger)
        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=owned.csv"}
        )

    elif name == "cleanup_missing":
        with open(config.missing_path, "r", encoding="utf-8") as f:
            missing = json.load(f)

        known_names = set()
        known_names |= load_csv_names(config.watchlist_path)
        known_names |= load_csv_names(config.watched_path)
        known_names |= load_csv_names(config.ratings_path)

        original_count = len(missing)

        cleaned = []
        for m in missing:
            missing_name = str(m.get("name", "")).strip().lower()
            if missing_name not in known_names:
                cleaned.append(m)

        with open(config.missing_path, "w", encoding="utf-8") as f:
            json.dump(cleaned, f, indent=2)

        return jsonify(
            success=True,
            message=f"Removed {original_count - len(cleaned)} entries from missing list"
        )

    elif name == "strip_missing_years":
        with open(config.missing_path, "r", encoding="utf-8") as f:
            missing = json.load(f)

        changed = 0

        for m in missing:
            if m.get("release_date") is not None:
                m["release_date"] = None
                changed += 1

        with open(config.missing_path, "w", encoding="utf-8") as f:
            json.dump(missing, f, indent=2)

        return jsonify(
            success=True,
            message=f"Cleaned years from {changed} missing entries"
        )

@app.route("/stream/<task_name>")
def stream_task(task_name):
    if task_name not in THREAD_TASKS:
        return "Unknown task", 404

    state = _copy_task_state(task_name)
    replay_history = request.args.get("replay", "1") != "0"
    if not state["logs"] and not state["running"]:
        return "No task data available", 404

    listener = queue.Queue()
    if state["running"]:
        _add_task_listener(task_name, listener)

    def generate():
        try:
            if replay_history:
                for msg in state["logs"]:
                    yield f"data: {msg}\n\n"

            if not state["running"]:
                return

            while True:
                msg = listener.get()
                if msg is None:
                    break
                yield f"data: {msg}\n\n"
        finally:
            _remove_task_listener(task_name, listener)

    return Response(
        generate(),
        mimetype='text/event-stream',
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )

@app.route("/task/status")
def task_status():
    return jsonify(_task_status_payload())

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
    global plex, movies
    try:
        cfg = request.get_json()

        with open(config.config_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=4)

        for key, value in cfg.items():
            setattr(config, key, value)

        connected = False
        try:
            if config.tmdb_use_api:
                tmdb.create_table()
                tmdb.reorganize_indexes()
                tmdb.invalidate_cache()
                letterboxd.create_table()

            plex = PlexServer(config.baseurl, config.token)
            movies = plex.library.section('Movies')
            connected = True
        except Exception as e:
            plex = None
            movies = None
            return jsonify({
                "success": True,
                "plex_connected": False,
                "message": f"Config saved, but failed to connect to Plex: {str(e)}"
            })

        return jsonify({
            "success": True,
            "plex_connected": connected,
            "message": "Config saved and connected to Plex successfully"
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e)
        })

@app.route("/autoselections")
def get_autoselections():
    # return all pending selections as JSON
    l = []
    for sel in selector.selection_requests.values():
        combination = sel["combination"]
        combination_dict = {
            "name": combination.name,
            "year": combination.year
        }
        l.append({
            "combination": combination_dict,
            "options": sel["options"]
        })
    return jsonify(l)

@app.route("/autoselections/choose", methods=["POST"])
def choose_autoselection():
    try:
        data = request.get_json()
        combo_name = data.get("name")
        combo_year = data.get("year")
        selected_key = data.get("selected_key")

        key_to_set_event = None

        for sel_id, sel in list(selector.selection_requests.items()):
            combo = sel["combination"]
            if combo.name == combo_name and combo.year == combo_year:
                from autoselection import AutoSelection
                autoselector = AutoSelection.load_json() or []
                autoselector.append(AutoSelection(combo, selected_key))
                AutoSelection.store_json(autoselector)

                key_to_set_event = combo.name

                del selector.selection_requests[sel_id]
                break

        # signal waiting thread
        if key_to_set_event and key_to_set_event in selector.selection_events:
            selector.selection_results[key_to_set_event] = selected_key
            selector.selection_events[key_to_set_event].set()

        return jsonify(success=True, message=f"Selected {combo_name} ({combo_year})")

    except Exception as e:
        return jsonify(success=False, message=str(e))

@app.route("/autoselections/skip", methods=["POST"])
def autoselection_skip():
    try:
        data = request.get_json()

        name = data.get("name")
        year = data.get("year")

        removed = False
        key_to_set_event = None
        for key, sel in list(selector.selection_requests.items()):
            if sel['combination'].name == name and sel['combination'].year == year:
                del selector.selection_requests[key]
                removed = True
                key_to_set_event = sel['combination'].name
                break

        # Trigger the event to unblock choose_movie
        if key_to_set_event and key_to_set_event in selector.selection_events:
            selector.selection_results[key_to_set_event] = None  # indicate skipped
            selector.selection_events[key_to_set_event].set()  # unblock the waiting thread

        if removed:
            return jsonify(success=True, message=f"Skipped {name} ({year})")
        else:
            return jsonify(success=False, message="Selection not found")
    except Exception as e:
        return jsonify(success=False, message=str(e))

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

    if not os.path.exists("data"): os.mkdir("data")
    if not os.path.exists("config"): os.mkdir("config")

    try:
        plex = PlexServer(config.baseurl, config.token)
        movies = plex.library.section('Movies')
    except Exception:
        logger.error("Not able to connect to Plex")

    if config.tmdb_use_api:
        tmdb.create_table()
        tmdb.reorganize_indexes()
        tmdb.invalidate_cache()
        letterboxd.create_table()

    if args.web:
        config.web_mode = True

        print("Starting server http://localhost:5000 ...")
        app.run(host="0.0.0.0", port=5000, debug=False)
        return

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
