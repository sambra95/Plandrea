"""Project colours: how they are handed out, and how a project reads on screen.

Streamlit's named badge colours only run to seven, which is fewer than a year's
worth of projects, so colours are stored as hex and drawn with Markdown's custom
colour syntax. Every project gets a colour no other project holds.
"""

from __future__ import annotations

import colorsys
import re

import pandas as pd

#: Distinct hues, muted to sit against the warm background.
PALETTE = [
    "#4E86E3",  # blue        #14B8A6 teal onwards are the extras that take
    "#32B562",  # green       a project list past the seven named colours
    "#DE9822",  # orange
    "#DE5555",  # red
    "#916BE7",  # violet
    "#D3A71F",  # yellow
    "#727279",  # gray
    "#24A899",  # teal
    "#DC5899",  # pink
    "#249DD3",  # sky
    "#80BA28",  # lime
    "#A865E7",  # purple
    "#E2772D",  # deep orange
    "#1BA7BF",  # cyan
    "#CD3153",  # rose
    "#687587",  # slate
]

#: Named colours that may still be stored, and their hex.
LEGACY = {"blue": PALETTE[0], "green": PALETTE[1], "orange": PALETTE[2],
          "red": PALETTE[3], "violet": PALETTE[4], "yellow": PALETTE[5],
          "gray": PALETTE[6], "grey": PALETTE[6]}

DEFAULT_COLOUR = PALETTE[0]

#: What an archived project turns. Not in PALETTE, so archiving frees a colour
#: rather than spending one.
ARCHIVED_COLOUR = "#AEA185"

#: What a project selector shows for no project.
NO_PROJECT = "-"

#: What a day off is washed in. Deliberately outside PALETTE, so a holiday
#: cannot be taken for a project on a calendar painted by project.
HOLIDAY_COLOUR = "#8C9A5B"

#: A holiday colours a whole calendar cell rather than a chip, so it sits a
#: little stronger than a project's wash or it vanishes into the page.
HOLIDAY_ALPHA = 0.22

#: How much colour washes into a card, a chip or a badge.
WASH_ALPHA = 0.16

#: Outline of a bordered section.
BORDER_WIDTH = "2px"

#: Only bordered containers have a border style, so this shows on those alone.
SECTION_CSS = (f'<style>[data-testid="stVerticalBlock"] '
               f'{{ border-width: {BORDER_WIDTH}; }}</style>')

#: What an input is filled with, matching a button. `secondaryBackgroundColor`
#: covers widgets and containers alike, so config cannot separate them.
INPUT_FILL = "#FFFFFF"

INPUT_CSS = f"""<style>
[data-testid="stTextInputRootElement"],
[data-testid="stTextAreaRootElement"],
[data-testid="stNumberInputContainer"],
[data-testid="stDateInputField"],
[data-testid="stTimeInputTimeDisplay"],
[data-testid="stSelectbox"] > div,
/* the select paints two nested divs, not one */
[data-testid="stSelectbox"] > div > div {{ background-color: {INPUT_FILL}; }}
</style>"""

#: How big a tick box is. Streamlit's own is 1rem, small to aim at down a long
#: checklist. The tick inside is a share of the box and grows with it.
CHECKBOX_SIZE = "1.4rem"

#: What a holiday box keeps: it sits beside its word in a day card's header,
#: where there is no room to spare, and a bigger box crowds the word out.
HOLIDAY_CHECKBOX_SIZE = "1rem"

#: Streamlit gives the box no name of its own; it is the div in front of the
#: widget's label, which is there whether the label shows or not. The holiday
#: box is picked out by the key its day card gives it.
CHECKBOX_CSS = f"""<style>
[data-testid="stCheckbox"] div:has(~ [data-testid="stWidgetLabel"]) {{
    width: {CHECKBOX_SIZE};
    height: {CHECKBOX_SIZE};
    /* The margin Streamlit centres it with is worked out from the old size.
       Centring it in the row instead holds for any size. */
    margin-top: 0;
    align-self: center;
}}
[class*="-holiday-"] [data-testid="stCheckbox"]
                     div:has(~ [data-testid="stWidgetLabel"]) {{
    width: {HOLIDAY_CHECKBOX_SIZE};
    height: {HOLIDAY_CHECKBOX_SIZE};
}}
</style>"""

