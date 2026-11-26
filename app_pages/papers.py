"""Papers: what is still to read, then everything read, searchable by title,
tag, note or project. A paper has no milestones, just notes and tags, and
opens the same editor a task does."""

from datetime import date

import pandas as pd
import streamlit as st

import daycard
import db
from palette import (NO_PROJECT, badge, chip_css, chip_date_css, search_css,
                     strike, style_block)


today = date.today()


def _mark_read(paper_id: int) -> None:
    """Read here records it as read today; a day's checklist uses that day."""
    db.set_task_done(paper_id, today if
                     st.session_state[f"paper_read:{paper_id}"] else None)


papers = db.unread_papers()
names = [NO_PROJECT] + list(db.projects()["name"])

st.header("Reading List")
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
# Read before the box is drawn, so the count above it can say what it holds.
query = st.session_state.get("paper_search", "")
read = db.papers_read(query)
st.header(f"Paper Database :gray-badge[{len(read)}{' matching' if query else ''}]")
st.text_input("Search papers", key="paper_search",
              placeholder="Search titles, tags, notes and projects…",
              label_visibility="collapsed")
# The search is the way into the whole database, so it is drawn larger than
# an ordinary box: taller, with bigger text.
rules.append(search_css("paper_search"))


def _read_line(paper) -> None:
    """One read paper: its chip in its project's colour with the day it was
    read at the far right, as the reading list above draws its days; then its
    tags; then a way out to the paper itself where it has a link."""
    global opened
    key = f"papers:read:{paper.id}"
    rules.append(chip_css(key, paper.colour))
    rules.append(chip_date_css(key, paper.done_on))
    line = st.columns([8, 1.7, 0.5], vertical_alignment="center")
    if line[0].button(paper.title, key=key, width="stretch"):
        opened = paper
    tags = db.split_tags(paper.tags)
    if tags:
        # A bracket in a tag would close the badge early.
        line[1].markdown(" ".join(
            f":gray-badge[{tag.replace('[', '(').replace(']', ')')}]"
            for tag in tags))
    link = None if pd.isna(paper.link) else str(paper.link).strip()
    if link:
        line[2].link_button("", link, icon=":material/open_in_new:",
                            help="View paper", width="stretch")


if read.empty:
    st.caption("No papers match." if query else "No papers read yet.")
else:
    # Grouped by project, each headed by its own coloured badge. A project
    # comes in the order of its latest read, so what is being read now sits at
    # the top; papers with no project come last. Within a project, newest
    # first. A long list scrolls in its own box, so the page stays one height
    # however much has been read; a short one takes only the room it needs.
    owned = read[read["project"].notna()]
    loose = read[read["project"].isna()]
    with st.container(border=True, height=460 if len(read) > 8 else "content"):
        for name, in_project in owned.groupby("project", sort=False):
            colour = in_project["colour"].iloc[0]
            st.markdown(badge(name, colour))
            for paper in in_project.itertuples():
                _read_line(paper)
        if not loose.empty:
            st.markdown("**No project**")
            for paper in loose.itertuples():
                _read_line(paper)

# One style block for every chip, each in its project's colour.
if rules:
    st.html(style_block(rules))

if opened is not None:
    daycard.open_item(opened, "papers:", names)
