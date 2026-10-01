"""One project's card: what it is, what has been noted about it, what it amounts
to, and a searchable table of everything assigned to it. A project is a chip like a task or a meeting, and
this is what opens when one is clicked - on Projects, and in the archive, where
retiring a project hides none of what it held.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

import daycard
import db
from palette import LEGACY, chip_css, style_block, wash

#: The kinds a project can hold, each with what finishing one is called: a
#: paper is read, the rest are completed.
KINDS = ((db.TASK, "Tasks", "completed"), (db.MEETING, "Meetings", "completed"),
         (db.PAPER, "Papers", "read"))

#: What finishing one of each kind is called, for a row's status.
FINISHED = {kind: verb for kind, _label, verb in KINDS}

#: The table's filters, one pill each.
SHOWN = ("Open tasks", "Completed tasks", "Meetings", "Papers")

#: A row's fill in the table: finished ones green, open ones red.
DONE_FILL = f"background-color: {wash(LEGACY['green'])}"
OPEN_FILL = f"background-color: {wash(LEGACY['red'])}"


def _rename(prefix: str, project_id: int) -> None:
    db.rename_project(project_id, st.session_state[f"{prefix}name:{project_id}"])


def _set_notes(prefix: str, project_id: int) -> None:
    db.set_project_notes(
        project_id, st.session_state[f"{prefix}about:{project_id}"])


def _set_dates(prefix: str, project_id: int) -> None:
    db.set_project_dates(project_id,
                         st.session_state[f"{prefix}start:{project_id}"],
                         st.session_state[f"{prefix}end:{project_id}"])


def _tally(items: pd.DataFrame) -> None:
    """How much is attached, by kind and by whether it is finished."""
    finished = items[items["done_on"].notna()]["kind"].value_counts()
    open_now = items[items["done_on"].isna()]["kind"].value_counts()
    st.markdown(" ".join(
        f":gray-badge[{label}: {int(open_now.get(kind, 0))} open, "
        f"{int(finished.get(kind, 0))} {verb}]" for kind, label, verb in KINDS))


def _belongings(project, items: pd.DataFrame, prefix: str):
    """Everything assigned to this project, in a table that stays one height
    however much there is. The box above it narrows the table, and picking a row
    gives that item back for the caller to open."""
    if items.empty:
        st.caption("Nothing assigned yet.")
        return None

    # The search box takes what the filters beside it leave. They say which
    # rows to show, all of them to begin with: tasks split on whether they are
    # finished, meetings and papers come whole.
    with st.container(horizontal=True, vertical_alignment="center"):
        term = st.text_input(
            "Search", key=f"{prefix}search:{project.id}",
            label_visibility="collapsed", width="stretch",
            placeholder="Search this project's tasks, meetings and papers…")
        showing = st.pills("Show", SHOWN, selection_mode="multi",
                           default=SHOWN, key=f"{prefix}show:{project.id}",
                           label_visibility="collapsed", width="content")
    shown = {name: name in showing for name in SHOWN}
    task = items["kind"] == db.TASK
    finished = items["done_on"].notna()
    found = items[(task & ~finished & shown["Open tasks"])
                  | (task & finished & shown["Completed tasks"])
                  | ((items["kind"] == db.MEETING) & shown["Meetings"])
                  | ((items["kind"] == db.PAPER) & shown["Papers"])]
    if term:
        found = found[found["haystack"].str.contains(term.strip().lower(),
                                                     regex=False, na=False)]
    if found.empty:
        st.caption("Nothing matching.")
        return None

    table = pd.DataFrame({
        "ID": found["code"],
        "Kind": found["kind"].str.capitalize(),
        "Item": found["title"],
        "Day": found["on_day"],
        "Status": [FINISHED[kind].capitalize() if pd.notna(done) else "Open"
                   for kind, done in zip(found["kind"], found["done_on"])],
        "Notes": found["notes"].fillna(""),
    })
    picked = st.dataframe(
        table.style.apply(lambda row: [OPEN_FILL if row["Status"] == "Open"
                                       else DONE_FILL] * len(row), axis=1),
        hide_index=True, width="stretch", height=200,
        key=f"{prefix}hits:{project.id}", on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Kind": st.column_config.TextColumn(width="small"),
            "Item": st.column_config.TextColumn(width="large"),
            "Day": st.column_config.DateColumn(format="ddd DD MMM YYYY"),
            "Status": st.column_config.TextColumn(width="small"),
            "Notes": st.column_config.TextColumn(width="medium"),
        })

    # A selection outlives the dialog it opened, and every project keeps its
    # own, so opening on "something is selected" would reopen a stale row the
    # moment any dialog closed. Open only when this table's pick changes.
    rows = picked.selection.rows
    # One row, as a namedtuple: a dialog is a fragment and is handed its
    # arguments back on every rerun, and a Series does not survive that.
    chosen = next(found.iloc[[rows[0]]].itertuples()) if rows else None
    seen = f"{prefix}seen:{project.id}"
    if (chosen.id if chosen else None) == st.session_state.get(seen):
        return None
    st.session_state[seen] = chosen.id if chosen else None
    return chosen


def _actions(project, prefix: str) -> None:
    """What can be done with the whole project. An archived one offers only the
    way back; a live one asks before either of the two that cannot be undone."""
    if project.archived:
        if st.button("Put it back", icon=":material/unarchive:",
                     key=f"{prefix}restore:{project.id}",
                     help="With a colour of its own again"):
            db.restore_project(project.id)
            st.rerun(scope="app")
        return

    row = st.columns(2)
    # Archiving takes the colour off everything assigned to it, so it asks
    # first, the way calling off a meeting does.
    with row[0].popover("Archive this project", icon=":material/archive:",
                        width="stretch"):
        st.markdown(f"**Archive {project.name}?**")
        st.caption("It and everything assigned to it turn grey, and its colour "
                   "goes back into circulation. It moves to the Settings page, "
                   "and you can restore it from there.")
        if st.button("Yes, archive it", type="primary",
                     key=f"{prefix}archive:{project.id}"):
            db.archive_project(project.id)
            st.rerun(scope="app")
    # Deleting cannot be undone, so it asks first the way archiving does.
    with row[1].popover("Delete this project", icon=":material/delete:",
                        width="stretch"):
        st.markdown(f"**Delete {project.name}?**")
        st.caption("Everything assigned to it is kept and simply shows as "
                   "having no project, and its colour goes back into "
                   "circulation. Archive it instead to keep the grouping. "
                   "This cannot be undone.")
        if st.button("Yes, delete it", type="primary",
                     key=f"{prefix}drop:{project.id}"):
            db.delete_project(project.id)
            st.rerun(scope="app")


@st.dialog("Project", width="large")
def _open(project, prefix: str) -> None:
    """Everything about one project, laid out as an item's own card is: the name
    on its own, then the dates, then what it holds."""
    if project.archived:
        st.markdown(":gray-badge[Archived]")
    # The ID to the right, centred on the box rather than on box and label.
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("Project", value=project.name,
                      key=f"{prefix}name:{project.id}",
                      on_change=_rename, args=(prefix, project.id))
        with st.container(height=40, width="content", border=False,
                          vertical_alignment="center"):
            st.markdown(f":gray-badge[{project.code}]")

    # Either end may be left open, so both boxes start empty.
    span = st.columns(2)
    for column, field, label in ((span[0], "start_on", "From"),
                                 (span[1], "end_on", "To")):
        stamp = getattr(project, field)
        column.date_input(label, value=None if pd.isna(stamp) else stamp.date(),
                          key=f"{prefix}{field.split('_')[0]}:{project.id}",
                          format="DD/MM/YYYY", on_change=_set_dates,
                          args=(prefix, project.id))

    # A text area, as a task's notes are: that is what the bullets attach
    # themselves to, and what there is to say about a project is rarely one line.
    st.text_area("Notes", key=f"{prefix}about:{project.id}", height=130,
                 value="" if pd.isna(project.description) else project.description,
                 placeholder="Add a note…",
                 on_change=_set_notes, args=(prefix, project.id))

    items = db.project_items(project.id)
    _tally(items)
    picked = _belongings(project, items, prefix)
    if picked is not None:
        # One dialog cannot open another, so the page is left to do it: this
        # rerun closes the card, and the page finds the item waiting. Which
        # card it came from is noted down with it, so it can come back.
        st.session_state["project_item"] = picked
        st.session_state["project_waiting"] = project.id
        st.rerun(scope="app")

    _actions(project, prefix)


def open_project(project_id: int, prefix: str) -> None:
    """One project's card, opened from somewhere that has only its id."""
    projects = db.projects()
    _open(next(projects[projects["id"] == project_id].itertuples()), prefix)


def chips(projects: pd.DataFrame, prefix: str, names: list[str]) -> None:
    """One project to a row in its own colour, each opening its card, and the
    item a card's table picked opened here once the card has closed. Closing
    that item puts its card back, so the table it was picked from is where you
    are left."""
    picked = st.session_state.pop("project_item", None)

    rules = []
    for project in projects.itertuples():
        key = f"{prefix}:{project.id}"
        rules.append(chip_css(key, project.colour))
        if st.button(project.name, key=key, width="stretch"):
            _open(project, prefix)
    if rules:
        st.html(style_block(rules))

    if picked is not None:
        daycard.open_item(picked, f"{prefix}:", names)
    elif (waiting := st.session_state.pop("project_waiting", None)) is not None:
        # The item is gone from the screen - dismissed, deleted, or taken off
        # its day - so the card that opened it comes back. Only a rerun of the
        # whole page reaches here, and that is the one thing that closes a
        # dialog. Read the project again: its card may have been edited.
        back = projects[projects["id"] == waiting]
        if not back.empty:
            _open(next(back.itertuples()), prefix)
