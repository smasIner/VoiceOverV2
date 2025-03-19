DROP TABLE IF EXISTS character_voice_actors;
DROP TABLE IF EXISTS episode_characters;
DROP TABLE IF EXISTS characters;
DROP TABLE IF EXISTS episodes;
DROP TABLE IF EXISTS voice_actors;
DROP TABLE IF EXISTS anime;
DROP TABLE IF EXISTS subtitles;
CREATE TABLE anime (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    image_url TEXT,
    external_id TEXT
);
CREATE TABLE voice_actors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    image_url TEXT
);
CREATE TABLE episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    release_date TEXT NOT NULL,
    number INTEGER,
    synopsis TEXT,
    FOREIGN KEY (anime_id) REFERENCES anime (id) ON DELETE CASCADE
);
CREATE TABLE characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    anime_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    image_url TEXT,
    external_id TEXT,
    FOREIGN KEY (anime_id) REFERENCES anime (id) ON DELETE CASCADE
);
CREATE TABLE episode_characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    character_id INTEGER NOT NULL,
    total_lines INTEGER NOT NULL DEFAULT 0,
    completed_lines INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (episode_id) REFERENCES episodes (id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE
);
CREATE TABLE character_voice_actors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    voice_actor_id INTEGER NOT NULL,
    FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE CASCADE,
    FOREIGN KEY (voice_actor_id) REFERENCES voice_actors (id) ON DELETE CASCADE
);
CREATE TABLE subtitles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    episode_id INTEGER NOT NULL,
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    english_phrase TEXT,
    russian_phrase TEXT NOT NULL,
    character_id INTEGER,
    is_completed BOOLEAN DEFAULT 0,
    FOREIGN KEY (episode_id) REFERENCES episodes (id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters (id) ON DELETE SET NULL
);

ALTER TABLE episodes ADD COLUMN subtitle_count INTEGER DEFAULT 0;
ALTER TABLE episodes ADD COLUMN completed_subtitle_count INTEGER DEFAULT 0;