#: Mirrors `borderColor` in .streamlit/config.toml, which CSS cannot read.
BORDER_COLOUR = "#C8BFAA"

#: Bar height; has to clear the tabs inside it.
NAV_HEIGHT = "72px"

#: Between tabs, so neighbouring highlights do not run together.
NAV_GAP = "10px"

NAV_CSS = f"""<style>
.stAppHeader {{
    /* Tall enough to hold a tab: the bar is 53px by default and the tabs are
       taller than that, so without this the active tab's highlight hangs over
       the divider instead of sitting inside the bar. */
    min-height: {NAV_HEIGHT};
    border-bottom: 1px solid {BORDER_COLOUR} !important;
    box-shadow: 0 2px 6px rgba(31, 36, 48, 0.06) !important;
}}
.stAppHeader .rc-overflow {{ width: 100%; gap: {NAV_GAP}; }}
.stAppHeader .rc-overflow-item {{ flex: 1 1 0; min-width: 0; }}
/* Streamlit keeps 175px here for the Deploy button, which is hidden; without
   this the tabs stop short of the right edge and sit off centre. */
.stAppHeader div:has(> [data-testid="stToolbarActions"]) {{ min-width: auto; }}
.stAppHeader .rc-overflow-item > div,
.stAppHeader [data-testid="stTopNavLinkContainer"] {{ width: 100%; }}
.stAppHeader [data-testid="stTopNavLink"] {{
    width: 100%;
    justify-content: center;
    padding: 14px 4px !important;
}}
.stAppHeader [data-testid="stTopNavLink"] span {{ font-size: 1.2rem !important; }}
/* Clicking the logo goes to the home page by default and no parameter turns
   that off. Away from the home page Streamlit wraps it in a button; the image
   itself is never the target. */
[data-testid="stLogoLink"] {{ pointer-events: none; }}
</style>"""

#: Golden angle: successive hues land as far apart as possible.
_GOLDEN = 0.6180339887498949


def as_hex(colour) -> str:
    """A stored colour as hex, whether it was saved as a name or already hex."""
    if colour is None or (isinstance(colour, float) and pd.isna(colour)):
        return DEFAULT_COLOUR
    colour = str(colour)
    return colour if colour.startswith("#") else LEGACY.get(colour, DEFAULT_COLOUR)


def next_colour(used) -> str:
    """A colour no existing project holds: the palette in order, then the hue
    wheel by golden angle until one is free."""
    taken = {as_hex(colour) for colour in used}
    for colour in PALETTE:
        if colour not in taken:
            return colour
    step = len(taken)
    while True:
        colour = _hex(colorsys.hls_to_rgb((step * _GOLDEN) % 1.0, 0.58, 0.62))
        if colour not in taken:
            return colour
        step += 1


def css_class(key: str) -> str:
    """The class Streamlit gives a keyed widget: "week:open:3" becomes
    "st-key-week-open-3". Selectors must be built from this, not the key."""
    return "st-key-" + re.sub(r"[^A-Za-z0-9_-]", "-", key)


def _channels(colour: str) -> tuple[int, int, int]:
    """A hex colour as its three channels."""
    return tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5))


def _hex(channels) -> str:
    """Three channels, each 0 to 1, back as hex."""
    return "#" + "".join(f"{round(channel * 255):02X}" for channel in channels)


def _rgba(colour: str, alpha: float) -> str:
    """Hex as a comma-separated rgba(), the form Streamlit's Markdown accepts."""
    red, green, blue = _channels(colour)
    return f"rgba({red},{green},{blue},{alpha})"


def badge(name, colour) -> str:
    """A project as a coloured chip, or nothing when a task has no project."""
    if not name or pd.isna(name):
        return ""
    tint = as_hex(colour)
    return (f':color[{name}]{{foreground="{tint}" '
            f'background="{_rgba(tint, WASH_ALPHA)}"}}')


