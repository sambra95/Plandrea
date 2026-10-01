"""One day's card, and a week of them, shared by My Week and the archive.

The checklist is a tick and a name; notes, milestones and write-ups open in a
dialog. Widget keys are prefixed per page so the same day rendered twice does
not collide in Session State.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd
import streamlit as st

import db
from palette import (NO_PROJECT, chip_css, done_css, select_css, strike,
                     style_block)
from worktime import (DEFAULT_END, DEFAULT_START, clock, default_break,
                      WEEK_DAYS, field, is_holiday, net, or_default,
                      span, when)


def _save_day(prefix: str, day: date) -> None:
    holiday = st.session_state[f"{prefix}holiday:{day}"]
    db.save_day(day,
                None if holiday else st.session_state.get(f"{prefix}start:{day}"),
                None if holiday else st.session_state.get(f"{prefix}end:{day}"),
                None if holiday else st.session_state.get(f"{prefix}break:{day}"),
                st.session_state[f"{prefix}comment:{day}"], holiday)


def _toggle_task(prefix: str, task_id: int, day: date) -> None:
    """Ticking files it under this day; unticking puts it back."""
    done = st.session_state[f"{prefix}task:{task_id}"]
    db.set_task_done(task_id, day if done else None)


def _toggle_milestone(key: str, milestone_id: int, day: date) -> None:
    """A milestone stands alone: ticking it files it under `day` and leaves the
    task open, on the list and wherever it already sat. `key` is the box that
    was ticked - the editor and a day card each keep their own."""
    db.set_milestone_done(milestone_id, day if st.session_state[key] else None)


def _clear_day(task_id: int) -> None:
    """Take something off this day without deleting it."""
    db.set_task_day(task_id, None)


def _rename(prefix: str, task_id: int) -> None:
    db.rename_task(task_id, st.session_state[f"{prefix}dtitle:{task_id}"])


def _move(prefix: str, task_id: int, kind: str) -> None:
    """Send it to another day. A meeting must keep one; a task or paper need
    not."""
    chosen = st.session_state[f"{prefix}dday:{task_id}"]
    if kind == db.MEETING:
        if chosen:
            db.move_meeting(task_id, chosen)
    else:
        db.set_task_day(task_id, chosen)


def _set_project(prefix: str, task_id: int) -> None:
    chosen = st.session_state[f"{prefix}dproject:{task_id}"]
    db.set_task_project(task_id, None if chosen == NO_PROJECT else chosen)


def _set_notes(prefix: str, task_id: int) -> None:
    db.set_task_notes(task_id, st.session_state[f"{prefix}dabout:{task_id}"])


def _set_times(prefix: str, task_id: int) -> None:
    db.set_meeting_times(task_id,
                         st.session_state[f"{prefix}dstart:{task_id}"],
                         st.session_state[f"{prefix}dend:{task_id}"])


def _set_tags(prefix: str, task_id: int) -> None:
    key = f"{prefix}dtags:{task_id}"
    st.session_state[key] = db.set_task_tags(task_id, st.session_state[key])


def _set_link(prefix: str, task_id: int) -> None:
    key = f"{prefix}dlink:{task_id}"
    st.session_state[key] = db.set_task_link(task_id, st.session_state[key])


def _set_note(prefix: str, task_id: int, field: str) -> None:
    db.set_task_note(task_id, field,
                     st.session_state[f"{prefix}d{field}:{task_id}"])


def _add_milestone(prefix: str, task_id: int) -> None:
    db.add_milestone(task_id, st.session_state[f"{prefix}dnewmilestone:{task_id}"])
    st.session_state[f"{prefix}dnewmilestone:{task_id}"] = ""


def _rename_milestone(key: str, milestone_id: int) -> None:
    db.rename_milestone(milestone_id, st.session_state[key])


#: How many milestones a card shows before the list starts scrolling, and what
#: one row of it stands. The height is a little over the rows shown, so the next
#: one peeks out and says there is more below.
_MILESTONES_SHOWN = 5
_MILESTONE_ROW = 42

#: The room a milestone's "Completed" badge is given, in pixels, whether or not
#: it has one: a little over the widest date, so the badge never wraps.
_BADGE_WIDTH = 220


def _done_badge(done_on, verb: str = "Completed") -> str:
    """When something was finished, worded and dated the same wherever it shows.
    A paper is read, not quite "done"."""
    return f":green-badge[{verb} {done_on:%a %d %b %Y}]"


def _milestone_box(count: int):
    """The frame the milestones are listed in. A short list simply takes the room
    it needs; a long one is capped and scrolls inside the card, so the box to add
    one and the buttons under it stay where they are."""
    if count <= _MILESTONES_SHOWN:
        return st.container()
    return st.container(
        height=_MILESTONES_SHOWN * _MILESTONE_ROW + _MILESTONE_ROW // 2)


#: What a meeting is written up under. A paper just has the one box.
_MEETING_SECTIONS = (("goals", "Goals"), ("notes", "Notes"),
                     ("actions", "Action points"))

def _draft_milestone(key: str) -> None:
    """Hold a milestone for a task that does not exist yet. It is written when
    the task is, so closing the box leaves no orphans behind."""
    if title := st.session_state[key + "newmilestone"].strip():
        st.session_state[key + "milestones"].append(title)
    st.session_state[key + "newmilestone"] = ""


def _paint_project(key: str, chosen: str | None) -> None:
    """Show the project box in its project's own colour. Read from the box
    rather than the item: a dialog keeps the arguments it opened with, so the
    item's colour would not follow a change made here."""
    if not chosen or chosen == NO_PROJECT:
        return
    colours = db.projects().set_index("name")["colour"]
    if chosen in colours.index:
        st.html(style_block([select_css(key, colours[chosen])]))


