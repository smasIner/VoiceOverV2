from flask import Flask, render_template, request, redirect, url_for, flash, g, jsonify
import sqlite3
import os
import requests
import re
import html
from datetime import date

app = Flask(__name__)
app.secret_key = 'anime_voiceover_secret_key'
DATABASE = 'anime_voiceover.db'

KITSU_SEARCH_URL = "https://kitsu.io/api/edge/anime"
KITSU_EPISODES_URL = "https://kitsu.io/api/edge/anime/{anime_id}/episodes?page[offset]={offset}"
ANILIST_URL = "https://graphql.anilist.co"


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    if not os.path.exists(DATABASE):
        with app.app_context():
            db = get_db()
            with app.open_resource('schema.sql', mode='r') as f:
                db.cursor().executescript(f.read())
            db.commit()


init_db()

def parse_subtitle_file(file_content):
    content = file_content.decode('utf-8', errors='ignore')

    # srt regular expression
    subtitle_pattern = re.compile(
        r"(\d+)\s*\n"  # subtitle number
        r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\s*\n"  # time codes
        r"(.*?)(?=\n\s*\n|\n\s*\d+\s*\n|\Z)",  # text
        re.DOTALL
    )

    parsed_subtitles = []
    matches = subtitle_pattern.findall(content)

    for match in matches:
        _, start_time, end_time, phrase = match
        phrase = phrase.strip().replace('\n', ' ')  # remove newlines
        parsed_subtitles.append((start_time, end_time, phrase))

    return parsed_subtitles


def translate_text(text, source_lang="en", target_lang="ru"):
    try:
        response = requests.get(f"https://lingva.ml/api/v1/{source_lang}/{target_lang}/{text}")
        if response.status_code == 200:
            return response.json().get("translation", text)
    except Exception as e:
        print(f"Translation error: {e}")
    return f"[Translation of: {text}]"

# API Functions
def get_anime_from_kitsu(title):
    """Search for an anime by title on Kitsu API"""
    response = requests.get(KITSU_SEARCH_URL, params={"filter[text]": title})

    if response.status_code == 200 and response.json()["data"]:
        return response.json()["data"][0]  # Return first anime
    else:
        return None


def get_episodes_from_kitsu(anime_id):
    """Fetch all episodes for an anime from Kitsu API"""
    episodes = []
    offset = 0  # Start at the first page

    while True:
        response = requests.get(KITSU_EPISODES_URL.format(anime_id=anime_id, offset=offset))

        if response.status_code == 200:
            data = response.json()
            new_episodes = data["data"]

            # Add fetched episodes to the list
            episodes.extend([
                {
                    "number": ep["attributes"]["number"],
                    "title": ep["attributes"]["canonicalTitle"] or f"Episode {ep['attributes']['number']}",
                    "synopsis": ep["attributes"]["synopsis"],
                    "airdate": ep["attributes"]["airdate"] or date.today().isoformat()
                }
                for ep in new_episodes if ep["attributes"]["number"] is not None
            ])

            # If there's no next page, stop
            if "next" not in data["links"]:
                break

                # Move to the next page (Kitsu paginates by 10)
            offset += 10
        else:
            break

    return episodes


def get_anime_from_anilist(title):
    """Fetch anime details from AniList API"""
    query = """
    query ($search: String, $charPage: Int) {
      Media (search: $search, type: ANIME) {
        id
        title {
          romaji
          english
          native
        }
        description
        episodes
        coverImage {
          large
        }
        characters (perPage: 50, page: $charPage) { 
          pageInfo {
            hasNextPage
          }
          edges {
            node {
              id
              name {
                full
              }
              image {
                large
              }
              description
            }
            role
          }
        }
      }
    }
    """

    characters = []
    char_page = 1
    has_next_page = True
    anime_data = None

    while has_next_page:
        variables = {"search": title, "charPage": char_page}
        response = requests.post(ANILIST_URL, json={"query": query, "variables": variables})

        if response.status_code == 200 and "data" in response.json() and response.json()["data"]["Media"]:
            data = response.json()["data"]["Media"]

            if anime_data is None:
                anime_data = {
                    "id": data["id"],
                    "title": data["title"]["english"] or data["title"]["romaji"],
                    "description": html.unescape(data["description"]).replace("<br>", "").replace("\r\n", " ") if data[
                        "description"] else "",
                    "episodes": data["episodes"],
                    "coverImage": data["coverImage"]["large"],
                    "characters": []
                }

            for char in data["characters"]["edges"]:
                characters.append({
                    "id": char["node"]["id"],
                    "name": char["node"]["name"]["full"],
                    "image": char["node"]["image"]["large"],
                    "description": char["node"]["description"] if char["node"]["description"] else ""
                })

            has_next_page = data["characters"]["pageInfo"]["hasNextPage"]
            char_page += 1
        else:
            break

    if anime_data:
        anime_data["characters"] = characters
        return anime_data

    return None


