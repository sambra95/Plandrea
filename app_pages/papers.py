"""Papers: what is still to read, then everything read, searchable by title,
tag, note or project. A paper has no milestones, just notes and tags, and
opens the same editor a task does."""

from datetime import date

import pandas as pd
import streamlit as st

import daycard
import db
from palette import NO_PROJECT, chip_css, chip_date_css, strike, style_block


today = date.today()


def _mark_read(paper_id: int) -> None:
    """Read here records it as read today; a day's checklist uses that day."""
    db.set_task_done(paper_id, today if
                     st.session_state[f"paper_read:{paper_id}"] else None)


papers = db.unread_papers()
names = [NO_PROJECT] + list(db.projects()["name"])

daycard.add_button(db.PAPER, names)

rules = []
opened = None

if papers.empty:
    st.caption("Nothing to read.")

for paper in papers.itertuples():
    rules.append(chip_css(f"papers:open:{paper.id}", paper.colour))
    if not pd.isna(paper.day):
        rules.append(chip_date_css(f"papers:open:{paper.id}", paper.day))

    line = st.columns([8, 0.4, 1.3, 0.5], vertical_alignment="center")
    if line[0].button(strike(paper.title, False),
                      key=f"papers:open:{paper.id}", width="stretch"):
        opened = paper
    line[1].checkbox("Read", value=False, key=f"paper_read:{paper.id}",
                     label_visibility="collapsed", help="Mark as read",
                     on_change=_mark_read, args=(paper.id,))
    # Onto today's card, still to read. Greyed out where it already sits there.
    line[2].button("Read today", icon=":material/today:", width="stretch",
                   key=f"paper_today:{paper.id}",
                   disabled=paper.day == pd.Timestamp(today),
                   on_click=db.set_task_day, args=(paper.id, today))
    line[3].button("", icon=":material/delete:", key=f"paper_drop:{paper.id}",
                   on_click=db.delete_task, args=(paper.id,))

st.divider()
st.markdown("**Read**")
query = st.text_input("Search papers", key="paper_search",
                      placeholder="Search titles, tags, notes and projects…",
                      label_visibility="collapsed")
read = db.papers_read(query)

if read.empty:
    st.caption("No papers match." if query else "No papers read yet.")
else:
    # A table stays one height however long the list gets; the notes, which are
    # as long as they are, open on the row you pick.
    listing = pd.DataFrame({"Read": read["done_on"], "Paper": read["title"],
                            "Tags": read["tags"].fillna(""),
                            "Project": read["project"].fillna("-"),
                            "Notes": read["notes"].fillna("")})
    picked = st.dataframe(
        listing, hide_index=True, width="stretch", height=280, key="paper_hits",
        on_select="rerun", selection_mode="single-row",
        column_config={
            "Read": st.column_config.DateColumn(format="ddd DD MMM YYYY"),
            "Paper": st.column_config.TextColumn(width="large"),
            "Tags": st.column_config.TextColumn(width="small"),
            "Notes": st.column_config.TextColumn(width="medium"),
        })
    rows = picked.selection.rows
    if not rows:
        # Nothing picked, so a later pick of the same row should open again.
        st.session_state.pop("dismissed_item", None)
    elif opened is None:
        # One row, as a namedtuple: a dialog is a fragment and is handed its
        # arguments back on every rerun, and a Series does not survive that.
        chosen = next(read.iloc[[rows[0]]].itertuples())
        # The selection outlives the dialog, so without this it reopens at once.
        if chosen.id != st.session_state.get("dismissed_item"):
            opened = chosen

# One style block for every chip, each in its project's colour.
if rules:
    st.html(style_block(rules))

if opened is not None:
    daycard.open_item(opened, "papers:", names)