def _dismiss() -> None:
    """Remember what was closed. A table's selection outlives the dialog it
    opened, so without this the dialog reopens the moment it is dismissed; a
    chip does not need it, being a button that fires once."""
    st.session_state["dismissed_item"] = st.session_state.get("open_item")


#: What finishing is called, and what the list it comes back to is, per kind.
#: A paper is read, not completed.
_CARD_WORDS = {db.TASK: ("Completed", "task list"),
               db.PAPER: ("Read", "reading list")}


def _card_actions(item, prefix: str, day: date) -> None:
    """The foot of a task or paper card: finish it, put it back on its list, or
    delete it, three across the card. Each is greyed out when it has nothing to
    do, so the row keeps its shape whatever state the item is in. Finishing
    files it under `day`, as ticking it on that card would. A meeting has its
    own, since calling one off is not the same as deleting it."""
    done = not pd.isna(item.done_on)
    finished, listing = _CARD_WORDS[item.kind]
    row = st.columns(3)

    if row[0].button(finished, icon=":material/check_circle:", width="stretch",
                     key=f"{prefix}dfinish:{item.id}", disabled=done,
                     help=None if done else f"Mark it {finished.lower()}."):
        db.set_task_done(item.id, day)
        st.rerun(scope="app")

    # Finished, or set for a day: either way it is off the list, and this is
    # what puts it back.
    if row[1].button(f"Back on the {listing}", icon=":material/undo:",
                     width="stretch", key=f"{prefix}dback:{item.id}",
                     disabled=not (done or not pd.isna(item.day))):
        if done:
            db.set_task_done(item.id, None)
        else:
            _clear_day(item.id)
        st.rerun(scope="app")

    with row[2].popover("Delete", icon=":material/delete:", width="stretch"):
        st.markdown(f"**Delete this {item.kind}?**")
        st.caption("It goes, notes and all. This cannot be undone.")
        if st.button("Yes, delete it", type="primary", width="stretch",
                     key=f"{prefix}ddrop:{item.id}"):
            db.delete_task(item.id)
            st.rerun(scope="app")


