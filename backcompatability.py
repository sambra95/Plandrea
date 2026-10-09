"""Everything that brings a history written by an older version of the app up
to the shape the current one reads, and to where it looks for it. Each step
looks for the old shape before it touches anything, so all of it is
idempotent: it runs on every connect, again after a restore, and on the copy of
a history being merged in.

Nothing here imports db, which calls into it. The values written below are the
ones the old shapes stood for, so they are spelled out rather than borrowed."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from sqlalchemy import inspect, text

#: What the app was called before it was Plandrea, and what its database file
#: was named after it.
OLD_NAME = "Planner"
OLD_DATABASE = "planner.db"

#: Tables that have changed name, old to new.
RENAMED_TABLES = {"steps": "milestones"}

#: Renamed columns: old name to new.
RENAMED_COLUMNS = {"days": {"focus_hours": "unfocused_hours",
                            "unfocused_hours": "break_hours"},
                   "tasks": {"minutes": "notes"}}

#: A meeting was written up under three boxes; now it has one, Notes. Each old
#: box becomes a heading in it, in the order they were shown, with what was
#: under it as sub-bullets.
_MEETING_SECTIONS = (("goals", "Goals"), ("notes", "Notes"),
                     ("actions", "Action points"))

#: The columns that went into Notes, and so are dropped once they have.
_FOLDED = ("goals", "actions")


def _columns(connection, table: str) -> set[str]:
    return {column["name"]
            for column in inspect(connection.engine).get_columns(table)}


def rename_tables(connection) -> None:
    """Take a database written before a table was renamed to the name it goes by
    now. This runs before the schema: CREATE TABLE IF NOT EXISTS would otherwise
    make an empty table under the new name and leave every row behind under the
    old one. The index goes too - SQLite carries it over under its old name, and
    the schema makes it again under the new one."""
    present = set(inspect(connection.engine).get_table_names())
    for old_name, new_name in RENAMED_TABLES.items():
        if old_name in present and new_name not in present:
            with connection.session as session:
                session.execute(
                    text(f"ALTER TABLE {old_name} RENAME TO {new_name}"))
                session.execute(text(f"DROP INDEX IF EXISTS {old_name}_by_task"))
                session.commit()


def rename_columns(connection) -> None:
    """Give a column its new name. Runs before columns are added, so a renamed
    one is not re-added empty."""
    for table, renames in RENAMED_COLUMNS.items():
        for old_name, new_name in renames.items():
            present = _columns(connection, table)
            if old_name in present and new_name not in present:
                with connection.session as session:
                    session.execute(text(f"ALTER TABLE {table} RENAME COLUMN "
                                         f"{old_name} TO {new_name}"))
                    session.commit()


def upgrade(connection) -> None:
    """Rewrite whatever is still in an old shape. Runs once every column the
    current schema wants is in place."""
    if "is_meeting" in _columns(connection, "tasks"):
        with connection.session as session:
            session.execute(text("UPDATE tasks SET kind = 'meeting' "
                                 "WHERE is_meeting = 1 AND kind = 'task'"))
            session.execute(text("ALTER TABLE tasks DROP COLUMN is_meeting"))
            session.commit()

    # A milestone was ticked or not; now it is ticked on a day. Which day is
    # nowhere on record, so the task's own is the closest thing to it.
    if "done" in _columns(connection, "milestones"):
        with connection.session as session:
            session.execute(text(
                "UPDATE milestones SET done_on = COALESCE("
                "  (SELECT t.done_on FROM tasks t WHERE t.id = task_id),"
                "  (SELECT t.day FROM tasks t WHERE t.id = task_id),"
                "  DATE('now')) WHERE done = 1 AND done_on IS NULL"))
            session.execute(text("ALTER TABLE milestones DROP COLUMN done"))
            session.commit()

    present = _columns(connection, "tasks")
    if any(name in present for name in _FOLDED):
        with connection.session as session:
            rows = session.execute(text(_folding_query(present, "main"))).all()
            for statement, params in _fold_meeting_notes(rows, present, "main"):
                session.execute(text(statement), params)
            session.commit()


def upgrade_backup(connection: sqlite3.Connection,
                   coded: tuple[str, ...]) -> None:
    """The same for a history attached as `backup` to be merged in. It is a copy
    made for the merge, so changing it alters nothing of yours. `coded` are the
    tables whose rows carry a code, which a history older still has no column
    for."""
    def columns(table: str) -> set[str]:
        return {row[1] for row in connection.execute(
            f"PRAGMA backup.table_info({table})")}

    for table in coded:
        if "code" not in columns(table):
            connection.execute(f"ALTER TABLE backup.{table} ADD COLUMN code TEXT")

    present = columns("tasks")
    if any(name in present for name in _FOLDED):
        rows = connection.execute(_folding_query(present, "backup")).fetchall()
        for statement, params in _fold_meeting_notes(rows, present, "backup"):
            connection.execute(statement, params)
        connection.commit()


def _folding_query(present: set[str], schema: str) -> str:
    """Every row with something under a box that has gone, and what was in each
    box. A history may have one of the old columns without the other."""
    picked = ", ".join(name if name in present else f"NULL AS {name}"
                       for name, _ in _MEETING_SECTIONS)
    written = " OR ".join(f"TRIM(COALESCE({name}, '')) <> ''"
                          for name in _FOLDED if name in present)
    return f"SELECT id, {picked} FROM {schema}.tasks WHERE {written}"


def _fold_meeting_notes(rows, present: set[str], schema: str):
    """The statements that put each row's boxes into its notes, then drop the
    columns that held them. Named parameters, which both SQLAlchemy and sqlite3
    take."""
    for task_id, *boxes in rows:
        yield (f"UPDATE {schema}.tasks SET notes = :notes WHERE id = :id",
               {"id": task_id, "notes": combined_notes(*boxes)})
    for name in _FOLDED:
        if name in present:
            yield f"ALTER TABLE {schema}.tasks DROP COLUMN {name}", {}


def combined_notes(*boxes: str | None) -> str | None:
    """A meeting's three boxes as the one it has now: each that was written in
    becomes a heading bullet, its own lines indented one step beneath it. Lines
    come out marked as `db.as_bullets` would mark them, so the first edit does
    not reshuffle them."""
    lines = []
    for (_, heading), box in zip(_MEETING_SECTIONS, boxes):
        written = [line for line in (box or "").splitlines()
                   if line.strip().strip("•- ")]
        if not written:
            continue
        lines.append(f"• {heading}")
        for line in written:
            indent = "  " + line[:len(line) - len(line.lstrip(" "))]
            body = line.strip()
            if body.startswith(("• ", "- ")):
                body = body[2:]
            lines.append(f"{indent}- {body}")
    return "\n".join(lines) or None


def move_database(old: Path, new: Path) -> None:
    """A database still under the name it had before the app was renamed, moved
    to the one it has now, SQLite's side files with it. Nothing moves if there is
    already a database at the new name: that one is in use."""
    if not old.is_file() or new.exists():
        return
    for suffix in ("", "-journal", "-wal", "-shm"):
        side = old.with_name(old.name + suffix)
        if side.exists():
            side.rename(new.with_name(new.name + suffix))


def move_support_folder(parent: Path, name: str, database: str) -> None:
    """The packaged app's folder, from <parent>/Planner to <parent>/<name>, and
    the database in it to `database`. The whole folder goes, so the copies a
    migration left beside the database go with it. Runs before the new folder
    is made, or there would always be one in the way."""
    old, new = parent / OLD_NAME, parent / name
    if old.is_dir() and not new.exists():
        old.rename(new)
    move_database(new / OLD_DATABASE, new / database)
