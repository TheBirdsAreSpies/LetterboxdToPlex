import argparse
import os
import json
import logging
from flask import Flask, render_template_string, jsonify, request, send_file, Response
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

MISSING_FILE = config.missing_path
IGNORE_FILE = config.ignore_path

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
    missing = load_json(MISSING_FILE)
    html = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>LetterboxdToPlex Web</title>
        <style>
            body { font-family: sans-serif; margin: 2rem; background: #fafafa; }
            table { border-collapse: collapse; width: 100%; box-shadow: 0 0 6px rgba(0,0,0,0.1); background: white; }
            th, td { border: 1px solid #ddd; padding: 0.6rem; text-align: left; }
            th { background: #eee; }
            button { padding: 0.4rem 0.8rem; cursor: pointer; background: #444; color: white; border: none; border-radius: 4px; }
            button:hover { background: #000; }
            .danger { background: #d33; }
            .danger:hover { background: #a00; }
            .action-bar { margin-bottom: 1.5rem; }
            #status { padding: 0.8rem; background: #eef; border-radius: 5px; margin-bottom: 1rem; display:none; }
        </style>
    </head>
    <body>
        <h1>LetterboxdToPlex Web</h1>
        
        <div id="status" style="overflow-y:auto; max-height:300px; border:1px solid #ccc; padding:0.5rem; background:#eef;"></div>

        <div class="action-bar">
            <button onclick="runAction('watchlist')">Synchronize Watchlist</button>
            <button onclick="runAction('owned')">Create Owned List</button>
            <button onclick="runAction('rating')">Update Ratings</button>
        </div>
        
        <h2>Missing Movies</h2>
        {% if missing %}
        <table id="missingTable">
            <tr>
                <th onclick="sortTable(0)">Title ▲▼</th>
                <th onclick="sortTable(1)">Year ▲▼</th>
                <th onclick="sortTable(2)">Release Date ▲▼</th>
                <th>Actions</th>
            </tr>
            {% for item in missing %}
            <tr>
                <td>{{ item.name }}</td>
                <td>{{ item.year }}</td>
                <td>
                    {% if item.release_date %}
                        {{ item.release_date.split('T')[0].split(' ')[0] }}
                    {% else %}
                        -
                    {% endif %}
                </td>
                <td><button class="danger" onclick="ignoreItem('{{ item.name }}')">Ignore Movie</button></td>
            </tr>
            {% endfor %}
        </table>
        {% else %}
        <p>No missing movies</p>
        {% endif %}
        
        <script>
        async function runAction(name) {
            const status = document.getElementById('status');
            status.style.display = 'block';
            status.style.background = '#eef';
            status.innerText = 'Starting ' + name + '...';
        
            try {
                if (name === "owned") {
                    const res = await fetch('/action/' + name, { method: 'POST' });
                    const blob = await res.blob();
                    const url = window.URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'owned.csv';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                    window.URL.revokeObjectURL(url);
                    status.innerText = "Owned CSV downloaded";
                    status.style.background = '#e6ffe6';
                } else {
                    const res = await fetch('/action/' + name, { method: 'POST' });
                    const data = await res.json();
                    status.innerText = data.message;
                    status.style.background = '#e6ffe6';
                }
                
                const MAX_LINES = 50;
                let logLines = [];
                if (name === "watchlist") {
                    await fetch('/action/watchlist', { method: 'POST' });
            
                    const eventSource = new EventSource('/stream/watchlist');
                    status.innerHTML = "";
            
                    eventSource.onmessage = function (event) {
                        // Keep only the last MAX_LINES
                        logLines.push(event.data);
                        if (logLines.length > MAX_LINES) {
                            logLines = logLines.slice(logLines.length - MAX_LINES);
                        }
                        status.innerHTML = logLines.join('<br>');
                        status.scrollTop = status.scrollHeight; // auto scroll
                    };

                    eventSource.onerror = function () {
                        eventSource.close();
                        logLines.push("Stream ended or error occurred");
                        if (logLines.length > MAX_LINES) {
                            logLines = logLines.slice(logLines.length - MAX_LINES);
                        }
                        status.innerHTML = logLines.join('<br>');
                        status.scrollTop = status.scrollHeight;
                    };
                }
            } catch (err) {
                status.innerText = 'Error: ' + err;
                status.style.background = '#ffe6e6';
            }
        }

        async function ignoreItem(name) {
            if (!confirm('Do you really want to add „' + name + '“ to ignore list?')) return;
            const res = await fetch('/ignore', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });
            if (res.ok) location.reload();
        }
        
        function sortTable(colIndex) {
            const table = document.getElementById("missingTable");
            const rows = Array.from(table.rows).slice(1);
            let asc = table.getAttribute(`data-sort-col`) != colIndex || table.getAttribute(`data-sort-dir`) == "desc";
            
            rows.sort((a, b) => {
                let aText = a.cells[colIndex].innerText.trim();
                let bText = b.cells[colIndex].innerText.trim();
        
                let aNum = parseFloat(aText), bNum = parseFloat(bText);
                if (!isNaN(aNum) && !isNaN(bNum)) {
                    return asc ? aNum - bNum : bNum - aNum;
                }
        
                return asc ? aText.localeCompare(bText) : bText.localeCompare(aText);
            });
        
            rows.forEach(row => table.appendChild(row));
        
            table.setAttribute("data-sort-col", colIndex);
            table.setAttribute("data-sort-dir", asc ? "asc" : "desc");
        }
        </script>
    </body>
    </html>
    """
    return render_template_string(html, missing=missing)


@app.route("/ignore", methods=["POST"])
def ignore():
    data = request.get_json()
    name = data.get("name")

    missing = load_json(MISSING_FILE)
    ignore_list = load_json(IGNORE_FILE)

    for item in missing:
        if item["name"] == name:
            ignore_list.append(item)
            missing.remove(item)
            break

    save_json(MISSING_FILE, missing)
    save_json(IGNORE_FILE, ignore_list)
    return jsonify(success=True)


@app.route("/action/<name>", methods=["POST"])
def action(name):
    logger = logging.getLogger('')
    logger.setLevel(logging.INFO)

    try:
        if name == "watchlist":
            q = queue.Queue()
            progress_queues['watchlist'] = q

            def progress_callback(msg):
                q.put(msg)

            def run_task():
                try:
                    run_watchlist(logger, progress_callback)
                finally:
                    q.put(None)

            threading.Thread(target=run_task).start()

            return jsonify(success=True)
        elif name == "owned":
            csv_file = run_owned(logger)
            return send_file(csv_file, as_attachment=True)
        elif name == "rating":
            msg = run_rating(logger)
            return jsonify(success=True, message=msg)
        else:
            return jsonify(success=False, message="Unknown action")
    except Exception as e:
        return jsonify(success=False, message=f"Error: {e}")


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


def main():
    global plex, movies

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.FileHandler('ltp.log', encoding='utf-8')]
    )

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
    parser.add_argument('--web', action='store_true', help='starting web server')
    args = parser.parse_args()

    if args.web:
        print("Starting server http://localhost:5000 ...")
        app.run(debug=True, port=5000)
        return

    logger = logging.getLogger('')
    logger.setLevel(level=logging.INFO)

    if config.tmdb_use_api:
        tmdb.create_table()
        tmdb.reorganize_indexes()
        tmdb.invalidate_cache()
        letterboxd.create_table()

    if args.watchlist or (args.owned is None and not args.rating):
        run_watchlist(logger)
    if args.owned is not None:
        run_owned(logger, args.owned)
    if args.rating:
        run_rating(logger)

    print("Done")


if __name__ == "__main__":
    main()
