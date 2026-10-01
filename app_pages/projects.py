"""Projects: a name, whatever is worth noting, dates and a colour of its own.
One chip each, as a task or a meeting is, opening the project's own card.
Archived ones live on Settings."""

import streamlit as st

import daycard
import db
import projectcard
from palette import NO_PROJECT


@st.dialog("Add project", width="large")
def _add_project() -> None:
    """A new project, laid out like the card it will become but empty. Its
    colour is not asked for: the next unused one is handed out."""
    name = st.text_input("Project", key="new_pname", placeholder="The project…")
    about = st.text_area("Notes", key="new_pabout", height=130,
                         placeholder="Add a note…")
    span = st.columns(2)
    start = span[0].date_input("From", value=None, key="new_pstart",
                               format="DD/MM/YYYY")
    end = span[1].date_input("To", value=None, key="new_pend", format="DD/MM/YYYY")

    if not st.button("Add project", type="primary", width="stretch",
                     key="new_psubmit"):
        return
    if not name.strip():
        st.error("A name is needed. Everything else can wait.")
        return
    new_id = db.add_project(name)
    if about.strip():
        db.set_project_notes(new_id, about)
    if start or end:
        db.set_project_dates(new_id, start, end)
    st.rerun(scope="app")


if st.button("Add project", icon=":material/add:", width="stretch"):
    daycard.forget_draft("new_p")
    _add_project()

projects = db.projects()
live = projects[projects["archived"] == 0]
if live.empty:
    st.caption("No projects yet.")
projectcard.chips(live, "project", [NO_PROJECT] + list(live["name"]))