def wash(colour) -> str:
    """A project colour at the wash alpha, for anything coloured directly rather
    than through a stylesheet."""
    return _rgba(as_hex(colour), WASH_ALPHA)


def strike(text: str, done: bool) -> str:
    """Text struck through once it is finished."""
    return f"~~{text}~~" if done else text


def lightened(colour: str, amount: float = 0.05) -> str:
    """`colour` with its lightness raised. Streamlit fills a plain button with
    the page background lightened this far, and offers no variable to borrow."""
    hue, light, saturation = colorsys.rgb_to_hls(
        *(channel / 255 for channel in _channels(colour)))
    return _hex(colorsys.hls_to_rgb(hue, min(1.0, light + amount), saturation))


def chip_css(key: str, colour) -> str:
    """CSS making one `st.button(key=...)` read as a project chip: the project's
    colour on a wash of it, rather than a default grey button. With no project
    there is no colour to wash it in, so it keeps the page behind it and simply
    loses its outline."""
    if colour is None or pd.isna(colour):
        return f'.{css_class(key)} button {{ border-color: transparent !important; }}'
    tint = as_hex(colour)
    return (f'.{css_class(key)} button {{ '
            f'background-color: {_rgba(tint, WASH_ALPHA)} !important; '
            f'color: {tint} !important; border-color: transparent !important; }}')


def chip_date_css(key: str, day) -> str:
    """CSS setting a chip's day at its far right. A button's label is markdown
    and cannot hold a second, right-aligned element, so the button draws the
    day itself; an unseen copy at the far left keeps the title centred and
    stops a long one running under the day."""
    chip = f".{css_class(key)} button"
    return (f'{chip} {{ justify-content: space-between; gap: 0.75rem; }} '
            f'{chip}::before, {chip}::after {{ content: "{day:%a %d %b}"; '
            f'flex: none; }} '
            f'{chip}::before {{ visibility: hidden; }}')


def label(title: str, name, colour, done: bool = False) -> str:
    """A task's title behind its project chip. Only the title is struck: the
    chip is a colour directive and tildes would stop it rendering."""
    return f"{badge(name, colour)} {strike(title, done)}".strip()


def select_css(key: str, colour) -> str:
    """CSS painting one `st.selectbox(key=...)` in the colour of the project it
    is showing. Two nested divs, as INPUT_CSS fills the same pair."""
    tint = as_hex(colour)
    return (f'.{css_class(key)} [data-testid="stSelectbox"] > div, '
            f'.{css_class(key)} [data-testid="stSelectbox"] > div > div {{ '
            f'background-color: {_rgba(tint, WASH_ALPHA)} !important; '
            f'color: {tint} !important; border-color: transparent !important; }}')


def done_css(key: str) -> str:
    """CSS washing one `st.text_input(key=...)` green, for something finished
    whose name is still there to edit."""
    return (f'.{css_class(key)} [data-testid="stTextInputRootElement"] {{ '
            f'background-color: {wash(LEGACY["green"])} !important; }}')


def holiday_css(key: str) -> str:
    """CSS marking one keyed container as a day off: the holiday colour washed
    over the whole cell, with its border picked out in the same colour so the
    day still reads as bordered rather than merely tinted."""
    return (f'.{css_class(key)} {{ '
            f'background-color: {_rgba(HOLIDAY_COLOUR, HOLIDAY_ALPHA)} !important; '
            f'border-color: {_rgba(HOLIDAY_COLOUR, 0.55)} !important; }}')


def style_block(rules: list[str]) -> str:
    """A page's card rules as one style element, empty when there are none."""
    return "<style>" + "\n".join(rules) + "</style>" if rules else ""


