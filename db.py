"""Every read and write the planner makes: one SQLite file and the helpers the
pages call. Dates go in as ISO strings and come back as pandas datetimes."""

from __future__ import annotations

import os
import sqlite3
import tempfile
from contextlib import contextmanager
from datetime import date, time
from pathlib import Path

import pandas as pd
import streamlit as st
from sqlalchemy import inspect, text

from palette import ARCHIVED_COLOUR, as_hex, next_colour

def _local_database() -> str:
    """Where the SQLite file lives. The packaged app sets PLANNER_DB to point
    outside the bundle; a checkout keeps it beside this file. Absolute either
    way, since an app launched from the Dock starts in "/"."""
    override = os.environ.get("PLANNER_DB", "").strip()
    if override:
        path = Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite:///{path}"
    return f"sqlite:///{Path(__file__).resolve().parent / 'planner.db'}"


LOCAL_URL = _local_database()

#: The file itself, for backing it up.
DB_PATH = Path(LOCAL_URL.removeprefix("sqlite:///"))

_DATE_COLUMNS = ("day", "done_on", "on_day", "created_on", "week_start",
                 "start_on", "end_on")

#: What a row in `tasks` is. They share a table, and differ in what hangs off
#: them: milestones for a task, notes for the other two.
TASK = "task"
MEETING = "meeting"
PAPER = "paper"

#: Renamed columns: old name to new.
_RENAMED_COLUMNS = {"days": {"focus_hours": "unfocused_hours",
                             "unfocused_hours": "break_hours"},
                    "tasks": {"minutes": "notes"}}

#: Columns added per table, applied on connect. Fixed here in the source, never
#: taken from user input.
_ADDED_COLUMNS = {
    "tasks": {"project_id": "INTEGER", "description": "TEXT",
              "kind": "TEXT NOT NULL DEFAULT 'task'", "notes": "TEXT",
              "goals": "TEXT", "actions": "TEXT",
              "start_time": "TEXT", "end_time": "TEXT", "tags": "TEXT",
              "link": "TEXT"},
    "days": {"holiday": "INTEGER NOT NULL DEFAULT 0"},
    "milestones": {"done_on": "DATE"},
    "projects": {"archived": "INTEGER NOT NULL DEFAULT 0",
                 "start_on": "DATE", "end_on": "DATE"},
}

#: Every item query joins a row to its project; they share the wording.
_FROM_TASKS = " FROM tasks t LEFT JOIN projects p ON p.id = t.project_id "

#: Milestone totals for a task, as two columns, in one statement.
_MILESTONE_COUNTS = (
    "(SELECT COUNT(*) FROM milestones m WHERE m.task_id = t.id) AS milestones, "
    "(SELECT COUNT(*) FROM milestones m "
    "  WHERE m.task_id = t.id AND m.done_on IS NOT NULL) "
    "AS milestones_done")

#: Everything an item's card and editor read, whatever kind the item is. One
#: list, so a task, meeting or paper arrives in the same shape wherever it is
#: read and the editor can open any of them.
_ITEM_COLUMNS = ("SELECT t.id, t.title, t.day, t.done_on, t.kind, t.description, "
                 "t.goals, t.notes, t.actions, t.tags, t.link, "
                 "t.start_time, t.end_time, "
                 "COALESCE(t.done_on, t.day) AS on_day, "
                 "p.name AS project, p.colour AS colour, " + _MILESTONE_COUNTS)

#: What a project's search box matches on, lowered here so the box can filter
#: its own rows without going back to the database.
_HAYSTACK = (", LOWER(t.title || ' ' || COALESCE(t.description, '') || ' ' "
             "|| COALESCE(t.notes, '') || ' ' || COALESCE(t.tags, '')) AS haystack")

#: The opening of every query that returns items.
_ITEMS = _ITEM_COLUMNS + _FROM_TASKS

_SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT,
    colour      TEXT NOT NULL,
    archived    INTEGER NOT NULL DEFAULT 0,
    start_on    DATE,
    end_on      DATE
);
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    day        DATE,
    done_on    DATE,
    created_on  DATE NOT NULL,
    project_id  INTEGER,
    description TEXT,
    kind        TEXT NOT NULL DEFAULT 'task',
    goals       TEXT,
    notes       TEXT,
    actions     TEXT,
    start_time  TEXT,
    end_time    TEXT,
    tags        TEXT,
    link        TEXT
);
CREATE TABLE IF NOT EXISTS milestones (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    title   TEXT NOT NULL,
    done_on DATE
);
-- Every task query counts its milestones with a correlated subquery. Without
-- this, each one scans the whole table. No semicolons in here: _create_tables
-- splits the schema on them.
CREATE INDEX IF NOT EXISTS milestones_by_task ON milestones(task_id);
CREATE TABLE IF NOT EXISTS days (
    day         DATE PRIMARY KEY,
    start_time  TEXT,
    end_time    TEXT,
    break_hours REAL,
    comment     TEXT,
    holiday     INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS reviews (
    week_start DATE NOT NULL,
    question   TEXT NOT NULL,
    answer     TEXT,
    PRIMARY KEY (week_start, question)
);
CREATE TABLE IF NOT EXISTS settings (
    name  TEXT PRIMARY KEY,
    value TEXT
);
"""


#: Tables that have changed name, old to new.
_RENAMED_TABLES = {"steps": "milestones"}


def _rename_tables(connection) -> None:
    """Take a database written before a table was renamed to the name it goes by
    now. This runs before the schema: CREATE TABLE IF NOT EXISTS would otherwise
    make an empty table under the new name and leave every row behind under the
    old one. The index goes too - SQLite carries it over under its old name, and
    the schema makes it again under the new one. Idempotent."""
    present = set(inspect(connection.engine).get_table_names())
    for old_name, new_name in _RENAMED_TABLES.items():
        if old_name in present and new_name not in present:
            with connection.session as session:
                session.execute(
                    text(f"ALTER TABLE {old_name} RENAME TO {new_name}"))
                session.execute(text(f"DROP INDEX IF EXISTS {old_name}_by_task"))
                session.commit()


#: Everything deciding what the database should look like. _create_tables takes
#: it only as a cache key: Streamlit keys on the function's own source, so a
#: session reloaded under a new migration would never run it.
_SHAPE = str((_SCHEMA, _RENAMED_TABLES, _RENAMED_COLUMNS, _ADDED_COLUMNS))


@st.cache_resource(show_spinner=False)
def _create_tables(_connection, shape: str) -> None:
    """Create anything missing, once per session and per `shape`. The connection
    is underscored so Streamlit caches on the call rather than trying to hash
    it; `shape` is unused here and is the cache key itself."""
    _rename_tables(_connection)
    with _connection.session as session:
        for statement in _SCHEMA.strip().split(";"):
            if statement.strip():
                session.execute(text(statement))
        session.commit()
    _catch_up(_connection)


def _catch_up(connection) -> None:
    """Bring an older database up to the current schema. Renames run before
    additions so a renamed column is not re-added empty. Idempotent."""
    def columns(table: str) -> set[str]:
        return {column["name"]
                for column in inspect(connection.engine).get_columns(table)}

    for table, renames in _RENAMED_COLUMNS.items():
        for old_name, new_name in renames.items():
            present = columns(table)
            if old_name in present and new_name not in present:
                with connection.session as session:
                    session.execute(text(f"ALTER TABLE {table} RENAME COLUMN "
                                         f"{old_name} TO {new_name}"))
                    session.commit()

    for table, wanted in _ADDED_COLUMNS.items():
        present = columns(table)
        missing = [(name, kind) for name, kind in wanted.items()
                   if name not in present]
        if missing:
            with connection.session as session:
                for name, kind in missing:
                    session.execute(
                        text(f"ALTER TABLE {table} ADD COLUMN {name} {kind}"))
                session.commit()

    if "is_meeting" in columns("tasks"):
        with connection.session as session:
            session.execute(text("UPDATE tasks SET kind = :meeting "
                                 "WHERE is_meeting = 1 AND kind = :task"),
                            {"meeting": MEETING, "task": TASK})
            session.execute(text("ALTER TABLE tasks DROP COLUMN is_meeting"))
            session.commit()

    # A milestone was ticked or not; now it is ticked on a day. Which day is
    # nowhere on record, so the task's own is the closest thing to it.
    if "done" in columns("milestones"):
        with connection.session as session:
            session.execute(text(
                "UPDATE milestones SET done_on = COALESCE("
                "  (SELECT t.done_on FROM tasks t WHERE t.id = task_id),"
                "  (SELECT t.day FROM tasks t WHERE t.id = task_id),"
                "  DATE('now')) WHERE done = 1 AND done_on IS NULL"))
            session.execute(text("ALTER TABLE milestones DROP COLUMN done"))
            session.commit()

    _unique_colours(connection)


def _unique_colours(connection) -> None:
    """Give every live project a hex colour of its own, oldest keeping it on a
    tie. Archived projects are skipped: they share one grey."""
    with connection.session as session:
        rows = session.execute(
            text("SELECT id, colour FROM projects WHERE archived = 0 "
                 "ORDER BY id")).all()
        used: list[str] = []
        for project_id, colour in rows:
            wanted = as_hex(colour)
            if wanted in used:
                wanted = next_colour(used)
            used.append(wanted)
            if wanted != colour:
                session.execute(
                    text("UPDATE projects SET colour = :colour WHERE id = :id"),
                    {"id": project_id, "colour": wanted})
        session.commit()


def _conn():
    """The connection (``st.connection`` caches it), with its tables in place."""
    conn = st.connection("planner", type="sql", url=LOCAL_URL)
    _create_tables(conn, _SHAPE)
    return conn


def snapshot() -> bytes:
    """The whole database as the bytes of a file. Taken through SQLite's backup
    API rather than read off disk, so a write in progress cannot tear the copy.
    Runs off the Streamlit thread, so it uses sqlite3 rather than the session."""
    source, target = sqlite3.connect(DB_PATH), sqlite3.connect(":memory:")
    try:
        source.backup(target)
        return target.serialize()
    finally:
        source.close()
        target.close()


#: What a file has to contain before it is treated as a Planner backup.
_TABLES = ("tasks", "milestones", "days", "projects", "reviews")


@contextmanager
def _uploaded(data: bytes):
    """An uploaded history on disk, checked before anything is written with it:
    a copy that failed halfway would leave the live database in pieces."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as handle:
        handle.write(data)
        path = handle.name
    try:
        connection = sqlite3.connect(path)
        try:
            sound = connection.execute("PRAGMA integrity_check").fetchone()
            found = {row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'")}
        except sqlite3.DatabaseError as problem:
            raise ValueError(f"That file is not a database ({problem}).") from problem
        finally:
            connection.close()
        if not sound or sound[0] != "ok":
            raise ValueError("That history is damaged and cannot be read.")
        missing = [name for name in _TABLES if name not in found]
        if missing:
            raise ValueError("Not a Planner history: no " + ", ".join(missing))
        yield path
    finally:
        os.unlink(path)
        # An older history may predate a column, so let the migrations run again.
        _create_tables.clear()


def restore(data: bytes) -> None:
    """Replace everything with an uploaded history. Written through SQLite's
    backup API rather than copied over the file, so the connection the app
    already holds sees the new contents instead of a file swapped beneath it."""
    with _uploaded(data) as path:
        source, target = sqlite3.connect(path), sqlite3.connect(DB_PATH)
        try:
            source.backup(target)
        finally:
            source.close()
            target.close()
    settings.clear()


#: A task, meeting or paper is the same one if it is of the same kind, under the
#: same title, on the same day. Ids cannot say: two histories number their own.
_SAME_ITEM = ("t.kind = b.kind AND t.title = b.title "
              "AND IFNULL(t.day, '') = IFNULL(b.day, '')")

#: Added on a merge, in order: a task needs its project, a milestone its task.
_MERGES = (
    ("projects", """
        INSERT INTO projects (name, description, colour, archived)
        SELECT b.name, b.description, b.colour, b.archived FROM backup.projects b
        WHERE NOT EXISTS (SELECT 1 FROM main.projects p WHERE p.name = b.name)"""),
    ("days", """
        INSERT INTO days (day, start_time, end_time, break_hours, comment, holiday)
        SELECT b.day, b.start_time, b.end_time, b.break_hours, b.comment, b.holiday
        FROM backup.days b
        WHERE NOT EXISTS (SELECT 1 FROM main.days d WHERE d.day = b.day)"""),
    ("settings", """
        INSERT INTO settings (name, value)
        SELECT b.name, b.value FROM backup.settings b
        WHERE NOT EXISTS (SELECT 1 FROM main.settings s WHERE s.name = b.name)"""),
    ("reviews", """
        INSERT INTO reviews (week_start, question, answer)
        SELECT b.week_start, b.question, b.answer FROM backup.reviews b
        WHERE NOT EXISTS (SELECT 1 FROM main.reviews r
                          WHERE r.week_start = b.week_start
                            AND r.question = b.question)"""),
    ("tasks", f"""
        INSERT INTO tasks (title, day, done_on, created_on, project_id, description,
                           kind, goals, notes, actions, start_time, end_time)
        SELECT b.title, b.day, b.done_on, b.created_on,
               (SELECT p.id FROM main.projects p JOIN backup.projects bp
                 ON bp.name = p.name WHERE bp.id = b.project_id),
               b.description, b.kind, b.goals, b.notes, b.actions,
               b.start_time, b.end_time
        FROM backup.tasks b
        WHERE NOT EXISTS (SELECT 1 FROM main.tasks t WHERE {_SAME_ITEM})"""),
    ("milestones", f"""
        INSERT INTO milestones (task_id, title, done_on)
        SELECT (SELECT t.id FROM main.tasks t WHERE {_SAME_ITEM} LIMIT 1),
               s.title, s.done_on
        FROM backup.milestones s JOIN backup.tasks b ON b.id = s.task_id
        WHERE EXISTS (SELECT 1 FROM main.tasks t WHERE {_SAME_ITEM})
          AND NOT EXISTS (
              SELECT 1 FROM main.milestones ms
                JOIN main.tasks t ON t.id = ms.task_id
              WHERE {_SAME_ITEM} AND ms.title = s.title)"""),
)


def merge(data: bytes) -> dict[str, int]:
    """Add whatever an uploaded history holds that is not here already, and
    report how much of each. Nothing here is changed or removed: an item already
    present is left exactly as it is."""
    added = {}
    with _uploaded(data) as path:
        connection = sqlite3.connect(DB_PATH)
        try:
            connection.execute("ATTACH DATABASE ? AS backup", (path,))
            # A history saved before settings existed has none to offer.
            present = {row[0] for row in connection.execute(
                "SELECT name FROM backup.sqlite_master WHERE type = 'table'")}
            with connection:                      # one transaction, or none of it
                for table, statement in _MERGES:
                    if table not in present:
                        continue
                    added[table] = connection.execute(statement).rowcount
            connection.execute("DETACH DATABASE backup")
        finally:
            connection.close()
    settings.clear()
    return {table: count for table, count in added.items() if count}


def _read(sql: str, **params) -> pd.DataFrame:
    """A query straight to the database - never cached, so an edit shows at once."""
    with _conn().session as session:
        frame = pd.read_sql(text(sql), session.connection(), params=params)
    for column in frame.columns.intersection(_DATE_COLUMNS):
        frame[column] = pd.to_datetime(frame[column], errors="coerce")
    return frame


def _write(sql: str, **params) -> None:
    with _conn().session as session:
        session.execute(text(sql), params)
        session.commit()


def _insert(sql: str, **params) -> int:
    """An INSERT, giving back the id of the row it made, so whatever else was
    filled in can be set on it with the ordinary setters."""
    with _conn().session as session:
        row = session.execute(text(sql), params)
        session.commit()
        return row.lastrowid


# --- Tasks ------------------------------------------------------------------

def item(task_id: int):
    """One task, meeting or paper, in the shape every listing gives. A day card
    opens the card of a finished milestone's task, which may be on no day at all
    and so in none of the lists that card holds."""
    return next(_read(_ITEMS + "WHERE t.id = :id", id=task_id).itertuples(), None)


#: Items grouped by project, in the order the projects page lists them, with
#: those under no project last.
_BY_PROJECT = "p.id IS NULL, p.archived, p.id"


def open_tasks() -> pd.DataFrame:
    """Every task still to do, grouped by project, those already given a day
    last within their project, then newest first. Meetings and papers live on
    their own pages and are not here."""
    return _read(_ITEMS
                 + "WHERE t.done_on IS NULL AND t.kind = :kind "
                   "ORDER BY " + _BY_PROJECT + ", t.day IS NOT NULL, t.id DESC",
                 kind=TASK)


def add_task(title: str) -> int | None:
    """Create an open task with nothing else set yet, and give back its id. A
    blank title makes nothing."""
    if title := title.strip():
        return _insert("INSERT INTO tasks (title, created_on) "
                       "VALUES (:title, :created_on)",
                       title=title, created_on=date.today().isoformat())
    return None


def rename_task(task_id: int, title: str) -> None:
    if title := title.strip():
        _write("UPDATE tasks SET title = :title WHERE id = :id",
               id=task_id, title=title)


def set_task_notes(task_id: int, notes: str) -> None:
    """Set or clear a task's notes, which live in the column that held its
    description. Bulleted like every other written box. Blank means none."""
    _write("UPDATE tasks SET description = :notes WHERE id = :id",
           id=task_id, notes=as_bullets(notes) or None)


def set_task_day(task_id: int, day: date | None) -> None:
    """Move an item to `day`, carrying its `done_on`: filing is by
    COALESCE(done_on, day), so leaving that behind would pin the item to its old
    day or hide the move entirely.

    A day gone by counts as done, the way a past meeting counts as held. That is
    also what keeps the move: `close_past_days` takes an unfinished task off a
    day that has passed, so a backdated one would be swept straight back onto
    the list. Clearing the day leaves a finished one where it was finished,
    since nothing here un-finishes work."""
    _write("UPDATE tasks SET day = :day, done_on = "
           "CASE WHEN :day IS NULL THEN done_on "
           "WHEN done_on IS NOT NULL OR :day < :today THEN :day "
           "ELSE NULL END "
           "WHERE id = :id",
           id=task_id, day=day.isoformat() if day else None,
           today=date.today().isoformat())


def set_task_project(task_id: int, project: str | None) -> None:
    _write("UPDATE tasks SET project_id = "
           "(SELECT id FROM projects WHERE name = :project) WHERE id = :id",
           id=task_id, project=project)


def _add_dated(title: str, day: date | None, kind: str) -> int | None:
    """Create a meeting or a paper: a titled thing of its kind, on a day or not
    yet on one. Gives back its id, or None for a blank title."""
    if title := title.strip():
        return _insert("INSERT INTO tasks (title, day, created_on, kind) "
                       "VALUES (:title, :day, :created_on, :kind)",
                       title=title, day=day.isoformat() if day else None,
                       kind=kind, created_on=date.today().isoformat())
    return None


def _of_kind(kind: str, first: date, last: date) -> pd.DataFrame:
    """One kind filed against a day in the range, earliest first: under the day
    it was finished, or the day it is set for. Undated ones are not here.
    Within a day, those with a start time come first in time order (HH:MM
    sorts as text), then the rest as they were added."""
    return _read(_ITEMS
                 + "WHERE t.kind = :kind "
                 "AND COALESCE(t.done_on, t.day) BETWEEN :first AND :last "
                 "ORDER BY COALESCE(t.done_on, t.day), "
                 "t.start_time IS NULL, t.start_time, t.id",
                 kind=kind, first=first.isoformat(), last=last.isoformat())


def add_paper(title: str, day: date | None = None) -> int | None:
    """Add a paper to read, usually with no day: give it one when you decide
    when to read it, and it joins that day's checklist then."""
    return _add_dated(title, day, PAPER)


def unread_papers() -> pd.DataFrame:
    """Papers still to read, grouped by project."""
    return _read(_ITEMS
                 + "WHERE t.done_on IS NULL AND t.kind = :kind "
                   "ORDER BY " + _BY_PROJECT + ", t.id DESC", kind=PAPER)


def papers_read(query: str = "") -> pd.DataFrame:
    """Papers read, newest first, narrowed to those whose title, notes, tags or
    project contain `query`. LOWER on both sides makes the match
    case-insensitive."""
    return _read(_ITEMS
                 + "WHERE t.kind = :kind AND t.done_on IS NOT NULL "
                 "AND (LOWER(t.title) LIKE :like "
                 "OR LOWER(COALESCE(t.notes, '')) LIKE :like "
                 "OR LOWER(COALESCE(t.tags, '')) LIKE :like "
                 "OR LOWER(COALESCE(p.name, '')) LIKE :like) "
                 "ORDER BY t.done_on DESC, t.id DESC",
                 kind=PAPER, like=f"%{query.strip().lower()}%")


def meetings_matching(query: str) -> pd.DataFrame:
    """Meetings whose title, write-up or project contain `query`, newest
    first. LOWER on both sides makes the match case-insensitive."""
    return _read(_ITEMS
                 + "WHERE t.kind = :kind AND ("
                 "LOWER(t.title) LIKE :like "
                 "OR LOWER(COALESCE(t.goals, '')) LIKE :like "
                 "OR LOWER(COALESCE(t.notes, '')) LIKE :like "
                 "OR LOWER(COALESCE(t.actions, '')) LIKE :like "
                 "OR LOWER(COALESCE(p.name, '')) LIKE :like) "
                 "ORDER BY COALESCE(t.done_on, t.day) DESC, t.id DESC",
                 kind=MEETING, like=f"%{query.strip().lower()}%")


def move_meeting(meeting_id: int, day: date) -> None:
    """Move a meeting, carrying its done_on: filing is by COALESCE(done_on,
    day), so leaving it behind would pin the meeting to its old day. A day gone
    by counts as held, a day to come does not."""
    _write("UPDATE tasks SET day = :day, done_on = :done_on "
           "WHERE id = :id AND kind = :kind",
           id=meeting_id, kind=MEETING, day=day.isoformat(),
           done_on=day.isoformat() if day < date.today() else None)


def add_meeting(title: str, day: date | None) -> int | None:
    """Create a meeting, normally on a day. Kept off the open task list; made on
    the Meetings page."""
    return _add_dated(title, day, MEETING)


#: The written sections. A meeting uses all three, a paper only notes. Named
#: here so `set_task_note` never takes a column name from user input.
NOTE_FIELDS = ("goals", "notes", "actions")


def set_meeting_times(task_id: int, start: time | None,
                      end: time | None) -> None:
    """When a meeting runs from and to. Both are optional: plenty of meetings
    are just a day in the diary."""
    _write("UPDATE tasks SET start_time = :start, end_time = :end WHERE id = :id",
           id=task_id, start=start.strftime("%H:%M") if start else None,
           end=end.strftime("%H:%M") if end else None)


def set_task_tags(task_id: int, tags: str) -> str:
    """Keywords for a paper, kept as one comma-separated line so a search can
    match them with the rest of its text. Blanks and repeats are dropped, and
    the tidied line is returned so the box it came from can show it."""
    cleaned = ", ".join(dict.fromkeys(
        word.strip() for word in tags.split(",") if word.strip()))
    _write("UPDATE tasks SET tags = :tags WHERE id = :id",
           tags=cleaned or None, id=task_id)
    return cleaned


def set_task_link(task_id: int, link: str) -> str:
    """Where a paper can be read. An address pasted without a scheme gets one,
    or the link would be read as a page of this app. Blank clears it; the
    tidied address comes back so the box it came from can show it."""
    cleaned = link.strip()
    scheme, _, rest = cleaned.partition("://")
    if cleaned and not (rest and scheme.isalpha()):
        cleaned = "https://" + cleaned
    _write("UPDATE tasks SET link = :link WHERE id = :id",
           link=cleaned or None, id=task_id)
    return cleaned


#: What a bullet is marked with: a point at the top level, a dash below it.
POINT, DASH = "\u2022 ", "- "


def as_bullets(text: str) -> str:
    """Every line as a bullet. The page starts the next one when Enter is
    pressed, but the text is tidied here too, so a line typed without one - or
    pasted in - still comes back as a bullet. The spaces a line opens with are
    kept: they are what makes it a sub-bullet of the one above, and what
    decides which mark it carries."""
    kept = []
    for line in (text or "").splitlines():
        body = line.strip()
        if not body.strip("\u2022- ").strip():
            continue
        indent = line[:len(line) - len(line.lstrip(" "))]
        if body.startswith((POINT, DASH)):
            body = body[2:]
        kept.append(indent + (DASH if indent else POINT) + body)
    return "\n".join(kept)


def set_task_note(task_id: int, field: str, text: str) -> None:
    """Set one written section of a meeting or paper. Blank means none."""
    if field not in NOTE_FIELDS:
        raise ValueError(f"not a note field: {field!r}")
    _write(f"UPDATE tasks SET {field} = :text WHERE id = :id",
           id=task_id, text=as_bullets(text) or None)


def close_past_days() -> None:
    """A meeting whose day is over has happened, so it settles onto that day. A
    task or paper has not: it was set for a day that has gone, so it comes off
    that day and goes back on the list, still to do. Idempotent, so it can run
    on every rerun."""
    today = date.today().isoformat()
    _write("UPDATE tasks SET done_on = day WHERE kind = :meeting "
           "AND done_on IS NULL AND day IS NOT NULL AND day < :today",
           meeting=MEETING, today=today)
    _write("UPDATE tasks SET day = NULL WHERE kind IN (:task, :paper) "
           "AND done_on IS NULL AND day IS NOT NULL AND day < :today",
           task=TASK, paper=PAPER, today=today)


def meetings_in(first: date, last: date) -> pd.DataFrame:
    """Meetings filed against a day in the range, earliest first.

    Filed the same way tasks are: under the day it was finished once it is done,
    otherwise the day it is set for. A meeting with no day yet is not here.
    """
    return _of_kind(MEETING, first, last)


def delete_task(task_id: int) -> None:
    """Remove a task and the milestones under it."""
    with _conn().session as session:
        session.execute(text("DELETE FROM milestones WHERE task_id = :id"),
                        {"id": task_id})
        session.execute(text("DELETE FROM tasks WHERE id = :id"), {"id": task_id})
        session.commit()


# --- Projects ---------------------------------------------------------------

def project_items(project_id: int) -> pd.DataFrame:
    """Everything assigned to one project - tasks, meetings and papers - open
    ones first, each with the `haystack` its search box filters on."""
    return _read(_ITEM_COLUMNS + _HAYSTACK + _FROM_TASKS
                 + "WHERE t.project_id = :id "
                 "ORDER BY t.done_on IS NOT NULL, t.id DESC", id=project_id)


def projects() -> pd.DataFrame:
    """Every project, live ones first. Archived ones stay so anything assigned
    to them still shows a name; they are grey and sorted last."""
    return _read("SELECT id, name, description, colour, archived, start_on, "
                 "end_on FROM projects ORDER BY archived, id")


def set_project_dates(project_id: int, start: date | None,
                      end: date | None) -> None:
    """When a project runs from and to. Either may be left open."""
    _write("UPDATE projects SET start_on = :start, end_on = :end WHERE id = :id",
           start=start.isoformat() if start else None,
           end=end.isoformat() if end else None, id=project_id)


def archive_project(project_id: int) -> None:
    """Retire a project, freeing its colour. Its tasks and papers keep it and
    turn grey with it."""
    _write("UPDATE projects SET archived = 1, colour = :grey WHERE id = :id",
           id=project_id, grey=ARCHIVED_COLOUR)


def restore_project(project_id: int) -> None:
    """Bring a project back, on whatever colour is free now."""
    with _conn().session as session:
        used = [row[0] for row in session.execute(
            text("SELECT colour FROM projects WHERE archived = 0"))]
        session.execute(
            text("UPDATE projects SET archived = 0, colour = :colour "
                 "WHERE id = :id"),
            {"id": project_id, "colour": next_colour(used)})
        session.commit()


def add_project(name: str) -> int | None:
    """Create a project, giving it the next colour no other project holds, and
    give back its id. A blank name makes nothing."""
    if not (name := name.strip()):
        return None
    with _conn().session as session:
        used = [row[0] for row in
                session.execute(text("SELECT colour FROM projects"))]
        row = session.execute(
            text("INSERT INTO projects (name, description, colour) "
                 "VALUES (:name, NULL, :colour)"),
            {"name": name, "colour": next_colour(used)})
        session.commit()
        return row.lastrowid


def rename_project(project_id: int, name: str) -> None:
    if name := name.strip():
        _write("UPDATE projects SET name = :name WHERE id = :id",
               id=project_id, name=name)


def set_project_notes(project_id: int, notes: str) -> None:
    """Set or clear a project's notes, which live in the column that held its
    description. Bulleted like every other written box. Blank means none."""
    _write("UPDATE projects SET description = :notes WHERE id = :id",
           id=project_id, notes=as_bullets(notes) or None)


def delete_project(project_id: int) -> None:
    """Remove a project. Its tasks are released, not deleted: they keep their
    history and simply show as having no project."""
    with _conn().session as session:
        session.execute(text("UPDATE tasks SET project_id = NULL "
                             "WHERE project_id = :id"), {"id": project_id})
        session.execute(text("DELETE FROM projects WHERE id = :id"),
                        {"id": project_id})
        session.commit()


# --- Items by day -----------------------------------------------------------

def items_in(first: date, last: date) -> pd.DataFrame:
    """Every kind of item filed against a day in the range, as `on_day`: a
    finished one under the day it was done, an open one under the day it is set
    for. A day's card shows them together, so they are read together."""
    return _read(_ITEMS
                 + "WHERE COALESCE(t.done_on, t.day) BETWEEN :first AND :last "
                 "ORDER BY t.id",
                 first=first.isoformat(), last=last.isoformat())


def set_task_done(task_id: int, day: date | None) -> None:
    """Tick a task off on `day`, or untick it when `day` is None. Finishing it
    finishes any milestone still open, under the same day; unticking leaves them
    finished, since nothing here un-finishes work."""
    _write("UPDATE tasks SET done_on = :done_on WHERE id = :id",
           id=task_id, done_on=day.isoformat() if day else None)
    if day:
        _write("UPDATE milestones SET done_on = :done_on "
               "WHERE task_id = :id AND done_on IS NULL",
               id=task_id, done_on=day.isoformat())


# --- Milestones --------------------------------------------------------------

#: Being done is having a day. `done` is handed back alongside so that every
#: list, tally and strike-through can ask the plain question. `extra` adds a
#: column to those, for the one caller that needs more.
_MILESTONE = ("SELECT s.id, s.task_id, s.title, s.done_on, "
              "s.done_on IS NOT NULL AS done{extra} FROM milestones s ")


def _milestones(sql: str, extra: str = "", **params) -> pd.DataFrame:
    frame = _read(_MILESTONE.format(extra=extra) + sql, **params)
    frame["done"] = frame["done"].astype(bool)
    return frame


def open_milestones() -> pd.DataFrame:
    """Every milestone of every open task, in one query; the task list groups
    them. Asking per task would be a round trip each, on every rerun."""
    return _milestones("JOIN tasks t ON t.id = s.task_id "
                       "WHERE t.done_on IS NULL AND t.kind = :kind "
                       "ORDER BY s.task_id, s.id", kind=TASK)


def task_milestones(task_id: int) -> pd.DataFrame:
    """One task's milestones, read fresh. The editor opens as a dialog and is
    handed the same frame back on every rerun, so it asks again rather than
    showing the list as it stood when it opened."""
    return _milestones("WHERE s.task_id = :task_id ORDER BY s.id",
                       task_id=task_id)


def milestones_in(first: date, last: date) -> pd.DataFrame:
    """Every milestone of every task filed against a day in the range, and every
    one ticked off inside it - a milestone is finished on its own day, and its
    task may sit on another or on none at all. The task's name and colour come
    too: a day card shows a finished milestone as the task it belongs to."""
    return _milestones(
        "JOIN tasks t ON t.id = s.task_id "
        "LEFT JOIN projects p ON p.id = t.project_id "
        "WHERE COALESCE(t.done_on, t.day) BETWEEN :first AND :last "
        "   OR s.done_on BETWEEN :first AND :last "
        "ORDER BY s.task_id, s.id",
        extra=", t.title AS task, p.colour AS colour",
        first=first.isoformat(), last=last.isoformat())


def add_milestone(task_id: int, title: str) -> None:
    """Add a milestone to a task. It never changes the task's own state."""
    if title := title.strip():
        _write("INSERT INTO milestones (task_id, title) "
               "VALUES (:task_id, :title)", task_id=task_id, title=title)


def rename_milestone(milestone_id: int, title: str) -> None:
    """Retitle a milestone. A blank title leaves it as it was."""
    if title := title.strip():
        _write("UPDATE milestones SET title = :title WHERE id = :id",
               id=milestone_id, title=title)


def delete_milestone(milestone_id: int) -> None:
    _write("DELETE FROM milestones WHERE id = :id", id=milestone_id)


def set_milestone_done(milestone_id: int, day: date | None) -> None:
    """Tick one milestone off on `day`, or untick it when `day` is None. Never
    touches the task's own state: the task stays open and stays where it is."""
    _write("UPDATE milestones SET done_on = :done_on WHERE id = :id",
           id=milestone_id, done_on=day.isoformat() if day else None)


# --- Days -------------------------------------------------------------------

def days_in(first: date, last: date) -> pd.DataFrame:
    return _read("SELECT day, start_time, end_time, break_hours, comment, holiday "
                 "FROM days "
                 "WHERE day BETWEEN :first AND :last ORDER BY day",
                 first=first.isoformat(), last=last.isoformat())


def save_day(day: date, start: time | None, end: time | None,
             break_hours: float | None, comment: str | None,
             holiday: bool = False) -> None:
    """Upsert one day's record."""
    _write("INSERT INTO days (day, start_time, end_time, break_hours, comment, "
           "holiday) VALUES (:day, :start_time, :end_time, :break_hours, "
           ":comment, :holiday) "
           "ON CONFLICT (day) DO UPDATE SET start_time = :start_time, "
           "end_time = :end_time, break_hours = :break_hours, "
           "comment = :comment, holiday = :holiday",
           day=day.isoformat(), break_hours=break_hours,
           comment=as_bullets(comment) or None, holiday=int(bool(holiday)),
           start_time=start.strftime("%H:%M") if start else None,
           end_time=end.strftime("%H:%M") if end else None)


# --- Weekly review ----------------------------------------------------------

def recorded_weeks() -> list[date]:
    """The Monday of every week with anything in it, newest first: a day filled
    in, a task finished, or a review answered. `weekday 0` lands on the Sunday
    that ends the week, so six days back from it is the Monday that starts it."""
    frame = _read(
        "SELECT DISTINCT DATE(day, 'weekday 0', '-6 days') AS week FROM days "
        "UNION SELECT DISTINCT DATE(done_on, 'weekday 0', '-6 days') FROM tasks "
        "  WHERE done_on IS NOT NULL "
        "UNION SELECT DISTINCT week_start FROM reviews "
        "ORDER BY week DESC")
    return [date.fromisoformat(week) for week in frame["week"] if week]


#: Asked at the end of each week. Reword them freely; answers already saved keep
#: the wording they were asked under, since the question is their key.
REVIEW_QUESTIONS = [
    "What went well?",
    "What did not go so well?",
    "What blocked me?",
    "What did I learn this week?",
]


# --- Settings ---------------------------------------------------------------

@st.cache_data(show_spinner=False)
def settings() -> dict[str, str]:
    """Every setting saved, by name. Kept in the database so a backup carries
    them. Cached, as the hours arithmetic reads them for every day it counts;
    anything that writes them clears it."""
    frame = _read("SELECT name, value FROM settings")
    return dict(zip(frame["name"], frame["value"]))


def save_setting(name: str, value) -> None:
    _write("INSERT INTO settings (name, value) VALUES (:name, :value) "
           "ON CONFLICT (name) DO UPDATE SET value = :value",
           name=name, value=str(value))
    settings.clear()


def review(week_start: date) -> dict[str, str]:
    """The answers already given for a week, keyed by question."""
    frame = _read("SELECT question, answer FROM reviews WHERE week_start = :week",
                  week=week_start.isoformat())
    return dict(zip(frame["question"], frame["answer"].fillna("")))


def save_review(week_start: date, answers: dict[str, str]) -> None:
    with _conn().session as session:
        for question, answer in answers.items():
            session.execute(
                text("INSERT INTO reviews (week_start, question, answer) "
                     "VALUES (:week, :question, :answer) ON CONFLICT "
                     "(week_start, question) DO UPDATE SET answer = :answer"),
                {"week": week_start.isoformat(), "question": question,
                 "answer": as_bullets(answer) or None})
        session.commit()