def _editor(item, prefix: str, names: list[str], day: date) -> None:
    """Everything about one item, and everything you can change about it. `day`
    is the one a milestone ticked here is filed under: the card it was opened
    from, or today where there is no card."""
    st.session_state["open_item"] = item.id
    # Laid out as the empty editor a new one is made in: the title on its own,
    # then project and day, and for a meeting the hours beside them.
    # The ID to the right, centred on the box rather than on box and label.
    with st.container(horizontal=True, vertical_alignment="bottom"):
        st.text_input("Title", value=item.title, key=f"{prefix}dtitle:{item.id}",
                      on_change=_rename, args=(prefix, item.id))
        with st.container(height=40, width="content", border=False,
                          vertical_alignment="center"):
            st.markdown(f":gray-badge[{item.code}]")
    if item.kind == db.MEETING:
        filed, dated, from_at, to_at = st.columns([3, 1, 1, 1])
    else:
        filed, dated = st.columns(2)

    project_key = f"{prefix}dproject:{item.id}"
    filed.selectbox("Project", names, key=project_key,
                    index=names.index(item.project)
                    if item.project in names else 0,
                    on_change=_set_project, args=(prefix, item.id))
    _paint_project(project_key, st.session_state.get(project_key, item.project))
    dated.date_input("Day", value=None if pd.isna(item.on_day)
                     else item.on_day.date(),
                     key=f"{prefix}dday:{item.id}", format="DD/MM/YYYY",
                     on_change=_move, args=(prefix, item.id, item.kind))

    # Only a task carries one: a meeting and a paper say what they are in their
    # write-up and their notes.
    if item.kind == db.TASK:
        # A text area, as a meeting's write-up is: that is what the bullets
        # attach themselves to, and a note is rarely one line.
        st.text_area("Notes", key=f"{prefix}dabout:{item.id}", height=130,
                     value="" if pd.isna(item.description) else item.description,
                     placeholder="Add a note…",
                     on_change=_set_notes, args=(prefix, item.id))

    if item.kind == db.TASK:
        st.markdown("**Milestones**")
        # Read again here: a dialog is a fragment, handed its arguments back on
        # every rerun, so a frame passed in never changes.
        own = db.task_milestones(item.id)
        finished = []
        with _milestone_box(len(own)):
            for milestone in own.itertuples():
                # The name is typed over in place, as a task's title is.
                with st.container(horizontal=True, vertical_alignment="center"):
                    key = f"{prefix}dmilestone:{milestone.id}"
                    st.checkbox("Done", value=bool(milestone.done), key=key,
                                label_visibility="collapsed",
                                on_change=_toggle_milestone,
                                args=(key, milestone.id, day))
                    name = f"{prefix}dnamemilestone:{milestone.id}"
                    st.text_input("Milestone", value=milestone.title, key=name,
                                  label_visibility="collapsed", width="stretch",
                                  on_change=_rename_milestone,
                                  args=(name, milestone.id))
                    # Open ones leave the badge's room empty, so every name
                    # box ends in the same place.
                    done = pd.notna(milestone.done_on)
                    st.markdown(_done_badge(milestone.done_on) if done else "",
                                width=_BADGE_WIDTH)
                    if done:
                        finished.append(done_css(name))
                    st.button("", icon=":material/close:",
                              key=f"{prefix}ddropmilestone:{milestone.id}",
                              on_click=db.delete_milestone, args=(milestone.id,))
        # A finished milestone's name sits on green.
        if finished:
            st.html(style_block(finished))
        st.text_input("New milestone", key=f"{prefix}dnewmilestone:{item.id}",
                      placeholder="Add a milestone…",
                      label_visibility="collapsed",
                      on_change=_add_milestone, args=(prefix, item.id))
    elif item.kind == db.MEETING:
        from_at.time_input("From", clock(item.start_time), step=900,
                           key=f"{prefix}dstart:{item.id}", on_change=_set_times,
                           args=(prefix, item.id))
        to_at.time_input("To", clock(item.end_time), step=900,
                         key=f"{prefix}dend:{item.id}", on_change=_set_times,
                         args=(prefix, item.id))
        for field, label in _MEETING_SECTIONS:
            st.text_area(label, key=f"{prefix}d{field}:{item.id}", height=130,
                         value="" if pd.isna(getattr(item, field))
                         else getattr(item, field),
                         placeholder=f"{label}…", on_change=_set_note,
                         args=(prefix, item.id, field))
    else:
        tagged, linked, opens = st.columns([3, 3, 1.4],
                                           vertical_alignment="bottom")
        tagged.text_input("Tags", key=f"{prefix}dtags:{item.id}",
                          value="" if pd.isna(getattr(item, "tags", None))
                          else item.tags,
                          placeholder="Keywords, separated by commas…",
                          on_change=_set_tags, args=(prefix, item.id))
        link_key = f"{prefix}dlink:{item.id}"
        linked.text_input("Link", key=link_key,
                          value="" if pd.isna(getattr(item, "link", None))
                          else item.link, placeholder="https://…",
                          help="Where to read it. Paste a new address over it "
                               "to change it.",
                          on_change=_set_link, args=(prefix, item.id))
        # Always there, so the row keeps its shape, but dead until there is
        # somewhere to go.
        url = st.session_state.get(link_key, "")
        opens.link_button("View paper", url or "#", width="stretch",
                          icon=":material/open_in_new:", disabled=not url)
        st.text_area("Notes", key=f"{prefix}dnotes:{item.id}", height=180,
                     value="" if pd.isna(item.notes) else item.notes,
                     on_change=_set_note, args=(prefix, item.id, "notes"))

    if item.kind == db.MEETING:
        # A meeting only exists on its day, so taking it off the day deletes it.
        held = not pd.isna(item.done_on)
        wording = "Delete this meeting" if held else "Call off this meeting"
        with st.popover(wording, icon=":material/delete:"):
            st.markdown(f"**{wording}?**")
            st.caption("It goes, minutes and all. This cannot be undone.")
            if st.button("Yes, delete it" if held else "Yes, call it off",
                         type="primary", key=f"{prefix}ddrop:{item.id}"):
                db.delete_task(item.id)
                st.rerun(scope="app")
    else:
        _card_actions(item, prefix, day)


