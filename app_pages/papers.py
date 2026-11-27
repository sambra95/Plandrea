"""Papers: suggestions of what to read next, what is still to read, then
everything read, searchable by title, tag, note or project. A paper has no
milestones, just notes and tags, and opens the same editor a task does."""

from datetime import date

import pandas as pd
import streamlit as st

import daycard
import db
import scholar
from palette import (NO_PROJECT, badge, chip_css, chip_date_css, search_css,
                     strike, style_block)


today = date.today()


def _mark_read(paper_id: int) -> None:
    """Read here records it as read today; a day's checklist uses that day."""
    db.set_task_done(paper_id, today if
                     st.session_state[f"paper_read:{paper_id}"] else None)


papers = db.unread_papers()
names = [NO_PROJECT] + list(db.projects()["name"])


@st.cache_data(ttl="1h", show_spinner="Matching papers to Semantic Scholar…")
def _match(unmatched: tuple[tuple[int, str], ...]) -> None:
    """Look up papers not yet matched until Semantic Scholar refuses. Cached on
    what is left, so a refusal that matched none waits an hour to be retried."""
    for paper_id, title in unmatched:
        try:
            db.set_paper_s2_id(paper_id, scholar.match(title))
        except (OSError, ValueError):
            return


def _seeds() -> pd.DataFrame:
    """The papers suggestions can start from: those found on Semantic Scholar,
    one row each. Papers not yet looked up are looked up first."""
    seeds = db.paper_seeds()
    _match(tuple(seeds.loc[seeds["s2_id"].isna(), ["id", "title"]]
                 .itertuples(index=False, name=None)))
    seeds = db.paper_seeds()
    seeds = seeds[seeds["s2_id"].fillna("") != ""].drop_duplicates("s2_id")
    return seeds.sort_values(["project", "title"], na_position="last")


def _pick_project(seeds: pd.DataFrame) -> None:
    """Choosing a project ticks its papers alone; choosing none ticks all."""
    project = st.session_state["suggest_for"]
    st.session_state["suggest_ticks"] = {
        s2_id: project is None or owner == project
        for s2_id, owner in zip(seeds["s2_id"], seeds["project"])}


def _paper_table(seeds: pd.DataFrame, project: str | None) -> tuple[str, ...]:
    """The papers to start from, as a table to tick rows in. Ticks are kept by
    paper, untouched ones ticked, and give back the Semantic Scholar ids."""
    ids = list(seeds["s2_id"])
    ticks = st.session_state.setdefault("suggest_ticks", {})
    # A table's ticks are row positions it only takes from selection_default
    # when new, so new rows or a new project get a new table, seeded by paper.
    event = st.dataframe(
        seeds[["title", "project", "done_on"]], hide_index=True,
        width="stretch", height=min(400, 38 + 35 * len(ids)),
        column_config={"title": "Paper", "project": "Project",
                       "done_on": st.column_config.DateColumn(
                           "Read", format="D MMM YYYY")},
        on_select="rerun", selection_mode="multi-row",
        selection_default={"selection": {"rows": [
            row for row, s2_id in enumerate(ids) if ticks.get(s2_id, True)]}},
        key=f"suggest_grid_{hash((tuple(ids), project))}")
    chosen = set(event.selection.rows)
    ticks.update({s2_id: row in chosen for row, s2_id in enumerate(ids)})
    return tuple(sorted(s2_id for row, s2_id in enumerate(ids) if row in chosen))


def _add(paper: dict, project: str | None) -> None:
    """A suggestion onto the reading list, with its link, under `project`."""
    paper_id = db.add_paper(paper["title"])
    db.set_task_link(paper_id, scholar.link(paper))
    db.set_paper_s2_id(paper_id, paper["paperId"])
    if project:
        db.set_task_project(paper_id, project)


def _refresh(shown: list[str]) -> None:
    """Set the suggestions on screen aside for the next ones, starting over
    when none are left, and ask afresh in case there is anything new."""
    seen = st.session_state.setdefault("suggest_seen", set())
    if shown:
        seen.update(shown)
    else:
        seen.clear()
    scholar.suggest.clear()


def _recommendations() -> None:
    """Papers like those already here, from Semantic Scholar. A failure to
    reach it is kept until Try again, so the page does not wait on every run."""
    st.header("Paper Recommendations")
    seeds = _seeds()
    # The button is filled in below, once it knows what is on screen.
    top = st.columns([8, 2.3], vertical_alignment="bottom")
    project = top[0].selectbox(
        "Suggest papers like", [None] + sorted(seeds["project"].dropna().unique()),
        format_func=lambda name: name or "All my papers", key="suggest_for",
        on_change=_pick_project, args=(seeds,))
    liked = _paper_table(seeds, project)
    found = []
    if "scholar_error" not in st.session_state:
        try:
            if liked:
                found = scholar.suggest(liked, tuple(db.dismissed_papers()))
        except (OSError, ValueError) as error:
            st.session_state["scholar_error"] = str(error)
    if error := st.session_state.get("scholar_error"):
        st.caption(f"Couldn't reach Semantic Scholar: {error}")
        st.button("Try again", key="scholar_retry",
                  on_click=st.session_state.pop, args=("scholar_error",))
        return
    skip = (set(db.paper_seeds()["s2_id"].dropna()) | set(db.dismissed_papers())
            | st.session_state.get("suggest_seen", set()))
    shown = [paper for paper in found if paper["paperId"] not in skip][:8]
    top[1].button("New suggestions", icon=":material/refresh:", width="stretch",
                  key="suggest_new", on_click=_refresh,
                  args=([paper["paperId"] for paper in shown],))
    if not shown:
        st.caption("No more suggestions: press New suggestions to start over."
                   if st.session_state.get("suggest_seen") else
                   "No suggestions yet.")
    for paper in shown:
        detail = " · ".join(str(part) for part in
                            (paper.get("year"), paper.get("venue")) if part)
        line = st.columns([8, 0.5, 1.3, 0.5], vertical_alignment="center")
        # A dollar would start maths; a bracket would close the grey early.
        line[0].markdown(paper["title"].replace("$", r"\$") + " :gray["
                         + detail.replace("[", "(").replace("]", ")") + "]")
        line[1].link_button("", scholar.link(paper), help="View paper",
                            icon=":material/open_in_new:", width="stretch")
        line[2].button("To read", icon=":material/add:", width="stretch",
                       key=f"suggest_add:{paper['paperId']}",
                       on_click=_add, args=(paper, project))
        line[3].button("", icon=":material/close:", help="Not interested",
                       key=f"suggest_drop:{paper['paperId']}",
                       on_click=db.dismiss_paper, args=(paper["paperId"],))


_recommendations()
st.divider()

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