@app.route('/')
def index():
    db = get_db()
    animes = db.execute('SELECT * FROM anime').fetchall()
    return render_template('index.html', animes=animes)


@app.route('/anime/add', methods=['POST'])
def add_anime():
    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        image_url = request.form['image_url'] or '/static/images/placeholder.jpg'

        db = get_db()
        db.execute('INSERT INTO anime (title, description, image_url) VALUES (?, ?, ?)',
                   [title, description, image_url])
        db.commit()
        flash('Anime added successfully!')
        return redirect(url_for('index'))

@app.route('/anime/edit/<int:id>', methods=['GET', 'POST'])
def edit_anime(id):
    db = get_db()

    # fetch the anime to edit based on the given `id`
    anime = db.execute('SELECT * FROM anime WHERE id = ?', (id,)).fetchone()

    if not anime:
        flash('Anime not found!', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        image_url = request.form['image_url'] or '/static/images/placeholder.jpg'  # Default image if not provided

        db.execute('UPDATE anime SET title = ?, description = ?, image_url = ? WHERE id = ?',
                   (title, description, image_url, id))
        db.commit()

        flash('Anime updated successfully!')
        return redirect(url_for('index'))

    # if it's a GET request, render the edit form with the current anime data
    return render_template('edit_anime.html', anime=anime)



@app.route('/anime/delete/<int:id>')
def delete_anime(id):
    db = get_db()
    db.execute('DELETE FROM anime WHERE id = ?', [id])
    db.commit()
    flash('Anime deleted successfully!')
    return redirect(url_for('index'))


@app.route('/anime/search', methods=['POST'])
def search_anime():
    title = request.form['search_title']

    # Search for anime on AniList
    anime_data = get_anime_from_anilist(title)

    if anime_data:
        # Search for episodes on Kitsu
        kitsu_anime = get_anime_from_kitsu(title)
        episodes = []

        if kitsu_anime:
            kitsu_id = kitsu_anime["id"]
            episodes = get_episodes_from_kitsu(kitsu_id)

        return render_template('anime_search_results.html', anime=anime_data, episodes=episodes)
    else:
        flash('Anime not found. Please try a different title.')
        return redirect(url_for('index'))


@app.route('/anime/import', methods=['POST'])
def import_anime():
    title = request.form['title']
    description = request.form['description']
    image_url = request.form['image_url']
    external_id = request.form['external_id']

    db = get_db()
    cursor = db.cursor()
    cursor.execute('INSERT INTO anime (title, description, image_url, external_id) VALUES (?, ?, ?, ?)',
                   [title, description, image_url, external_id])
    anime_id = cursor.lastrowid

    episode_count = int(request.form.get('episode_count', 0))
    for i in range(episode_count):
        if f'episode_title_{i}' in request.form:
            episode_title = request.form[f'episode_title_{i}']
            episode_number = request.form.get(f'episode_number_{i}', None)
            episode_synopsis = request.form.get(f'episode_synopsis_{i}', '')
            episode_date = request.form.get(f'episode_date_{i}', date.today().isoformat())

            db.execute('INSERT INTO episodes (anime_id, title, release_date, number, synopsis) VALUES (?, ?, ?, ?, ?)',
                       [anime_id, episode_title, episode_date, episode_number, episode_synopsis])

    character_count = int(request.form.get('character_count', 0))
    for i in range(character_count):
        if f'character_name_{i}' in request.form:
            character_name = request.form[f'character_name_{i}']
            character_image = request.form.get(f'character_image_{i}', '/static/images/placeholder.jpg')
            character_description = request.form.get(f'character_description_{i}', '')
            character_id = request.form.get(f'character_id_{i}', '')

            db.execute(
                'INSERT INTO characters (anime_id, name, description, image_url, external_id) VALUES (?, ?, ?, ?, ?)',
                [anime_id, character_name, character_description, character_image, character_id])

    db.commit()
    flash('Anime imported successfully with episodes and characters!')
    return redirect(url_for('episodes', anime_id=anime_id))


@app.route('/voice_actors')
def voice_actors():
    db = get_db()
    actors = db.execute('SELECT * FROM voice_actors').fetchall()
    return render_template('voice_actors.html', actors=actors)


@app.route('/voice_actor/add', methods=['GET', 'POST'])
def add_voice_actor():
    if request.method == 'POST':
        name = request.form['name']
        image_url = request.form['image_url'] or '/static/images/placeholder.jpg'

        db = get_db()
        db.execute('INSERT INTO voice_actors (name, image_url) VALUES (?, ?)', (name, image_url))
        db.commit()
        flash('Voice actor added successfully!')
        return redirect(url_for('voice_actors'))

    return render_template('add_voice_actor.html')




@app.route('/voice_actor/edit/<int:id>', methods=['GET', 'POST'])
def edit_voice_actor(id):
    db = get_db()

    if request.method == 'POST':
        name = request.form['name']
        image_url = request.form['image_url'] or '/static/images/placeholder.jpg'

        db.execute('UPDATE voice_actors SET name = ?, image_url = ? WHERE id = ?',
                   [name, image_url, id])
        db.commit()
        flash('Voice actor updated successfully!')
        return redirect(url_for('voice_actors'))

    # GET request
    voice_actor = db.execute('SELECT * FROM voice_actors WHERE id = ?', [id]).fetchone()
    return render_template('edit_voice_actor.html', actor=voice_actor)


@app.route('/voice_actor/delete/<int:id>')
def delete_voice_actor(id):
    db = get_db()
    db.execute('DELETE FROM voice_actors WHERE id = ?', [id])
    db.commit()
    flash('Voice actor deleted successfully!')
    return redirect(url_for('voice_actors'))


@app.route('/anime/<int:anime_id>/episodes')
def episodes(anime_id):
    db = get_db()
    anime = db.execute('SELECT * FROM anime WHERE id = ?', [anime_id]).fetchone()
    episodes = db.execute('SELECT * FROM episodes WHERE anime_id = ? ORDER BY number', [anime_id]).fetchall()
    return render_template('episodes.html', anime=anime, episodes=episodes)


@app.route('/episode/add', methods=['POST'])
def add_episode():
    if request.method == 'POST':
        anime_id = request.form['anime_id']
        title = request.form['title']
        release_date = request.form['release_date']
        number = request.form.get('number', None)
        synopsis = request.form.get('synopsis', '')

        db = get_db()
        db.execute('INSERT INTO episodes (anime_id, title, release_date, number, synopsis) VALUES (?, ?, ?, ?, ?)',
                   [anime_id, title, release_date, number, synopsis])
        db.commit()
        flash('Episode added successfully!')
        return redirect(url_for('episodes', anime_id=anime_id))


@app.route('/episode/edit/<int:id>', methods=['GET', 'POST'])
def edit_episode(id):
    db = get_db()
    episode = db.execute('SELECT * FROM episodes WHERE id = ?', [id]).fetchone()
    anime_id = episode['anime_id']
    if request.method == 'POST':
        title = request.form['title']
        release_date = request.form['release_date']
        number = request.form.get('number', None)
        synopsis = request.form.get('synopsis', '')

        db = get_db()
        episode = db.execute('SELECT anime_id FROM episodes WHERE id = ?', [id]).fetchone()
        anime_id = episode['anime_id']

        db.execute('UPDATE episodes SET title = ?, release_date = ?, number = ?, synopsis = ? WHERE id = ?',
                   [title, release_date, number, synopsis, id])
        db.commit()
        flash('Episode updated successfully!')
        return redirect(url_for('episodes', anime_id=anime_id))
    return render_template('edit_episode.html', episode=episode, anime_id=anime_id)


@app.route('/episode/delete/<int:id>')
def delete_episode(id):
    db = get_db()
    episode = db.execute('SELECT anime_id FROM episodes WHERE id = ?', [id]).fetchone()
    anime_id = episode['anime_id']

    db.execute('DELETE FROM episodes WHERE id = ?', [id])
    db.commit()
    flash('Episode deleted successfully!')
    return redirect(url_for('episodes', anime_id=anime_id))


@app.route('/anime/<int:anime_id>/characters')
def characters(anime_id):
    db = get_db()
    anime = db.execute('SELECT * FROM anime WHERE id = ?', [anime_id]).fetchone()
    characters = db.execute(
        'SELECT c.*, va.name as voice_actor_name FROM characters c LEFT JOIN character_voice_actors cva ON c.id = cva.character_id LEFT JOIN voice_actors va ON cva.voice_actor_id = va.id WHERE c.anime_id = ?',
        [anime_id]).fetchall()
    voice_actors = db.execute('SELECT * FROM voice_actors').fetchall()
    return render_template('characters.html', anime=anime, characters=characters, voice_actors=voice_actors)


# update the add_character route to handle both GET and POST requests
@app.route('/character/add/<int:anime_id>', methods=['GET', 'POST'])
def add_character(anime_id):
    db = get_db()
    anime = db.execute('SELECT * FROM anime WHERE id = ?', [anime_id]).fetchone()
    voice_actors = db.execute('SELECT * FROM voice_actors').fetchall()

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        image_url = request.form['image_url'] or '/static/images/placeholder.jpg'
        voice_actor_id = request.form.get('voice_actor_id')

        cursor = db.cursor()
        cursor.execute('INSERT INTO characters (anime_id, name, description, image_url) VALUES (?, ?, ?, ?)',
                       [anime_id, name, description, image_url])
        character_id = cursor.lastrowid

        if voice_actor_id:
            db.execute('INSERT INTO character_voice_actors (character_id, voice_actor_id) VALUES (?, ?)',
                       [character_id, voice_actor_id])

        db.commit()
        flash('Character added successfully!')
        return redirect(url_for('characters', anime_id=anime_id))

    # GET request - render the form
    return render_template('add_character.html', anime=anime, voice_actors=voice_actors)


# update the character edit route to handle both GET and POST
@app.route('/character/edit/<int:id>', methods=['GET', 'POST'])
def edit_character(id):
    db = get_db()
    character = db.execute('SELECT * FROM characters WHERE id = ?', [id]).fetchone()
    anime_id = character['anime_id']

    if request.method == 'POST':
        name = request.form['name']
        description = request.form['description']
        image_url = request.form['image_url'] or '/static/images/placeholder.jpg'
        voice_actor_id = request.form.get('voice_actor_id')

        db.execute('UPDATE characters SET name = ?, description = ?, image_url = ? WHERE id = ?',
                   [name, description, image_url, id])

        # update voice actor
        db.execute('DELETE FROM character_voice_actors WHERE character_id = ?', [id])
        if voice_actor_id:
            db.execute('INSERT INTO character_voice_actors (character_id, voice_actor_id) VALUES (?, ?)',
                       [id, voice_actor_id])

        db.commit()
        flash('Character updated successfully!')
        return redirect(url_for('characters', anime_id=anime_id))

    # for get respponse in edit form new page
    voice_actors = db.execute('SELECT * FROM voice_actors').fetchall()
    current_voice_actor = db.execute('''
        SELECT va.id FROM voice_actors va 
        JOIN character_voice_actors cva ON va.id = cva.voice_actor_id 
        WHERE cva.character_id = ?
    ''', [id]).fetchone()

    current_voice_actor_id = current_voice_actor['id'] if current_voice_actor else None

    return render_template('edit_character.html', character=character, voice_actors=voice_actors,
                           current_voice_actor_id=current_voice_actor_id, anime_id=anime_id)


@app.route('/character/delete/<int:id>')
def delete_character(id):
    db = get_db()
    character = db.execute('SELECT anime_id FROM characters WHERE id = ?', [id]).fetchone()
    anime_id = character['anime_id']

    db.execute('DELETE FROM characters WHERE id = ?', [id])
    db.commit()
    flash('Character deleted successfully!')
    return redirect(url_for('characters', anime_id=anime_id))


@app.route('/episode/<int:episode_id>')
def episode_detail(episode_id):
    db = get_db()
    episode = db.execute(
        'SELECT e.*, a.title as anime_title, a.id as anime_id FROM episodes e JOIN anime a ON e.anime_id = a.id WHERE e.id = ?',
        [episode_id]).fetchone()

    # get characters for this anime (for the assign character dropdown)
    all_characters = db.execute('SELECT * FROM characters WHERE anime_id = ?', [episode['anime_id']]).fetchall()

    # get characters participating in this episode
    participating_characters = db.execute('''
        SELECT c.*, va.name as voice_actor_name 
        FROM episode_characters ec
        JOIN characters c ON ec.character_id = c.id
        LEFT JOIN character_voice_actors cva ON c.id = cva.character_id
        LEFT JOIN voice_actors va ON cva.voice_actor_id = va.id
        WHERE ec.episode_id = ?
    ''', [episode_id]).fetchall()

    # get IDs of participating characters for filtering
    participating_character_ids = [char['id'] for char in participating_characters]

    # get subtitles for this episode
    subtitles = db.execute('''
        SELECT s.*, c.name as character_name, va.name as voice_actor_name 
        FROM subtitles s 
        LEFT JOIN characters c ON s.character_id = c.id 
        LEFT JOIN character_voice_actors cva ON c.id = cva.character_id 
        LEFT JOIN voice_actors va ON cva.voice_actor_id = va.id 
        WHERE s.episode_id = ?
        ORDER BY s.start_time
    ''', [episode_id]).fetchall()


    subtitle_count = len(subtitles)
    completed_count = len([s for s in subtitles if s['is_completed']])

    return render_template('episode.html',
                           episode=episode,
                           all_characters=all_characters,
                           participating_characters=participating_characters,
                           participating_character_ids=participating_character_ids,
                           subtitles=subtitles,
                           subtitle_count=subtitle_count,
                           completed_count=completed_count)


@app.route('/episode/<int:episode_id>/upload_subtitles', methods=['POST'])
def upload_subtitles(episode_id):
    if 'subtitle_file' not in request.files:
        flash('No file part')
        return redirect(url_for('episode_detail', episode_id=episode_id))

    file = request.files['subtitle_file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('episode_detail', episode_id=episode_id))

    language = request.form.get('language', 'en')

    if file:
        # read the file content
        file_content = file.read()

        # parse the SRT file
        parsed_subtitles = parse_subtitle_file(file_content)

        db = get_db()
        cursor = db.cursor()

        # clear existing subtitles for this episode
        db.execute('DELETE FROM subtitles WHERE episode_id = ?', [episode_id])

        # insert new subtitles
        for start_time, end_time, phrase in parsed_subtitles:
            if language == 'en':
                # English source, translate to Russian
                english_phrase = phrase
                russian_phrase = translate_text(phrase, 'en', 'ru')
            else:
                # no translation
                english_phrase = ''
                russian_phrase = phrase

            cursor.execute('''
                INSERT INTO subtitles (episode_id, start_time, end_time, english_phrase, russian_phrase, is_completed)
                VALUES (?, ?, ?, ?, ?, 0)
            ''', [episode_id, start_time, end_time, english_phrase, russian_phrase])

        # update subtitle count in episodes table
        db.execute('UPDATE episodes SET subtitle_count = ?, completed_subtitle_count = 0 WHERE id = ?',
                   [len(parsed_subtitles), episode_id])

        db.commit()
        flash(f'Successfully uploaded and processed {len(parsed_subtitles)} subtitles')

    return redirect(url_for('episode_detail', episode_id=episode_id))


@app.route('/subtitle/<int:subtitle_id>/assign_character', methods=['POST'])
def assign_character_to_subtitle(subtitle_id):
    character_id = request.form.get('character_id')

    db = get_db()
    subtitle = db.execute('SELECT episode_id FROM subtitles WHERE id = ?', [subtitle_id]).fetchone()
    episode_id = subtitle['episode_id']

    db.execute('UPDATE subtitles SET character_id = ? WHERE id = ?', [character_id, subtitle_id])
    db.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # If AJAX request, return JSON response
        character = db.execute(
            'SELECT c.name, va.name as voice_actor_name FROM characters c LEFT JOIN character_voice_actors cva ON c.id = cva.character_id LEFT JOIN voice_actors va ON cva.voice_actor_id = va.id WHERE c.id = ?',
            [character_id]).fetchone()
        return jsonify({
            'success': True,
            'character_name': character['name'],
            'voice_actor_name': character['voice_actor_name'] if character['voice_actor_name'] else 'None'
        })

    flash('Character assigned to subtitle')
    return redirect(url_for('episode_detail', episode_id=episode_id))


@app.route('/subtitle/<int:subtitle_id>/toggle_completion', methods=['POST'])
def toggle_subtitle_completion(subtitle_id):
    db = get_db()
    subtitle = db.execute('SELECT episode_id, is_completed FROM subtitles WHERE id = ?', [subtitle_id]).fetchone()
    episode_id = subtitle['episode_id']

    # Toggle completion status
    new_status = 1 if subtitle['is_completed'] == 0 else 0
    db.execute('UPDATE subtitles SET is_completed = ? WHERE id = ?', [new_status, subtitle_id])

    # Update completed count in episodes table
    completed_count = db.execute('SELECT COUNT(*) as count FROM subtitles WHERE episode_id = ? AND is_completed = 1',
                                 [episode_id]).fetchone()['count']
    db.execute('UPDATE episodes SET completed_subtitle_count = ? WHERE id = ?', [completed_count, episode_id])

    db.commit()

    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        # If AJAX request, return JSON response
        return jsonify({
            'success': True,
            'is_completed': new_status,
            'completed_count': completed_count
        })

    return redirect(url_for('episode_detail', episode_id=episode_id))


@app.route('/episode/<int:episode_id>/assign_character', methods=['POST'])
def assign_character(episode_id):
    if request.method == 'POST':
        character_id = request.form['character_id']
        total_lines = request.form['total_lines']

        db = get_db()
        # check if character is already assigned to this episode
        existing = db.execute('SELECT * FROM episode_characters WHERE episode_id = ? AND character_id = ?',
                              [episode_id, character_id]).fetchone()

        if existing:
            db.execute('UPDATE episode_characters SET total_lines = ? WHERE episode_id = ? AND character_id = ?',
                       [total_lines, episode_id, character_id])
        else:
            db.execute(
                'INSERT INTO episode_characters (episode_id, character_id, total_lines, completed_lines) VALUES (?, ?, ?, 0)',
                [episode_id, character_id, total_lines, 0])

        db.commit()
        flash('Character assigned successfully!')
        return redirect(url_for('episode_detail', episode_id=episode_id))


@app.route('/episode/<int:episode_id>/update_lines/<int:character_id>/<action>')
def update_lines(episode_id, character_id, action):
    db = get_db()
    character_episode = db.execute('SELECT * FROM episode_characters WHERE episode_id = ? AND character_id = ?',
                                   [episode_id, character_id]).fetchone()

    completed_lines = character_episode['completed_lines']
    total_lines = character_episode['total_lines']

    if action == 'increment' and completed_lines < total_lines:
        completed_lines += 1
    elif action == 'decrement' and completed_lines > 0:
        completed_lines -= 1

    db.execute('UPDATE episode_characters SET completed_lines = ? WHERE episode_id = ? AND character_id = ?',
               [completed_lines, episode_id, character_id])
    db.commit()

    return redirect(url_for('episode_detail', episode_id=episode_id))


@app.route('/episode/<int:episode_id>/remove_character/<int:character_id>')
def remove_character_from_episode(episode_id, character_id):
    db = get_db()
    db.execute('DELETE FROM episode_characters WHERE episode_id = ? AND character_id = ?',
               [episode_id, character_id])
    db.commit()
    flash('Character removed from episode!')
    return redirect(url_for('episode_detail', episode_id=episode_id))


@app.route('/episode/<int:episode_id>/add_character', methods=['POST'])
def add_character_to_episode(episode_id):
    character_id = request.form.get('character_id')

    if not character_id:
        flash('Please select a character')
        return redirect(url_for('episode_detail', episode_id=episode_id))

    db = get_db()

    # check if character is already in the episode
    existing = db.execute('SELECT * FROM episode_characters WHERE episode_id = ? AND character_id = ?',
                          [episode_id, character_id]).fetchone()

    if not existing:
        db.execute('INSERT INTO episode_characters (episode_id, character_id) VALUES (?, ?)',
                   [episode_id, character_id])
        db.commit()
        flash('Character added to episode')
    else:
        flash('Character is already in this episode')

    return redirect(url_for('episode_detail', episode_id=episode_id))


if __name__ == '__main__':
    app.run(debug=True)