def _milestone_row(milestone, prefix: str, day: date, rules: list[str]) -> bool:
    """A milestone finished on this day, laid out as the tasks above it are: a
    tick that takes it back off the day, and its own name in its project's
    colour, which opens the card of the task it belongs to - the only place the
    rest of it lives. True when that card was asked for."""
    key = f"{prefix}dayms:{milestone.id}"
    chip = f"{prefix}daychip:{milestone.id}"
    rules.append(chip_css(chip, milestone.colour))

    line = st.columns([7, 1], vertical_alignment="center")
    # Only the milestone is named, so the task it belongs to is the hint.
    opened = line[0].button(strike(milestone.title, True), key=chip,
                            width="stretch",
                            help=f"Milestone of {milestone.task}")
    line[1].checkbox("Done", value=True, key=key, label_visibility="collapsed",
                     on_change=_toggle_milestone, args=(key, milestone.id, day))
    return opened


#: What each kind is called where a new one is being made.
_KIND_NAMES = {db.TASK: "task", db.MEETING: "meeting", db.PAPER: "paper"}


@st.dialog("Add task", width="large")
def _new_task(kind, names, day):
    _new(kind, names, day)


@st.dialog("Add meeting", width="large")
def _new_meeting(kind, names, day):
    _new(kind, names, day)


@st.dialog("Add paper", width="large")
def _new_paper(kind, names, day):
    _new(kind, names, day)


def add_button(kind: str, names: list[str], day: date | None = None) -> None:
    """The button that opens an empty editor for a new item of `kind`. Opening
    it drops whatever was typed into a previous one and abandoned, so it always
    starts blank."""
    if st.button(f"Add {_KIND_NAMES[kind]}", icon=":material/add:",
                 width="stretch", key=f"open_new_{kind}"):
        forget_draft(f"new_{kind}_")
        {db.TASK: _new_task, db.MEETING: _new_meeting,
         db.PAPER: _new_paper}[kind](kind, names, day)


def forget_draft(prefix: str) -> None:
    """Clear the fields of an editor for something that was never made. Safe
    here: the widgets it names belong to a run that is over."""
    for key in [key for key in st.session_state if key.startswith(prefix)]:
        del st.session_state[key]


