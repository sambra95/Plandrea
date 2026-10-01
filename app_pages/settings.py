"""Settings: a search of everything, the hours a week owes, the projects
retired, and the history itself. The hours are kept in the history, so a
backup carries them too. A week is opened and reviewed on My Week, which any
of them can be picked on."""

from datetime import date, time

import pandas as pd
import streamlit as st

import daycard
import db
import projectcard
from palette import NO_PROJECT
from worktime import (clock, field, is_holiday, monday_of, totals,
                      week_hours, week_records)

#: The project card's filters, and one for each kind only a search finds.
SHOWN = projectcard.SHOWN + ("Projects", "Day notes", "Reviews")

#: What each kind of match is called in the results.
KIND_NAMES = {db.TASK: "Task", db.MEETING: "Meeting", db.PAPER: "Paper",
              "project": "Project", "day": "Day", "review": "Review"}


def _average(clocks: list[time]) -> str:
    """The mean of some clock times, as HH:MM, or a dash for none."""
    if not clocks:
        return "–"
    minutes = round(sum(c.hour * 60 + c.minute for c in clocks) / len(clocks))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _excerpt(body, query: str, around: int = 50) -> str:
    """The part of `body` around the first match, or its start if the match was
    in the name or ID."""
    if pd.isna(body):
        return ""
    body = " ".join(str(body).split())
    at = body.lower().find(query.lower())
    if at < 0:
        return body[:2 * around] + ("…" if len(body) > 2 * around else "")
    start, end = max(0, at - around), at + len(query) + around
    return (("…" if start else "") + body[start:end]
            + ("…" if end < len(body) else ""))


st.markdown("**Search**")
# The search box takes what the filters beside it leave, as on a project card.
with st.container(horizontal=True, vertical_alignment="center"):
    query = st.text_input("Search everything", key="everything_search",
                          label_visibility="collapsed", width="stretch",
                          placeholder="Search every task, meeting, paper, "
                                      "project, day note and review…")
    showing = st.pills("Show", SHOWN, selection_mode="multi", default=SHOWN,
                       key="everything_show", label_visibility="collapsed",
                       width="content")
if query.strip():
    found = db.search(query)
    shown = {name: name in showing for name in SHOWN}
    task = found["kind"] == db.TASK
    finished = found["done_on"].notna()
    found = found[(task & ~finished & shown["Open tasks"])
                  | (task & finished & shown["Completed tasks"])
                  | ((found["kind"] == db.MEETING) & shown["Meetings"])
                  | ((found["kind"] == db.PAPER) & shown["Papers"])
                  | ((found["kind"] == "project") & shown["Projects"])
                  | ((found["kind"] == "day") & shown["Day notes"])
                  | ((found["kind"] == "review") & shown["Reviews"])]
    if found.empty:
        st.caption("Nothing matching.")
    else:
        picked = st.dataframe(
            pd.DataFrame({"ID": found["code"].fillna(""),
                          "Kind": found["kind"].map(KIND_NAMES),
                          "Name": found["title"],
                          "Day": found["on_day"],
                          "Match": [_excerpt(body, query.strip())
                                    for body in found["body"]]}),
            hide_index=True, width="stretch", height=280, key="everything_hits",
            on_select="rerun", selection_mode="single-row",
            column_config={
                "Kind": st.column_config.TextColumn(width="small"),
                "Name": st.column_config.TextColumn(width="medium"),
                "Day": st.column_config.DateColumn(format="ddd DD MMM YYYY"),
                "Match": st.column_config.TextColumn(width="large"),
            })
        st.caption(f"{len(found)} matching · pick a task, meeting, paper or "
                   "project to open it")

        # The selection outlives the card it opened, so open only when the
        # pick changes, or the card comes back the moment it is closed.
        rows = picked.selection.rows
        chosen = found.iloc[rows[0]] if rows else None
        pick = (None if chosen is None or pd.isna(chosen["ref"])
                else (chosen["kind"], int(chosen["ref"])))
        if pick != st.session_state.get("everything_seen"):
            st.session_state["everything_seen"] = pick
            if pick and pick[0] == "project":
                projectcard.open_project(pick[1], "search")
            elif pick:
                projects = db.projects()
                daycard.open_item(db.item(pick[1]), "search:",
                                  [NO_PROJECT] + list(projects["name"]))

