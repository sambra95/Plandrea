"""Meetings: a month calendar, each on the day it happened - the day it was
held, or the day it is set for."""

import calendar
from datetime import date, timedelta

import pandas as pd
import streamlit as st

import daycard
import db
from palette import (NO_PROJECT, chip_css, css_class, holiday_css,
                     style_block, wash)
from worktime import is_holiday, when

WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

#: A fixed height, so the grid reads as a calendar whatever a day holds; what
#: does not fit is reached by scrolling it, hence the badge with its total.
CELL_HEIGHT = 120

#: The month steps and title, sized as My Week sizes its week steps and title,
#: so the two pages move the same way.
STEP_WIDTH = 200
LABEL_SIZE = "2.25rem"
ROW_HEIGHT = "3.5rem"

MONTH_ROW_CSS = f"""<style>
.{css_class("month_back")} button, .{css_class("month_on")} button,
.{css_class("month_now")} button {{ height: {ROW_HEIGHT}; }}
.{css_class("month_now")} button p {{ font-size: {LABEL_SIZE}; }}
</style>"""


def _first_of_month(day: date) -> date:
    return day.replace(day=1)


def _shift(months: int) -> None:
    """Move the month in view, carrying over the year end in either direction."""
    start = st.session_state.month_start
    moved = start.month - 1 + months
    st.session_state.month_start = date(start.year + moved // 12, moved % 12 + 1, 1)


def _this_month() -> None:
    st.session_state.month_start = _first_of_month(date.today())


st.session_state.setdefault("month_start", _first_of_month(date.today()))

# A step either side of the month's name, as My Week lays out its weeks. The
# name is the way back to this month.
st.html(MONTH_ROW_CSS)
with st.container(horizontal=True, vertical_alignment="center"):
    st.button("", icon=":material/chevron_left:", key="month_back",
              width=STEP_WIDTH, on_click=_shift, args=(-1,))
    st.button(f"{st.session_state.month_start:%B %Y}", key="month_now",
              width="stretch", help="Back to this month", on_click=_this_month)
    st.button("", icon=":material/chevron_right:", key="month_on",
              width=STEP_WIDTH, on_click=_shift, args=(1,))

month_start = st.session_state.month_start

# A new meeting lands on today when today is in view, otherwise on the 1st.
default_day = (date.today() if month_start.year == date.today().year
               and month_start.month == date.today().month else month_start)

names = [NO_PROJECT] + list(db.projects()["name"])
daycard.add_button(db.MEETING, names, day=default_day)


next_month = date(month_start.year + month_start.month // 12,
                  month_start.month % 12 + 1, 1)
month_end = next_month - timedelta(days=1)

# The grid spans whole weeks, so it runs into the months either side. Fetch those
# days too, then grey them out, rather than leaving holes at the corners.
grid = calendar.Calendar(firstweekday=0).monthdatescalendar(
    month_start.year, month_start.month)
meetings = db.meetings_in(grid[0][0], grid[-1][-1])
by_day = {day: frame for day, frame in meetings.groupby(meetings["on_day"].dt.date)}

# The same days My Week marks off, read over the whole grid so the neighbouring
# months are marked too rather than changing colour as they scroll into view.
holidays = {record["day"].date()
            for _, record in db.days_in(grid[0][0], grid[-1][-1]).iterrows()
            if is_holiday(record)}

today = date.today()
rules = []
opened = None

for column, name in zip(st.columns(7), WEEKDAYS):
    column.caption(f"**{name}**")

for week in grid:
    for column, day in zip(st.columns(7), week):
        on_day = by_day.get(day, pd.DataFrame())
        # A day with anything on it says how many, so a busy day reads at a
        # glance and the ones past the fold are not left unannounced.
        tally = f" :gray-badge[{len(on_day)}]" if len(on_day) else ""
        # Only a day off is keyed: the rest need no rule, and keying every cell
        # would put a class on the whole grid to style seven of them.
        off = f"cal-holiday-{day}" if day in holidays else None
        if off:
            rules.append(holiday_css(off))
        with column, st.container(border=True, height=CELL_HEIGHT, key=off):
            # Named as well as washed: the colour alone would be the only thing
            # telling a day off from a quiet one.
            mark = " :green-badge[Holiday]" if off else ""
            if day == today:
                st.markdown(f"**{day.day}** :blue-badge[today]{tally}{mark}")
            elif day.month == month_start.month:
                st.markdown(f"**{day.day}**{tally}{mark}")
            else:
                st.caption(f"{day.day}")
            for meeting in on_day.itertuples():
                # Buttons cannot render a colour directive in their label, so the
                # button itself is painted in the project's colour instead.
                rules.append(chip_css(f"open-{meeting.id}", meeting.colour))
                clock_face = when(meeting._asdict())
                if st.button(f"{clock_face} {meeting.title}".strip(),
                             key=f"open-{meeting.id}", width="stretch"):
                    opened = meeting

# The grid runs into the neighbouring months, so count only this one's days.
in_month = meetings[(meetings["on_day"] >= pd.Timestamp(month_start))
                    & (meetings["on_day"] <= pd.Timestamp(month_end))]
if in_month.empty:
    st.caption("No meetings this month.")

if rules:
    st.html(style_block(rules))

if opened is not None:
    daycard.open_item(opened, "cal:", names)


st.divider()
query = st.text_input("Search meetings", key="meeting_search",
                      placeholder="Search every month by title, write-up or project…",
                      label_visibility="collapsed")

if query:
    found = db.meetings_matching(query)
    if found.empty:
        st.caption("No meetings match.")
    else:
        def _row_tint(row):
            colour = found.loc[row.name, "colour"]
            return [""] * len(row) if pd.isna(colour) else \
                   [f"background-color: {wash(colour)}"] * len(row)

        listing = pd.DataFrame({"Day": found["on_day"], "Meeting": found["title"],
                                "Project": found["project"].fillna("-"),
                                "Notes": found["notes"].fillna("")})
        picked = st.dataframe(
            listing.style.apply(_row_tint, axis=1), hide_index=True, width="stretch", height=280, key="meeting_hits",
            on_select="rerun", selection_mode="single-row",
            column_config={
                "Day": st.column_config.DateColumn(format="ddd DD MMM YYYY"),
                "Meeting": st.column_config.TextColumn(width="large"),
                "Notes": st.column_config.TextColumn(width="medium"),
            })
        st.caption(f"{len(found)} meeting(s) matching · pick one to open it")

        rows = picked.selection.rows
        if not rows:
            # Nothing picked, so a later pick of the same row should open again.
            st.session_state.pop("dismissed_item", None)
        elif opened is None:
            # One row, as a namedtuple: a dialog is a fragment and is handed its
            # arguments back on every rerun, and a Series does not survive that.
            chosen = next(found.iloc[[rows[0]]].itertuples())
            # The selection outlives the dialog, so without this the dialog
            # reopens the moment it is dismissed.
            if chosen.id != st.session_state.get("dismissed_item"):
                daycard.open_item(chosen, "cal:", names)