def _new(kind: str, names: list[str], day: date | None) -> None:
    """A new item of `kind`, laid out like the editor that opens on an existing
    one but with every field empty. Nothing is written until Add is pressed, so
    a half-filled box that is closed leaves nothing behind."""
    what = _KIND_NAMES[kind]
    key = f"new_{kind}_"

    # The title on its own, then project and day, and for a meeting the hours
    # beside them, so every kind reads the same way.
    title = st.text_input("Title", key=key + "title", placeholder=f"The {what}…")
    if kind == db.MEETING:
        filed, dated, from_at, to_at = st.columns([3, 1, 1, 1])
    else:
        filed, dated = st.columns(2)

    project = filed.selectbox("Project", names, key=key + "project")
    _paint_project(key + "project", project)
    # A meeting lives on its day, so it starts on one rather than nowhere.
    when = dated.date_input("Day", value=day, key=key + "day",
                            format="DD/MM/YYYY")
    description = ("" if kind != db.TASK else
                   st.text_area("Notes", key=key + "about", height=130,
                                placeholder="Add a note…"))

    times, notes = (None, None), {}
    if kind == db.MEETING:
        times = (from_at.time_input("From", value=None, step=900,
                                    key=key + "start"),
                 to_at.time_input("To", value=None, step=900, key=key + "end"))
        for field, label in _MEETING_SECTIONS:
            notes[field] = st.text_area(label, height=130, key=key + field,
                                        placeholder=f"{label}…")
    elif kind == db.PAPER:
        tagged, linked = st.columns(2)
        tags = tagged.text_input("Tags", key=key + "tags",
                                 placeholder="Keywords, separated by commas…")
        link = linked.text_input("Link", key=key + "link",
                                 placeholder="https://…")
        notes["notes"] = st.text_area("Notes", height=180, key=key + "notes")
    elif kind == db.TASK:
        st.markdown("**Milestones**")
        drafted = st.session_state.setdefault(key + "milestones", [])
        with _milestone_box(len(drafted)):
            for index, milestone in enumerate(drafted):
                row = st.columns([9, 0.6, 0.6], vertical_alignment="center")
                row[0].markdown(milestone)
                row[1].button("", icon=":material/close:",
                              key=f"{key}dropmilestone:{index}",
                              on_click=drafted.pop, args=(index,))
        st.text_input("New milestone", key=key + "newmilestone",
                      placeholder="Add a milestone…",
                      label_visibility="collapsed", on_change=_draft_milestone,
                      args=(key,))

    if not st.button(f"Add {what}", type="primary", width="stretch",
                     key=key + "submit"):
        return
    if not title.strip():
        st.error("A title is needed. Everything else can wait.")
        return

    # Made first, then filled in: the setters the editor uses take an id.
    new_id = (db.add_meeting(title, when) if kind == db.MEETING
              else db.add_paper(title, when) if kind == db.PAPER
              else db.add_task(title))
    if kind == db.TASK and when:
        db.set_task_day(new_id, when)
    if project != NO_PROJECT:
        db.set_task_project(new_id, project)
    if description.strip():
        db.set_task_notes(new_id, description)
    if kind == db.MEETING and any(times):
        db.set_meeting_times(new_id, *times)
    if kind == db.PAPER and tags.strip():
        db.set_task_tags(new_id, tags)
    if kind == db.PAPER and link.strip():
        db.set_task_link(new_id, link)
    for field, written in notes.items():
        if written.strip():
            db.set_task_note(new_id, field, written)
    for milestone in st.session_state.get(key + "milestones", []):
        db.add_milestone(new_id, milestone)
    st.rerun(scope="app")


def open_item(item, prefix: str, names: list[str],
              day: date | None = None) -> None:
    """The editor for one item, headed with what it is and where it stands.
    Public, because every page that lists items opens the same one. `day` is the
    card it was opened from; a page listing items without days files a milestone
    under today.

    A dialog takes its title when it is decorated, so one naming this item is
    made here rather than three standing ones taking it as an argument."""
    standing = (":gray-badge[Open]" if pd.isna(item.done_on) else
                _done_badge(item.done_on,
                            "Read" if item.kind == db.PAPER else "Completed"))

    @st.dialog(f"{item.kind.capitalize()} {standing}", width="large",
               on_dismiss=_dismiss)
    def _open():
        _editor(item, prefix, names, day or date.today())

    _open()