st.divider()
st.markdown("**Work week**")

st.number_input("Hours a week", min_value=0.0, max_value=168.0, step=0.5,
                value=week_hours(), key="week_hours",
                on_change=lambda: db.save_setting(
                    "week_hours", st.session_state["week_hours"]))

# Every week with anything in it up to this one, counted as My Week counts it:
# a blank weekday as an ordinary day. The averages take only days whose times
# were filled in, since a blank one would just pull them towards the default.
today = date.today()
weeks = [week for week in db.recorded_weeks() if week <= monday_of(today)]
if weeks:
    days = db.days_in(weeks[-1], today)
    saved = {row["day"].date(): row for _, row in days.iterrows()}
    balance = sum(totals(week_records(week, saved))[2] for week in weeks)
    worked = [record for record in saved.values() if not is_holiday(record)]
    starts = [c for r in worked if (c := clock(field(r, "start_time")))]
    ends = [c for r in worked if (c := clock(field(r, "end_time")))]
    with st.container(horizontal=True):
        st.metric("Average start", _average(starts), border=True)
        st.metric("Average finish", _average(ends), border=True)
        st.metric("Total Overtime", f"{balance:+.1f} h", border=True)

st.divider()
st.markdown("**Archived projects**")

projects = db.projects()
retired = projects[projects["archived"] == 1]
if retired.empty:
    st.caption("None archived.")
# Retiring a project hides none of what it held: the chip opens the same card
# as on Projects, with the way back where its archive and delete buttons are.
projectcard.chips(retired, "retired", [NO_PROJECT] + list(projects["name"]))

st.divider()
st.markdown("**Backups**")

outcome = st.session_state.pop("restored", None)
if outcome:
    st.success(outcome)

# One row: the button sizes to its label and the uploader takes the rest.
with st.container(horizontal=True, vertical_alignment="center"):
    st.download_button("Backup history", data=db.snapshot,
                       file_name=f"planner_backup_{date.today():%d%m%y}.db",
                       mime="application/vnd.sqlite3", icon=":material/download:",
                       help="Your whole history and settings, as one file.")
    restoring = st.file_uploader("Restore history", type=["db"],
                                 label_visibility="collapsed",
                                 help="A file saved by Backup history.")

if restoring is not None:
    how = st.segmented_control("How to apply it", ["Merge", "Overwrite"],
                               default="Merge", label_visibility="collapsed")
    with st.popover(f"{how} this history", icon=":material/upload:"):
        if how == "Overwrite":
            st.markdown("**Replace everything with this file?**")
            st.caption("Every task, day, project, review and setting in the app "
                       "is written over. This cannot be undone, so back up first.")
        else:
            st.markdown("**Add what is missing from this file?**")
            st.caption("Nothing here is changed or removed. A task, meeting or "
                       "paper of the same kind, title and day is already here, "
                       "so it is left alone.")
        if st.button("Yes, go ahead", type="primary"):
            try:
                if how == "Overwrite":
                    db.restore(restoring.getvalue())
                    outcome = "History replaced."
                else:
                    added = db.merge(restoring.getvalue())
                    outcome = ("Added " + ", ".join(f"{count} {name}"
                                                    for name, count in added.items())
                               if added else "Nothing to add: it is all here already.")
            except ValueError as problem:
                st.error(str(problem))
            else:
                # The message has to outlive the rerun that redraws the page.
                st.session_state["restored"] = outcome
                st.rerun()
