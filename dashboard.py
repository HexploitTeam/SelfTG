# dashboard.py
import os
import json
import datetime
from flask import Flask, render_template_string, request, redirect, url_for, flash

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # for flash messages

# Paths
STATS_FILE = "mode/stats.json"
CHATSTATS_FILE = "mode/chatstats.json"
ENEMY_FILE = "mode/Enemy.json"
WARN_FILE = "mode/warn.json"
MUTE_FILE = "mode/mute.json"
SETTINGS_FILE = "mode/settings.json"

# ---------- Helpers ----------
def load_json(fpath):
    if not os.path.exists(fpath):
        return {}
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_json(fpath, data):
    os.makedirs(os.path.dirname(fpath), exist_ok=True)
    with open(fpath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def get_default_settings():
    return {
        "enemy_enabled": True,
        "warn_enabled": True,
        "mute_enabled": True,
        "reply_enabled": False,
        "log_enabled": False,
        "auto_solve": False,
        "stats_enabled": True
    }

def load_settings():
    settings = load_json(SETTINGS_FILE)
    defaults = get_default_settings()
    # merge missing keys
    for k, v in defaults.items():
        if k not in settings:
            settings[k] = v
    return settings

def save_settings(settings):
    save_json(SETTINGS_FILE, settings)

def get_total_stats(stats_data):
    total = {
        "total_msgs": 0,
        "total_chars": 0,
        "total_words": 0,
        "total_emojis": 0,
        "total_mentions": 0,
        "replies_given": 0,
        "media": {},
        "word_counts": {},
        "emoji_counts": {},
        "mention_counts": {},
        "daily_counts": {},
    }
    for chat_id, chat_data in stats_data.items():
        for user_id, user_stats in chat_data.get("users", {}).items():
            total["total_msgs"] += user_stats.get("total_msgs", 0)
            total["total_chars"] += user_stats.get("total_chars", 0)
            total["total_words"] += user_stats.get("total_words", 0)
            total["total_emojis"] += user_stats.get("total_emojis", 0)
            total["total_mentions"] += user_stats.get("total_mentions", 0)
            total["replies_given"] += user_stats.get("replies_given", 0)
            for k, v in user_stats.get("media", {}).items():
                total["media"][k] = total["media"].get(k, 0) + v
            for w, c in user_stats.get("word_counts", {}).items():
                total["word_counts"][w] = total["word_counts"].get(w, 0) + c
            for e, c in user_stats.get("emoji_counts", {}).items():
                total["emoji_counts"][e] = total["emoji_counts"].get(e, 0) + c
            for m, c in user_stats.get("mention_counts", {}).items():
                total["mention_counts"][m] = total["mention_counts"].get(m, 0) + c
            for day, count in user_stats.get("daily_counts", {}).items():
                total["daily_counts"][day] = total["daily_counts"].get(day, 0) + count
    return total

def get_all_users(stats_data):
    users = {}
    for chat_id, chat_data in stats_data.items():
        for user_id, user_stats in chat_data.get("users", {}).items():
            if user_id not in users:
                users[user_id] = {
                    "total_msgs": 0,
                    "total_chars": 0,
                    "total_words": 0,
                    "total_emojis": 0,
                    "total_mentions": 0,
                    "replies_given": 0,
                    "media": {},
                    "word_counts": {},
                    "emoji_counts": {},
                    "mention_counts": {},
                    "chats": []
                }
            u = users[user_id]
            u["total_msgs"] += user_stats.get("total_msgs", 0)
            u["total_chars"] += user_stats.get("total_chars", 0)
            u["total_words"] += user_stats.get("total_words", 0)
            u["total_emojis"] += user_stats.get("total_emojis", 0)
            u["total_mentions"] += user_stats.get("total_mentions", 0)
            u["replies_given"] += user_stats.get("replies_given", 0)
            for k, v in user_stats.get("media", {}).items():
                u["media"][k] = u["media"].get(k, 0) + v
            for w, c in user_stats.get("word_counts", {}).items():
                u["word_counts"][w] = u["word_counts"].get(w, 0) + c
            for e, c in user_stats.get("emoji_counts", {}).items():
                u["emoji_counts"][e] = u["emoji_counts"].get(e, 0) + c
            for m, c in user_stats.get("mention_counts", {}).items():
                u["mention_counts"][m] = u["mention_counts"].get(m, 0) + c
            u["chats"].append(chat_id)
    return users

# ---------- Routes ----------
@app.route('/')
def overview():
    stats = load_json(STATS_FILE)
    chatstats = load_json(CHATSTATS_FILE)
    enemies = load_json(ENEMY_FILE)
    warns = load_json(WARN_FILE)
    mutes = load_json(MUTE_FILE)

    total = get_total_stats(stats) if stats else {}
    top_words = sorted(total.get("word_counts", {}).items(), key=lambda x: x[1], reverse=True)[:10]
    top_emojis = sorted(total.get("emoji_counts", {}).items(), key=lambda x: x[1], reverse=True)[:10]
    top_mentions = sorted(total.get("mention_counts", {}).items(), key=lambda x: x[1], reverse=True)[:10]

    daily = total.get("daily_counts", {})
    sorted_days = sorted(daily.items())
    days = [d for d, _ in sorted_days]
    counts = [c for _, c in sorted_days]

    enemy_count = sum(len(v) for v in enemies.values()) if enemies else 0
    warn_count = 0
    for chat_id, chat_data in warns.items():
        warn_count += len(chat_data.get("warnings", {})) if chat_data else 0
    mute_count = 0
    for chat_id, users in mutes.items():
        mute_count += len(users) if users else 0
    chat_count = len(chatstats) if chatstats else 0

    return render_template_string(HTML_OVERVIEW, total=total, top_words=top_words,
                                  top_emojis=top_emojis, top_mentions=top_mentions,
                                  days=days, counts=counts, chat_count=chat_count,
                                  enemy_count=enemy_count, warn_count=warn_count,
                                  mute_count=mute_count)

@app.route('/chats')
def chats():
    chatstats = load_json(CHATSTATS_FILE)
    chat_list = list(chatstats.values()) if chatstats else []
    return render_template_string(HTML_CHATS, chats=chat_list)

@app.route('/users')
def users():
    stats = load_json(STATS_FILE)
    users_dict = get_all_users(stats)
    user_list = []
    for uid, u in users_dict.items():
        user_list.append({
            "id": uid,
            "msgs": u["total_msgs"],
            "chars": u["total_chars"],
            "words": u["total_words"],
            "emojis": u["total_emojis"],
            "mentions": u["total_mentions"],
            "replies": u["replies_given"],
            "chats": len(u["chats"])
        })
    user_list.sort(key=lambda x: x["msgs"], reverse=True)
    return render_template_string(HTML_USERS, users=user_list)

@app.route('/enemies', methods=['GET', 'POST'])
def enemies():
    if request.method == 'POST':
        action = request.form.get('action')
        chat_id = request.form.get('chat_id')
        user_id = request.form.get('user_id')
        category = request.form.get('category', 'default')
        custom_text = request.form.get('custom_text', '')
        if action == 'add' and chat_id and user_id:
            enemies = load_json(ENEMY_FILE)
            if chat_id not in enemies:
                enemies[chat_id] = []
            # check if user already exists
            if not any(u.get('user_id') == int(user_id) for u in enemies[chat_id]):
                enemies[chat_id].append({"user_id": int(user_id), "category": category, "custom_text": custom_text})
                save_json(ENEMY_FILE, enemies)
                flash('Enemy added.', 'success')
            else:
                flash('User already in enemy list.', 'warning')
        elif action == 'remove' and chat_id and user_id:
            enemies = load_json(ENEMY_FILE)
            if chat_id in enemies:
                enemies[chat_id] = [u for u in enemies[chat_id] if str(u.get('user_id')) != user_id]
                save_json(ENEMY_FILE, enemies)
                flash('Enemy removed.', 'success')
        return redirect(url_for('enemies'))

    enemies = load_json(ENEMY_FILE)
    # flatten
    enemy_list = []
    for cid, users in enemies.items():
        for u in users:
            enemy_list.append({
                "chat_id": cid,
                "user_id": u.get("user_id"),
                "category": u.get("category", "default"),
                "custom_text": u.get("custom_text", "")
            })
    return render_template_string(HTML_ENEMIES, enemies=enemy_list)

@app.route('/warns', methods=['GET', 'POST'])
def warns():
    if request.method == 'POST':
        action = request.form.get('action')
        chat_id = request.form.get('chat_id')
        user_id = request.form.get('user_id')
        if action == 'set_limit' and chat_id:
            limit = request.form.get('limit')
            try:
                limit = int(limit)
                if limit < 1:
                    flash('Limit must be at least 1.', 'danger')
                    return redirect(url_for('warns'))
            except:
                flash('Invalid limit.', 'danger')
                return redirect(url_for('warns'))
            warns_data = load_json(WARN_FILE)
            if chat_id not in warns_data:
                warns_data[chat_id] = {"limit": limit, "warnings": {}}
            else:
                warns_data[chat_id]["limit"] = limit
            save_json(WARN_FILE, warns_data)
            flash(f'Warning limit for chat {chat_id} set to {limit}.', 'success')
        elif action == 'clear_user' and chat_id and user_id:
            warns_data = load_json(WARN_FILE)
            if chat_id in warns_data and user_id in warns_data[chat_id].get("warnings", {}):
                del warns_data[chat_id]["warnings"][user_id]
                save_json(WARN_FILE, warns_data)
                flash(f'Cleared warnings for user {user_id} in chat {chat_id}.', 'success')
            else:
                flash('User not found or no warnings.', 'warning')
        return redirect(url_for('warns'))

    warns_data = load_json(WARN_FILE)
    warn_list = []
    for cid, wdata in warns_data.items():
        limit = wdata.get("limit", 3)
        for uid, reasons in wdata.get("warnings", {}).items():
            for reason in reasons:
                warn_list.append({
                    "chat_id": cid,
                    "user_id": uid,
                    "reason": reason,
                    "limit": limit
                })
    return render_template_string(HTML_WARNS, warns=warn_list)

@app.route('/mutes', methods=['GET', 'POST'])
def mutes():
    if request.method == 'POST':
        action = request.form.get('action')
        chat_id = request.form.get('chat_id')
        user_id = request.form.get('user_id')
        mode = request.form.get('mode', 'admin')
        if action == 'add' and chat_id and user_id:
            mutes_data = load_json(MUTE_FILE)
            if chat_id not in mutes_data:
                mutes_data[chat_id] = []
            if not any(u.get('user_id') == int(user_id) for u in mutes_data[chat_id]):
                mutes_data[chat_id].append({"user_id": int(user_id), "mode": mode})
                save_json(MUTE_FILE, mutes_data)
                flash('Mute added.', 'success')
            else:
                flash('User already muted.', 'warning')
        elif action == 'remove' and chat_id and user_id:
            mutes_data = load_json(MUTE_FILE)
            if chat_id in mutes_data:
                mutes_data[chat_id] = [u for u in mutes_data[chat_id] if str(u.get('user_id')) != user_id]
                save_json(MUTE_FILE, mutes_data)
                flash('Mute removed.', 'success')
        return redirect(url_for('mutes'))

    mutes_data = load_json(MUTE_FILE)
    mute_list = []
    for cid, users in mutes_data.items():
        for u in users:
            mute_list.append({
                "chat_id": cid,
                "user_id": u.get("user_id"),
                "mode": u.get("mode", "admin")
            })
    return render_template_string(HTML_MUTES, mutes=mute_list)

@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if request.method == 'POST':
        settings = load_settings()
        # toggle keys
        for key in settings.keys():
            if key in request.form:
                settings[key] = request.form.get(key) == 'on'
        save_settings(settings)
        flash('Settings updated.', 'success')
        return redirect(url_for('settings'))

    settings = load_settings()
    return render_template_string(HTML_SETTINGS, settings=settings)

# ---------- HTML Templates (inline) ----------
HTML_OVERVIEW = '''
<!DOCTYPE html>
<html>
<head>
    <title>Selfbot Dashboard</title>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { background: #f8f9fa; }
        .stat-card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); text-align: center; height: 100%; }
        .stat-number { font-size: 2.5rem; font-weight: bold; color: #0d6efd; }
        .stat-label { color: #6c757d; }
        .nav-link { font-weight: 500; }
    </style>
</head>
<body>
    <nav class="navbar navbar-expand-lg navbar-dark bg-dark">
        <div class="container-fluid">
            <a class="navbar-brand" href="/">🤖 Selfbot</a>
            <button class="navbar-toggler" type="button" data-bs-toggle="collapse" data-bs-target="#navbarNav">
                <span class="navbar-toggler-icon"></span>
            </button>
            <div class="collapse navbar-collapse" id="navbarNav">
                <ul class="navbar-nav">
                    <li class="nav-item"><a class="nav-link" href="/">Overview</a></li>
                    <li class="nav-item"><a class="nav-link" href="/chats">Chats</a></li>
                    <li class="nav-item"><a class="nav-link" href="/users">Users</a></li>
                    <li class="nav-item"><a class="nav-link" href="/enemies">Enemies</a></li>
                    <li class="nav-item"><a class="nav-link" href="/warns">Warns</a></li>
                    <li class="nav-item"><a class="nav-link" href="/mutes">Mutes</a></li>
                    <li class="nav-item"><a class="nav-link" href="/settings">Settings</a></li>
                </ul>
            </div>
        </div>
    </nav>
    <div class="container mt-4">
        {% with messages = get_flashed_messages(with_categories=true) %}
          {% if messages %}
            {% for category, message in messages %}
              <div class="alert alert-{{ category }} alert-dismissible fade show" role="alert">
                {{ message }}
                <button type="button" class="btn-close" data-bs-dismiss="alert" aria-label="Close"></button>
              </div>
            {% endfor %}
          {% endif %}
        {% endwith %}
        <div class="row">
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ total.total_msgs }}</div><div class="stat-label">Total Messages</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ total.total_chars }}</div><div class="stat-label">Characters</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ total.total_words }}</div><div class="stat-label">Words</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ total.total_emojis }}</div><div class="stat-label">Emojis</div></div></div>
        </div>
        <div class="row mt-3">
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ chat_count }}</div><div class="stat-label">Chats</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ enemy_count }}</div><div class="stat-label">Enemies</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ warn_count }}</div><div class="stat-label">Warnings</div></div></div>
            <div class="col-md-3"><div class="stat-card"><div class="stat-number">{{ mute_count }}</div><div class="stat-label">Mutes</div></div></div>
        </div>

        <div class="row mt-4">
            <div class="col-md-8">
                <div class="card">
                    <div class="card-header">📊 Daily Activity</div>
                    <div class="card-body"><canvas id="activityChart" height="200"></canvas></div>
                </div>
            </div>
            <div class="col-md-4">
                <div class="card">
                    <div class="card-header">🏆 Top Words</div>
                    <ul class="list-group list-group-flush">
                        {% for w,c in top_words[:5] %}<li class="list-group-item d-flex justify-content-between"><span>{{ w }}</span><span class="badge bg-primary">{{ c }}</span></li>{% endfor %}
                    </ul>
                </div>
                <div class="card mt-3">
                    <div class="card-header">😊 Top Emojis</div>
                    <ul class="list-group list-group-flush">
                        {% for e,c in top_emojis[:5] %}<li class="list-group-item d-flex justify-content-between"><span>{{ e }}</span><span class="badge bg-primary">{{ c }}</span></li>{% endfor %}
                    </ul>
                </div>
                <div class="card mt-3">
                    <div class="card-header">📣 Top Mentions</div>
                    <ul class="list-group list-group-flush">
                        {% for m,c in top_mentions[:5] %}<li class="list-group-item d-flex justify-content-between"><span>{{ m }}</span><span class="badge bg-primary">{{ c }}</span></li>{% endfor %}
                    </ul>
                </div>
            </div>
        </div>
    </div>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        const ctx = document.getElementById('activityChart').getContext('2d');
        new Chart(ctx, {
            type: 'line',
            data: {
                labels: {{ days|tojson }},
                datasets: [{
                    label: 'Messages',
                    data: {{ counts|tojson }},
                    borderColor: '#0d6efd',
                    tension: 0.1,
                    fill: false
                }]
            },
            options: { responsive: true, plugins: { legend: { display: false } } }
        });
    </script>
</body>
</html>
'''

HTML_CHATS = '''
<!DOCTYPE html>
<html>
<head><title>Chats</title>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark">
    <div class="container-fluid">
        <a class="navbar-brand" href="/">🤖 Selfbot</a>
        <div class="collapse navbar-collapse">
            <ul class="navbar-nav">
                <li class="nav-item"><a class="nav-link" href="/">Overview</a></li>
                <li class="nav-item"><a class="nav-link active" href="/chats">Chats</a></li>
                <li class="nav-item"><a class="nav-link" href="/users">Users</a></li>
                <li class="nav-item"><a class="nav-link" href="/enemies">Enemies</a></li>
                <li class="nav-item"><a class="nav-link" href="/warns">Warns</a></li>
                <li class="nav-item"><a class="nav-link" href="/mutes">Mutes</a></li>
                <li class="nav-item"><a class="nav-link" href="/settings">Settings</a></li>
            </ul>
        </div>
    </div>
</nav>
<div class="container mt-4">
    <h2>💬 Chats</h2>
    <table class="table table-striped">
        <thead><tr><th>Title</th><th>Type</th><th>Participants</th><th>Unread</th><th>Created</th></tr></thead>
        <tbody>
        {% for chat in chats %}
            <tr>
                <td>{{ chat.title }}</td>
                <td><span class="badge bg-secondary">{{ chat.type }}</span></td>
                <td>{{ chat.participants }}</td>
                <td>{{ chat.unread_count }}</td>
                <td>{{ chat.created or 'N/A' }}</td>
            </tr>
        {% else %}
            <tr><td colspan="5">No chats tracked.</td></tr>
        {% endfor %}
        </tbody>
    </table>
</div>
</body>
</html>
'''

HTML_USERS = '''
<!DOCTYPE html>
<html>
<head><title>Users</title>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark"> ... same nav ... </nav>
<div class="container mt-4">
    <h2>👥 Users</h2>
    <input class="form-control mb-3" id="searchInput" type="text" placeholder="Search by ID...">
    <table class="table table-striped" id="userTable">
        <thead><tr><th>ID</th><th>Messages</th><th>Chars</th><th>Words</th><th>Emojis</th><th>Mentions</th><th>Replies</th><th>Chats</th></tr></thead>
        <tbody>
        {% for u in users %}
            <tr>
                <td>{{ u.id }}</td>
                <td>{{ u.msgs }}</td>
                <td>{{ u.chars }}</td>
                <td>{{ u.words }}</td>
                <td>{{ u.emojis }}</td>
                <td>{{ u.mentions }}</td>
                <td>{{ u.replies }}</td>
                <td>{{ u.chats }}</td>
            </tr>
        {% else %}
            <tr><td colspan="8">No users.</td></tr>
        {% endfor %}
        </tbody>
    </table>
</div>
<script>
    document.getElementById('searchInput').addEventListener('keyup', function() {
        let filter = this.value.toLowerCase();
        let rows = document.querySelectorAll('#userTable tbody tr');
        rows.forEach(row => {
            let text = row.textContent.toLowerCase();
            row.style.display = text.includes(filter) ? '' : 'none';
        });
    });
</script>
</body>
</html>
'''

HTML_ENEMIES = '''
<!DOCTYPE html>
<html>
<head><title>Enemies</title>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body>
<nav class="navbar navbar-expand-lg navbar-dark bg-dark"> ... same nav ... </nav>
<div class="container mt-4">
    <h2>👿 Enemies</h2>
    <form method="post" class="row g-3 mb-4">
        <div class="col-md-3"><input name="chat_id" class="form-control" placeholder="Chat ID" required></div>
        <div class="col-md-3"><input name="user_id" class="form-control" placeholder="User ID" required></div>
        <div class="col-md-2"><input name="category" class="form-control" placeholder="Category (default/no)"></div>
        <div class="col-md-2"><input name="custom_text" class="form-control" placeholder="Custom text (optional)"></div>
        <div class="col-md-2"><button name="action" value="add" class="btn btn-success">Add</button></div>
    </form>
    <table class="table table-striped">
        <thead><tr><th>Chat ID</th><th>User ID</th><th>Category</th><th>Custom Text</th><th>Action</th></tr></thead>
        <tbody>
        {% for e in enemies %}
            <tr>
                <td>{{ e.chat_id }}</td>
                <td>{{ e.user_id }}</td>
                <td>{{ e.category }}</td>
                <td>{{ e.custom_text or '-' }}</td>
                <td>
                    <form method="post" style="display:inline;">
                        <input type="hidden" name="chat_id" value="{{ e.chat_id }}">
                        <input type="hidden" name="user_id" value="{{ e.user_id }}">
                        <button name="action" value="remove" class="btn btn-danger btn-sm">Remove</button>
                    </form>
                </td>
            </tr>
        {% else %}
            <tr><td colspan="5">No enemies.</td></tr>
        {% endfor %}
        </tbody>
    </table>
</div>
</body>
</html>
'''

HTML_WARNS = '''
<!DOCTYPE html>
<html>
<head><title>Warns</title>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body>
<nav> ... same ... </nav>
<div class="container mt-4">
    <h2>⚠️ Warns</h2>
    <form method="post" class="row g-3 mb-4">
        <div class="col-md-3"><input name="chat_id" class="form-control" placeholder="Chat ID" required></div>
        <div class="col-md-3"><input name="limit" class="form-control" placeholder="Limit" required></div>
        <div class="col-md-2"><button name="action" value="set_limit" class="btn btn-primary">Set Limit</button></div>
    </form>
    <form method="post" class="row g-3 mb-4">
        <div class="col-md-3"><input name="chat_id" class="form-control" placeholder="Chat ID" required></div>
        <div class="col-md-3"><input name="user_id" class="form-control" placeholder="User ID" required></div>
        <div class="col-md-2"><button name="action" value="clear_user" class="btn btn-warning">Clear User Warns</button></div>
    </form>
    <table class="table table-striped">
        <thead><tr><th>Chat ID</th><th>User ID</th><th>Reason</th><th>Limit</th></tr></thead>
        <tbody>
        {% for w in warns %}
            <tr>
                <td>{{ w.chat_id }}</td>
                <td>{{ w.user_id }}</td>
                <td>{{ w.reason }}</td>
                <td>{{ w.limit }}</td>
            </tr>
        {% else %}
            <tr><td colspan="4">No warns.</td></tr>
        {% endfor %}
        </tbody>
    </table>
</div>
</body>
</html>
'''

HTML_MUTES = '''
<!DOCTYPE html>
<html>
<head><title>Mutes</title>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body>
<nav> ... same ... </nav>
<div class="container mt-4">
    <h2>🔇 Mutes</h2>
    <form method="post" class="row g-3 mb-4">
        <div class="col-md-3"><input name="chat_id" class="form-control" placeholder="Chat ID" required></div>
        <div class="col-md-3"><input name="user_id" class="form-control" placeholder="User ID" required></div>
        <div class="col-md-2">
            <select name="mode" class="form-select">
                <option value="admin">Admin</option>
                <option value="manual">Manual</option>
            </select>
        </div>
        <div class="col-md-2"><button name="action" value="add" class="btn btn-success">Add</button></div>
    </form>
    <table class="table table-striped">
        <thead><tr><th>Chat ID</th><th>User ID</th><th>Mode</th><th>Action</th></tr></thead>
        <tbody>
        {% for m in mutes %}
            <tr>
                <td>{{ m.chat_id }}</td>
                <td>{{ m.user_id }}</td>
                <td><span class="badge bg-warning">{{ m.mode }}</span></td>
                <td>
                    <form method="post" style="display:inline;">
                        <input type="hidden" name="chat_id" value="{{ m.chat_id }}">
                        <input type="hidden" name="user_id" value="{{ m.user_id }}">
                        <button name="action" value="remove" class="btn btn-danger btn-sm">Remove</button>
                    </form>
                </td>
            </tr>
        {% else %}
            <tr><td colspan="4">No mutes.</td></tr>
        {% endfor %}
        </tbody>
    </table>
</div>
</body>
</html>
'''

HTML_SETTINGS = '''
<!DOCTYPE html>
<html>
<head><title>Settings</title>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css">
</head>
<body>
<nav> ... same ... </nav>
<div class="container mt-4">
    <h2>⚙️ Settings</h2>
    <form method="post" class="row g-3">
        {% for key, value in settings.items() %}
        <div class="col-md-4">
            <div class="form-check form-switch">
                <input class="form-check-input" type="checkbox" name="{{ key }}" id="{{ key }}" {% if value %}checked{% endif %}>
                <label class="form-check-label" for="{{ key }}">{{ key|replace('_',' ')|title }}</label>
            </div>
        </div>
        {% endfor %}
        <div class="col-12"><button type="submit" class="btn btn-primary">Save</button></div>
    </form>
</div>
</body>
</html>
'''

# The nav is repeated in each template; for brevity we include a comment. In practice you would use a base template.

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)