def render_day(day: date, record, tasks: pd.DataFrame,
               milestones: pd.DataFrame, prefix: str, rules: list[str]):
    """One day's card, from what `db.milestones_in` returns. Gives back the item
    whose name was clicked and this day, so the editor knows where it opened
    from, or None."""
    opened = None
    with st.container(border=True):
        header = st.columns([3, 2], vertical_alignment="center")
        # %-d is glibc-only and blows up on Windows; take the day number
        # straight off the date so the format string stays portable.
        header[0].markdown(f"**{day:%a} {day.day} {day:%b}**"
                           + (" :blue-badge[today]" if day == date.today() else ""))
        away = header[1].checkbox("Holiday", value=is_holiday(record),
                                  key=f"{prefix}holiday:{day}",
                                  help="Leave this day out of every time "
                                       "calculation.",
                                  on_change=_save_day, args=(prefix, day))

        if away:
            st.caption("Holiday - not counted.")
        else:
            # Only a weekday stands in as an ordinary day; a weekend default
            # would read as unearned overtime.
            ordinary = day.weekday() < WEEK_DAYS
            clocks = st.columns(2)
            start = clocks[0].time_input(
                "Start", or_default(clock(field(record, "start_time")),
                                    DEFAULT_START if ordinary else None),
                step=900, key=f"{prefix}start:{day}", on_change=_save_day,
                args=(prefix, day))
            end = clocks[1].time_input(
                "End", or_default(clock(field(record, "end_time")),
                                  DEFAULT_END if ordinary else None),
                step=900, key=f"{prefix}end:{day}", on_change=_save_day,
                args=(prefix, day))
            st.number_input(
                "Break", min_value=0.0, max_value=24.0, step=0.5,
                value=or_default(field(record, "break_hours"),
                                 default_break() if ordinary else None),
                key=f"{prefix}break:{day}",
                help="Hours between start and end that were not work. They come "
                     "off the hours worked.",
                on_change=_save_day, args=(prefix, day))

            hours = net(span(start, end),
                        st.session_state.get(f"{prefix}break:{day}"))
            st.caption(f"{round(hours, 2):g} h worked" if hours is not None
                       else "No hours yet")

        for item in tasks.itertuples():
            done = not pd.isna(item.done_on)
            own = (milestones[milestones["task_id"] == item.id]
                   if item.kind == db.TASK else milestones.iloc[0:0])
            tally = f" ({int(own['done'].sum())}/{len(own)})" if len(own) else ""
            rules.append(chip_css(f"{prefix}open:{item.id}", item.colour))

            line = st.columns([7, 1], vertical_alignment="center")
            clock_face = when(item._asdict()) if item.kind == db.MEETING else ""
            label_text = f"{clock_face} {strike(item.title, done)}".strip()
            if line[0].button(label_text + tally,
                              key=f"{prefix}open:{item.id}", width="stretch"):
                opened = item, day
            line[1].checkbox("Done", value=done, key=f"{prefix}task:{item.id}",
                             label_visibility="collapsed",
                             on_change=_toggle_task, args=(prefix, item.id, day))

        if tasks.empty:
            st.caption("No tasks assigned.")

        # Ticked off here while its task sits elsewhere. One whose task is on
        # this card is left to it: finishing a task finishes its milestones, so
        # both rows would say the same thing.
        finished = milestones[(milestones["done_on"] == pd.Timestamp(day))
                              & ~milestones["task_id"].isin(tasks["id"])]
        for milestone in finished.itertuples():
            if _milestone_row(milestone, prefix, day, rules):
                opened = db.item(milestone.task_id), day

        st.text_area("Notes", value=field(record, "comment") or "", height=80,
                     key=f"{prefix}comment:{day}", on_change=_save_day,
                     args=(prefix, day))
    return opened


def render_week(week_start: date, records: dict, tasks: pd.DataFrame,
                milestones: pd.DataFrame, prefix: str = "") -> None:
    """Monday to Friday side by side, with the weekend in an expander."""
    opened, rules = None, []

    def card(day: date):
        return render_day(day, records.get(day, {}),
                          tasks[tasks["on_day"] == pd.Timestamp(day)],
                          milestones, prefix, rules)

    for column, offset in zip(st.columns(5), range(5)):
        with column:
            opened = card(week_start + timedelta(days=offset)) or opened

    with st.expander("Weekend", icon=":material/weekend:"):
        for column, offset in zip(st.columns(2), (5, 6)):
            with column:
                opened = card(week_start + timedelta(days=offset)) or opened

    if rules:
        st.html(style_block(rules))
    if opened is not None:
        item, day = opened
        open_item(item, prefix, [NO_PROJECT] + list(db.projects()["name"]), day)
