"""Plandrea - a personal task list, work diary and weekly review."""

from datetime import date, timedelta
from pathlib import Path

import streamlit as st

import db
from palette import (BULLET_JS, CHECKBOX_CSS, INPUT_CSS, NAV_CSS,
                     SECTION_CSS)

#: Beside this file, not the working directory: the packaged app starts elsewhere.
ASSETS = Path(__file__).resolve().parent / "assets"

st.set_page_config(page_title="Plandrea", page_icon=str(ASSETS / "logo.png"),
                   layout="wide")
st.logo(str(ASSETS / "logo.svg"), size="large")

page = st.navigation([
    st.Page("app_pages/week.py", title="My Week",
            icon=":material/calendar_view_week:"),
    st.Page("app_pages/tasks.py", title="Tasks", icon=":material/checklist:"),
    st.Page("app_pages/meetings.py", title="Meetings", icon=":material/groups:"),
    st.Page("app_pages/papers.py", title="Papers", icon=":material/menu_book:"),
    st.Page("app_pages/projects.py", title="Projects", icon=":material/folder:"),
    st.Page("app_pages/settings.py", title="Settings", icon=":material/settings:"),
], position="top")

# A task or meeting settles onto its own day once that day is over.
db.close_past_days()

st.html(SECTION_CSS)
st.html(INPUT_CSS)
st.html(CHECKBOX_CSS)
st.html(NAV_CSS)
st.html(BULLET_JS, unsafe_allow_javascript=True)

# The end-of-week nudge, on the last working day of this week that is not a
# holiday: normally Friday, Thursday when Friday is taken off, and so on.
today = date.today()
monday = today - timedelta(days=today.weekday())
week = db.days_in(monday, monday + timedelta(days=4))
off = {row["day"].date() for _, row in week.iterrows() if row["holiday"]}
last_working = next((day for offset in range(4, -1, -1)
                     if (day := monday + timedelta(days=offset)) not in off), None)
if today == last_working and not any(db.review(monday).values()):
    st.info(f"Your review for the week of {monday:%d %b} is still empty.",
            icon=":material/rate_review:")

page.run()