#: Enter starts the next bullet in every text area and Tab makes one a
#: sub-bullet: a point at the top level, a dash under it. Streamlit cannot see
#: a keypress inside one, so the page does it, writing the value the way React
#: listens for. db.as_bullets tidies the same text on save, marks and all.
BULLET_JS = """<script>
(() => {
  // st.html runs again on every rerun, so without this the listeners stack up
  // and one Enter inserts one bullet per rerun that has happened.
  if (window.plandreaBullets) return;
  window.plandreaBullets = true;

  const ours = (box) => box.tagName === "TEXTAREA";
  // What one level of indent is worth, and how to find the line a caret is on.
  const STEP = "  ";
  // A top-level bullet is a point; everything under it is a dash. Both are two
  // characters wide, so a line keeps its width when it changes level.
  const MARK = /^(?:\u2022 |- )/;
  const mark = (indent) => indent ? "- " : "\u2022 ";
  const lineStart = (value, at) =>
      at === 0 ? 0 : value.lastIndexOf("\\n", at - 1) + 1;
  const lineEnd = (value, at) => {
    const stop = value.indexOf("\\n", at);
    return stop === -1 ? value.length : stop;
  };
  const indentOf = (value, at) =>
      value.slice(lineStart(value, at)).match(/^ */)[0];
  const write = (box, value, caret) => {
    const setter = Object.getOwnPropertyDescriptor(
        window.HTMLTextAreaElement.prototype, "value").set;
    setter.call(box, value);
    box.dispatchEvent(new Event("input", {bubbles: true}));
    box.setSelectionRange(caret, caret);
  };
  document.addEventListener("keydown", (event) => {
    const box = event.target;
    // Shift+Enter is a plain newline, and Cmd/Ctrl+Enter is how Streamlit
    // applies a text area: leave all of those alone.
    if (!ours(box) || event.key !== "Enter" || event.shiftKey
        || event.metaKey || event.ctrlKey || event.altKey) return;
    event.preventDefault();
    const at = box.selectionStart;
    // The next bullet starts at the depth of the one it follows, so it is
    // marked the way that depth is marked.
    const ahead = indentOf(box.value, at);
    const added = "\\n" + ahead + mark(ahead);
    write(box, box.value.slice(0, at) + added + box.value.slice(box.selectionEnd),
          at + added.length);
  }, true);
  const indent = (event) => {
    const box = event.target;
    // Tab takes a bullet one level in, Shift+Tab one level back out. Inside a
    // text area that is worth more than moving the focus on, so the key is
    // stopped dead: the default would tab away, and Streamlit's own handlers
    // would too if the event reached them.
    if (!ours(box) || event.key !== "Tab"
        || event.metaKey || event.ctrlKey || event.altKey) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (event.type !== "keydown") return;   // keyup only has to be swallowed
    const at = box.selectionStart;
    const start = lineStart(box.value, at);
    const line = box.value.slice(start, lineEnd(box.value, at));
    const was = line.match(/^ */)[0];
    if (event.shiftKey && was.length < STEP.length) return;   // already out
    const now = event.shiftKey ? was.slice(STEP.length) : was + STEP;
    const body = line.slice(was.length).replace(MARK, "");
    const line2 = now + mark(now) + body;
    const caret = Math.min(
        Math.max(at + line2.length - line.length, start + now.length + 2),
        start + line2.length);
    write(box, box.value.slice(0, start) + line2
               + box.value.slice(start + line.length), caret);
    // Writing the value re-renders the box, which can drop the focus on the
    // way past. Take it back once that has settled.
    requestAnimationFrame(() => {
      if (document.activeElement !== box) box.focus();
      box.setSelectionRange(caret, caret);
    });
  };
  document.addEventListener("keydown", indent, true);
  document.addEventListener("keyup", indent, true);
  document.addEventListener("input", (event) => {
    const box = event.target;
    // An indented first line is already a bullet, so match past the spaces.
    if (!ours(box) || box.value === ""
        || MARK.test(box.value.replace(/^ */, ""))) return;
    const ind = box.value.match(/^ */)[0];
    write(box, ind + mark(ind) + box.value.slice(ind.length),
          box.selectionStart + 2);
  }, true);
})();
</script>"""

