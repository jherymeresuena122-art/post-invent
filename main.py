"""The Pod: post-event inventory app.

Run this file in PyCharm to open the app in a phone-sized window.
Screens: choose user, create account, home, event calendar, inventory of the day.
Rules about who may do what live in permissions.py; the look is in podinventory.kv.
"""
import calendar
import os
from datetime import date, datetime

from kivy.app import App
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.properties import (
    BooleanProperty,
    ListProperty,
    NumericProperty,
    StringProperty,
)
from kivy.resources import resource_find
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import Screen, ScreenManager, SlideTransition
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget
from kivy.utils import escape_markup, platform

import theme
from database import Database, EventLockedError
from permissions import (
    ADMIN,
    CREW,
    LEADER,
    ROLE_DESCRIPTIONS,
    can_delete_day,
    can_edit_submitted,
    can_start_day,
    role_label,
    start_denied_reason,
)
from report import build_report, save_report, timestamp_text
from units import DEFAULT_ITEMS, consumed, cup_totals, fmt, parse_number

# On a computer, show the app at roughly the size of a phone screen.
if platform not in ("android", "ios"):
    Window.size = (390, 780)
else:
    # keep the text box visible when the phone keyboard opens
    Window.softinput_mode = "below_target"


# --------------------------------------------------------------- small widgets
class PodButton(Button):
    bg = ListProperty(theme.rgba(theme.TEAL))
    fg = ListProperty([1, 1, 1, 1])


class PodLabel(Label):
    pass


class PodInput(TextInput):
    pass


class TeamToggle(ToggleButton):
    user_id = NumericProperty(0)  # 0 = a crew member typed in by name


class RoleToggle(ToggleButton):
    role_key = StringProperty("")


class TopBar(BoxLayout):
    title = StringProperty("")
    back_to = StringProperty("home")  # which screen the "<" button returns to


class OptionRow(ButtonBehavior, BoxLayout):
    heading = StringProperty("")
    sub = StringProperty("")


class Avatar(FloatLayout):
    """A colored circle with a letter in the middle."""

    letter = StringProperty("")
    tint = ListProperty([1, 1, 1, 1])
    ink = ListProperty([0, 0, 0, 1])
    d = NumericProperty(0)


class UserTile(ButtonBehavior, BoxLayout):
    initial = StringProperty("")
    username = StringProperty("")
    role_text = StringProperty("")
    tint = ListProperty([1, 1, 1, 1])
    ink = ListProperty([0, 0, 0, 1])
    user_id = NumericProperty(0)


class PodScreen(Screen):
    """Base class: every screen gets the paper-colored background."""


class UnitSpinner(Spinner):
    """Drop-down to pick how an item is counted (cups, bags, grams...)."""


class TotalsCard(BoxLayout):
    before_text = StringProperty("-")
    after_text = StringProperty("-")
    used_text = StringProperty("-")


def set_visible(widget, visible, height=None):
    """Show or hide a widget. Hidden ones also stop taking taps and space."""
    widget.opacity = 1 if visible else 0
    widget.disabled = not visible
    if height is not None:
        widget.height = height if visible else 0


# --------------------------------------------------------------------- popups
def confirm_popup(title, message, yes_text, on_yes, height=280):
    """A small 'are you sure?' box."""
    content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(14))
    label = Label(text=message, halign="center", valign="middle")
    label.bind(size=lambda w, s: setattr(w, "text_size", (s[0], None)))
    row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
    popup = Popup(
        title=title,
        content=content,
        size_hint=(0.9, None),
        height=dp(height),
        auto_dismiss=False,
    )
    cancel = PodButton(text="Cancel", bg=theme.rgba(theme.LINE), fg=theme.rgba(theme.INK))
    cancel.bind(on_release=lambda *_: popup.dismiss())

    def _yes(*_):
        popup.dismiss()
        on_yes()

    yes = PodButton(text=yes_text)
    yes.bind(on_release=_yes)
    row.add_widget(cancel)
    row.add_widget(yes)
    content.add_widget(label)
    content.add_widget(row)
    popup.open()


def input_popup(title, hint, ok_text, on_ok, password=False, digits_only=False, max_length=None):
    """Ask for one line of text.

    on_ok(text) must return '' to close the box, or an error text to show in it.
    """
    content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(10))
    field = PodInput(
        hint_text=hint,
        password=password,
        input_filter="int" if digits_only else None,
        write_tab=False,
    )
    if max_length:
        field.bind(text=lambda w, v: setattr(w, "text", v[:max_length]) if len(v) > max_length else None)
    message = PodLabel(text="", font_size="14sp", color=theme.rgba(theme.DANGER))
    row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
    popup = Popup(
        title=title,
        content=content,
        size_hint=(0.9, None),
        height=dp(270),
        auto_dismiss=False,
    )
    cancel = PodButton(text="Cancel", bg=theme.rgba(theme.LINE), fg=theme.rgba(theme.INK))
    cancel.bind(on_release=lambda *_: popup.dismiss())

    def _ok(*_):
        error = on_ok(field.text)
        if error:
            message.text = error
        else:
            popup.dismiss()

    ok = PodButton(text=ok_text)
    ok.bind(on_release=_ok)
    field.bind(on_text_validate=_ok)
    row.add_widget(cancel)
    row.add_widget(ok)
    content.add_widget(field)
    content.add_widget(message)
    content.add_widget(row)
    popup.open()
    Clock.schedule_once(lambda dt: setattr(field, "focus", True), 0.25)


def default_export_folder(app):
    """A sensible place to start looking for where to save the export."""
    if platform == "android":
        try:
            from android.storage import primary_external_storage_path

            folder = os.path.join(primary_external_storage_path(), "Download")
            if os.path.isdir(folder):
                return folder
        except Exception:
            pass
        return app.user_data_dir
    home = os.path.expanduser("~")
    for sub in ("Documents", "Downloads"):
        folder = os.path.join(home, sub)
        if os.path.isdir(folder):
            return folder
    return home


def export_popup(app, data, base_name):
    """Pick PDF or PNG and a folder, then save the day as a picture."""
    content = BoxLayout(orientation="vertical", padding=dp(12), spacing=dp(8))
    formats = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
    png = RoleToggle(text="PNG picture", group="export_format", role_key="png", state="down")
    pdf = RoleToggle(text="PDF file", group="export_format", role_key="pdf")
    formats.add_widget(png)
    formats.add_widget(pdf)

    start = default_export_folder(app)
    path_input = PodInput(text=start, height=dp(44))
    chooser = FileChooserListView(
        path=start,
        dirselect=True,
        filters=[lambda folder, name: os.path.isdir(os.path.join(folder, name))],
    )
    chooser.bind(path=lambda w, value: setattr(path_input, "text", value))
    chooser.bind(selection=lambda w, sel: setattr(path_input, "text", sel[0]) if sel else None)
    message = PodLabel(text="", font_size="13sp", color=theme.rgba(theme.DANGER))

    row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(10))
    popup = Popup(
        title="Export this day",
        content=content,
        size_hint=(0.95, 0.92),
        auto_dismiss=False,
    )
    close = PodButton(text="Close", bg=theme.rgba(theme.LINE), fg=theme.rgba(theme.INK))
    close.bind(on_release=lambda *_: popup.dismiss())

    def _export(*_):
        folder = path_input.text.strip()
        if not os.path.isdir(folder):
            message.color = theme.rgba(theme.DANGER)
            message.text = "That folder does not exist. Pick a folder from the list."
            return
        try:
            image = build_report(
                data,
                resource_find("data/fonts/Roboto-Regular.ttf"),
                resource_find("data/fonts/Roboto-Bold.ttf"),
            )
            path = save_report(image, folder, base_name, "pdf" if pdf.state == "down" else "png")
        except Exception as err:  # show any problem instead of crashing the app
            message.color = theme.rgba(theme.DANGER)
            message.text = f"Could not save: {err}"
            return
        message.color = theme.rgba(theme.TEAL_DARK)
        message.text = f"Saved: {path}"

    export = PodButton(text="Export")
    export.bind(on_release=_export)
    row.add_widget(close)
    row.add_widget(export)

    content.add_widget(PodLabel(text="1. Choose the format", bold=True, font_size="13sp"))
    content.add_widget(formats)
    content.add_widget(PodLabel(text="2. Choose the folder to save in", bold=True, font_size="13sp"))
    content.add_widget(path_input)
    content.add_widget(chooser)
    content.add_widget(message)
    content.add_widget(row)
    popup.open()


# -------------------------------------------------------------------- screens
class ChooseUserScreen(PodScreen):
    def on_pre_enter(self, *args):
        app = App.get_running_app()
        grid = self.ids.grid
        grid.clear_widgets()
        users = app.db.list_users()
        self.ids.empty_hint.opacity = 0 if users else 1
        for i, user in enumerate(users):
            soft, dark = theme.TINTS[i % len(theme.TINTS)]
            tile = UserTile(
                initial=user["name"][:1].upper(),
                username=user["name"],
                role_text=role_label(user["role"]),
                tint=theme.rgba(soft),
                ink=theme.rgba(dark),
                user_id=user["id"],
            )
            tile.bind(on_release=lambda w: app.try_login(w.user_id))
            grid.add_widget(tile)


class CreateAccountScreen(PodScreen):
    def on_pre_enter(self, *args):
        app = App.get_running_app()
        ids = self.ids
        ids.name_input.text = ""
        ids.pin_input.text = ""
        ids.pin2_input.text = ""
        ids.message.text = ""

        has_admin = app.db.has_admin()
        first_user = not app.db.list_users()
        ids.r_admin.disabled = has_admin
        ids.admin_note.text = (
            "A Creator admin already exists on this phone."
            if has_admin
            else "Only one Creator admin can exist."
        )
        if first_user and not has_admin:
            ids.r_admin.state = "down"
        else:
            ids.r_crew.state = "down"
        self.update_role_ui()

    def selected_role(self):
        for toggle in (self.ids.r_admin, self.ids.r_leader, self.ids.r_crew):
            if toggle.state == "down":
                return toggle.role_key
        return CREW

    def update_role_ui(self):
        role = self.selected_role()
        self.ids.role_hint.text = ROLE_DESCRIPTIONS[role]
        needs_pin = role in (ADMIN, LEADER)
        self.ids.pin_label.text = "PIN (required, 4 to 6 digits)" if needs_pin else "PIN (optional)"

    def sign_up(self):
        app = App.get_running_app()
        ids = self.ids
        name = ids.name_input.text.strip()
        role = self.selected_role()
        pin, pin2 = ids.pin_input.text.strip(), ids.pin2_input.text.strip()

        if not name:
            ids.message.text = "Please type your name."
            return
        if role in (ADMIN, LEADER) and not pin:
            ids.message.text = "Creator admin and Team leader need a PIN (4 to 6 digits)."
            return
        if pin:
            if not (pin.isdigit() and 4 <= len(pin) <= 6):
                ids.message.text = "The PIN must be 4 to 6 digits."
                return
            if pin != pin2:
                ids.message.text = "The two PINs do not match."
                return
        try:
            user_id = app.db.add_user(name, role, pin=pin or None)
        except ValueError as err:
            ids.message.text = str(err)
            return
        app.login(user_id)


class HomeScreen(PodScreen):
    def on_pre_enter(self, *args):
        App.get_running_app().refresh_totals()


class CalendarScreen(PodScreen):
    year = NumericProperty(0)
    month = NumericProperty(0)
    selected = StringProperty("")

    def on_pre_enter(self, *args):
        today = date.today()
        self.year, self.month = today.year, today.month
        self.selected = today.isoformat()
        self.refresh()

    def change_month(self, step):
        month = self.month + step
        year = self.year
        if month < 1:
            month, year = 12, year - 1
        elif month > 12:
            month, year = 1, year + 1
        self.year, self.month = year, month
        self.selected = ""
        self.refresh()

    def select(self, date_str):
        self.selected = date_str
        self.refresh()

    def refresh(self):
        app = App.get_running_app()
        ids = self.ids
        ids.month_title.text = f"{calendar.month_name[self.month]} {self.year}"
        status = app.db.month_status(self.year, self.month)
        booked = app.db.month_bookings(self.year, self.month)
        weeks = calendar.Calendar(firstweekday=6).monthdayscalendar(self.year, self.month)

        ids.days.clear_widgets()
        ids.days.height = dp(46) * len(weeks)
        for week in weeks:
            for day in week:
                if day == 0:
                    ids.days.add_widget(Widget(size_hint_y=None, height=dp(42)))
                    continue
                date_str = f"{self.year:04d}-{self.month:02d}-{day:02d}"
                state = status.get(date_str)
                if date_str == self.selected:
                    bg, fg = theme.rgba(theme.TEAL), [1, 1, 1, 1]
                elif state == "submitted":
                    bg, fg = theme.rgba(theme.TEAL_SOFT), theme.rgba(theme.TEAL_DARK)
                elif state == "draft":
                    bg, fg = theme.rgba(theme.ORANGE_SOFT), theme.rgba(theme.ORANGE_DARK)
                elif date_str in booked:
                    bg, fg = theme.rgba(theme.VIOLET_SOFT), theme.rgba(theme.VIOLET_DARK)
                else:
                    bg, fg = theme.rgba(theme.CARD), theme.rgba(theme.INK)
                btn = PodButton(text=str(day), bg=bg, fg=fg, height=dp(42), font_size="15sp")
                btn.bind(on_release=lambda w, d=date_str: self.select(d))
                ids.days.add_widget(btn)
        self.show_detail()

    def show_detail(self):
        app = App.get_running_app()
        ids = self.ids
        role = app.current_user_role
        today = date.today().isoformat()

        if not self.selected:
            ids.detail.text = "Tap a day to see what was recorded."
            set_visible(ids.open_btn, False, dp(52))
            set_visible(ids.book_btn, False, dp(52))
            return

        nice = datetime.strptime(self.selected, "%Y-%m-%d").strftime("%A, %B %d, %Y")
        event = app.db.get_event(self.selected)
        booked = app.db.has_booking(self.selected)

        if event is not None:
            lines = [f"[b]{nice}[/b]", f"Location: {escape_markup(event['location'])}"]
            for it in app.db.get_items(event["id"]):
                used = consumed(it["before"], it["after"])
                lines.append(
                    f"{escape_markup(it['name'])}: {fmt(it['before'])} before, "
                    f"{fmt(it['after'])} after, [b]{fmt(used)} {it['unit']} consumed[/b]"
                )
            names = [u["name"] for u in app.db.get_team(event["id"])]
            names += app.db.get_crew_names(event["id"])
            crew = ", ".join(escape_markup(n) for n in names) or "none"
            lines.append(f"Crew: {crew}")
            if event["submitted_at"]:
                who = app.db.get_user(event["submitted_by"])
                who_name = escape_markup(who["name"]) if who else "unknown"
                lines.append(f"Submitted by {who_name} on {event['submitted_at'].replace('T', ' ')}")
                edits = [e for e in app.db.get_log(event["id"]) if e["action"] == "admin_edit"]
                if edits:
                    last = edits[-1]
                    lines.append(
                        f"[b]Edited by admin {escape_markup(last['user_name'] or 'unknown')} "
                        f"on {last['created_at'].replace('T', ' ')} ({len(edits)} edit(s))[/b]"
                    )
                open_text = "View this day"
            else:
                lines.append("Status: draft, not submitted yet")
                open_text = (
                    "Continue this day" if can_start_day(role, self.selected, today) else "View this day"
                )
            ids.detail.text = "\n".join(lines)
            ids.open_btn.text = open_text
            set_visible(ids.open_btn, True, dp(52))
            set_visible(ids.book_btn, False, dp(52))
            return

        reason = start_denied_reason(role, self.selected, today)
        lines = [
            f"[b]{nice}[/b]",
            "Pending work day, not started yet." if booked else "No record for this day yet.",
        ]
        if reason:
            lines.append(escape_markup(reason))
        ids.detail.text = "\n".join(lines)

        ids.open_btn.text = "Start this day"
        set_visible(ids.open_btn, True, dp(52))
        if reason:
            ids.open_btn.disabled = True
            ids.open_btn.opacity = 0.4

        if booked:
            ids.book_btn.text = "Remove pending work day"
            set_visible(ids.book_btn, True, dp(52))
        elif self.selected >= today:
            ids.book_btn.text = "Mark as pending work day"
            set_visible(ids.book_btn, True, dp(52))
        else:
            set_visible(ids.book_btn, False, dp(52))

    def open_selected(self):
        app = App.get_running_app()
        app.target_date = self.selected
        app.go("create_day")

    def toggle_booking(self):
        app = App.get_running_app()
        if app.db.has_booking(self.selected):
            app.db.remove_booking(self.selected)
        else:
            try:
                app.db.add_booking(self.selected, app.current_user_id)
            except ValueError:
                pass
        app.refresh_totals()
        self.refresh()


class ItemRow(BoxLayout):
    """One inventory line: name, unit, before, after, and what was consumed."""

    consumed_text = StringProperty("")
    warn = BooleanProperty(False)

    def __init__(self, screen, name="", unit="items", before="", after="", **kwargs):
        super().__init__(**kwargs)
        self.screen = screen
        ids = self.ids
        ids.name_input.text = name
        ids.unit_spinner.text = unit
        ids.before_input.text = before
        ids.after_input.text = after
        ids.before_input.bind(text=lambda *_: self.recalc())
        ids.after_input.bind(text=lambda *_: self.recalc())
        ids.unit_spinner.bind(text=lambda *_: self.recalc())
        self.recalc()

    @property
    def item_name(self):
        return self.ids.name_input.text.strip()

    @property
    def item_unit(self):
        return self.ids.unit_spinner.text

    @property
    def before(self):
        return parse_number(self.ids.before_input.text)

    @property
    def after(self):
        return parse_number(self.ids.after_input.text)

    @property
    def used(self):
        return consumed(self.before, self.after)

    def recalc(self):
        used = self.used
        if used is None:
            self.warn = False
            self.consumed_text = "Fill in before and after to see what was consumed."
        elif used < 0:
            self.warn = True
            self.consumed_text = (
                f"Check this: {fmt(self.after)} left is more than {fmt(self.before)} before."
            )
        else:
            self.warn = False
            self.consumed_text = f"Consumed: {fmt(used)} {self.item_unit}"
        self.screen.update_summary()

    def remove(self):
        self.screen.remove_row(self)


def _text(value):
    """Number -> text for an input box ('' when nothing was entered)."""
    return "" if value is None else f"{value:g}"


class CreateDayScreen(PodScreen):
    event_id = NumericProperty(0)
    editable = BooleanProperty(False)       # may this person change an unsubmitted day?
    submitted = BooleanProperty(False)
    admin_editing = BooleanProperty(False)  # the Creator admin unlocked a submitted day
    totals_card = None
    team_toggles = ()

    def on_pre_enter(self, *args):
        app = App.get_running_app()
        date_str = app.target_date or date.today().isoformat()
        app.target_date = ""
        self.load_day(date_str)

    # ------------------------------------------------------------ rows
    def item_rows(self):
        """Item rows in the order they appear on screen (top to bottom)."""
        return [w for w in reversed(self.ids.items_box.children) if isinstance(w, ItemRow)]

    def add_row(self, name="", unit="items", before="", after=""):
        row = ItemRow(self, name, unit, before, after)
        self.ids.items_box.add_widget(row)  # new widgets land at the bottom
        self.update_summary()
        return row

    def add_custom_item(self):
        self.add_row()

    def remove_row(self, row):
        self.ids.items_box.remove_widget(row)
        self.update_summary()

    def _place_totals(self):
        """Put the cups total card right under the last row counted in cups."""
        box = self.ids.items_box
        rows = self.item_rows()
        last_cups = -1
        for position, row in enumerate(rows):
            if row.item_unit == "cups":
                last_cups = position
        # children are stored bottom-to-top, so count the rows below the card
        index = len(rows) - (last_cups + 1) if last_cups >= 0 else 0
        box.add_widget(self.totals_card, index=index)

    def update_summary(self):
        card = self.totals_card
        if card is None:
            return
        data = [
            {"unit": r.item_unit, "before": r.before, "after": r.after} for r in self.item_rows()
        ]
        before, after, used = cup_totals(data)
        card.before_text, card.after_text, card.used_text = fmt(before), fmt(after), fmt(used)

    # ------------------------------------------------------------ crew chips
    def _add_chip(self, text, user_id, down):
        toggle = TeamToggle(text=text, user_id=user_id)
        toggle.state = "down" if down else "normal"
        toggle.disabled = not self._fields_on()
        self.team_toggles.append(toggle)
        self.ids.team_box.add_widget(toggle)

    def add_crew_member(self):
        def on_ok(text):
            name = text.strip()
            if not name:
                return "Type the crew member's name."
            if any(t.text.lower() == name.lower() for t in self.team_toggles):
                return "That name is already on the list."
            self._add_chip(name, 0, True)
            return ""

        input_popup("Add crew member", "Name", "Add", on_ok)

    # ------------------------------------------------------------ loading
    def _fields_on(self):
        return (self.editable and not self.submitted) or self.admin_editing

    def load_day(self, date_str):
        app = App.get_running_app()
        ids = self.ids
        role = app.current_user_role
        today = date.today().isoformat()
        event = app.db.get_event(date_str)

        self.event_id = event["id"] if event else 0
        self.submitted = bool(event and event["submitted_at"])
        self.admin_editing = False
        self.editable = (not self.submitted) and can_start_day(role, date_str, today)

        items, crew_names = [], []
        team_ids = {app.current_user_id} if date_str == today else set()
        if event is not None:
            items = app.db.get_items(event["id"])
            team_ids = {u["id"] for u in app.db.get_team(event["id"])}
            crew_names = app.db.get_crew_names(event["id"])

        ids.date_input.text = date_str
        ids.loc_input.text = event["location"] if event else ""

        ids.items_box.clear_widgets()
        self.totals_card = TotalsCard()
        if items:
            for it in items:
                self.add_row(it["name"], it["unit"], _text(it["before"]), _text(it["after"]))
        else:
            for name, unit in DEFAULT_ITEMS:  # a new day starts with the usual items
                self.add_row(name, unit)
        self._place_totals()
        self.update_summary()

        ids.team_box.clear_widgets()
        self.team_toggles = []
        for user in app.db.list_users():
            self._add_chip(user["name"], user["id"], user["id"] in team_ids)
        for name in crew_names:
            self._add_chip(name, 0, True)

        self.apply_mode()
        ids.status.text = ""
        if self.submitted:
            who = app.db.get_user(event["submitted_by"])
            who_name = who["name"] if who else "unknown"
            extra = (
                " Tap 'Edit this day (admin)' to change it."
                if can_edit_submitted(role)
                else " Only the Creator admin can change it."
            )
            self._say(
                f"Locked. Submitted by {who_name} on "
                f"{event['submitted_at'].replace('T', ' ')}.{extra}",
                good=True,
            )
        elif not self.editable:
            self._say(start_denied_reason(role, date_str, today))

    def apply_mode(self):
        """Turn fields and buttons on or off to match what this person may do."""
        app = App.get_running_app()
        role = app.current_user_role
        ids = self.ids
        fields_on = self._fields_on()

        for widget in (ids.loc_input, ids.add_item_btn, ids.add_crew_btn):
            widget.disabled = not fields_on
            widget.opacity = 1 if fields_on else 0.6
        for row in self.item_rows():
            row.disabled = not fields_on
        for toggle in self.team_toggles:
            toggle.disabled = not fields_on

        ids.save_btn.text = "Save changes (admin)" if self.admin_editing else "Save draft"
        set_visible(ids.save_btn, fields_on, dp(52))
        set_visible(ids.submit_btn, fields_on and not self.submitted, dp(52))
        set_visible(
            ids.unlock_btn,
            self.submitted and can_edit_submitted(role) and not self.admin_editing,
            dp(52),
        )
        set_visible(ids.delete_btn, self.event_id > 0 and can_delete_day(role), dp(52))

    # ------------------------------------------------------------ actions
    def _collect(self, strict=False):
        """Read the form. strict=True is used for submitting and admin edits."""
        ids = self.ids
        date_str = ids.date_input.text.strip()
        location = ids.loc_input.text.strip()
        if not location:
            raise ValueError("Please type the event location.")

        items, seen, warnings = [], set(), []
        for row in self.item_rows():
            name = row.item_name
            if not name:
                raise ValueError("Every item needs a name. Fill it in or remove the row.")
            if name.lower() in seen:
                raise ValueError(f"'{name}' is listed twice. Rename or remove one.")
            seen.add(name.lower())
            if strict and (row.before is None or row.after is None):
                raise ValueError(f"Fill in both before and after for {name}.")
            if row.used is not None and row.used < 0:
                warnings.append(
                    f"{name}: {fmt(row.after)} left is more than {fmt(row.before)} before"
                )
            items.append(
                {"name": name, "unit": row.item_unit, "before": row.before, "after": row.after}
            )
        if strict and not items:
            raise ValueError("Add at least one item.")

        team_ids = [t.user_id for t in self.team_toggles if t.state == "down" and t.user_id]
        crew_names = [t.text for t in self.team_toggles if t.state == "down" and not t.user_id]
        if strict and not team_ids and not crew_names:
            raise ValueError("Select or add at least one crew member who worked this day.")
        return date_str, location, items, team_ids, crew_names, warnings

    def _say(self, text, good=False):
        self.ids.status.color = theme.rgba(theme.TEAL_DARK if good else theme.DANGER)
        self.ids.status.text = text

    def save_draft(self):
        app = App.get_running_app()
        if not self._fields_on():
            self._say("You are not allowed to change this day.")
            return
        try:
            date_str, location, items, team_ids, crew_names, _ = self._collect(
                strict=self.admin_editing
            )
            self.event_id = app.db.save_event(
                date_str, location, items, team_ids, app.current_user_id,
                crew_names=crew_names,
                allow_locked=self.admin_editing,
                editor_id=app.current_user_id,
            )
        except (ValueError, EventLockedError) as err:
            self._say(str(err))
            return
        app.refresh_totals()
        if self.admin_editing:
            self.load_day(date_str)
            self._say("Changes saved and written to this day's history.", good=True)
        else:
            self.apply_mode()
            self._say("Draft saved. You can come back and keep editing it.", good=True)

    def ask_submit(self):
        if not self._fields_on() or self.submitted:
            self._say("You are not allowed to submit this day.")
            return
        try:
            *_, warnings = self._collect(strict=True)
        except ValueError as err:
            self._say(str(err))
            return
        message = (
            "After you submit, this day is locked and cannot be edited.\n"
            "Check the numbers and the crew first."
        )
        height = 280
        if warnings:
            message += "\n\nThese look odd:\n" + "\n".join(warnings)
            height = 280 + 28 * len(warnings)
        confirm_popup("Submit this day?", message, "Yes, submit", self.submit, height)

    def submit(self):
        app = App.get_running_app()
        try:
            date_str, location, items, team_ids, crew_names, _ = self._collect(strict=True)
            event_id = app.db.save_event(
                date_str, location, items, team_ids, app.current_user_id, crew_names=crew_names
            )
            app.db.submit_event(event_id, app.current_user_id)
        except (ValueError, EventLockedError) as err:
            self._say(str(err))
            return
        app.refresh_totals()
        self.load_day(date_str)

    def unlock_for_admin(self):
        app = App.get_running_app()
        if not (self.submitted and can_edit_submitted(app.current_user_role)):
            return
        self.admin_editing = True
        self.apply_mode()
        self._say(
            "Admin edit mode. Every change you save is written to this day's history.",
            good=True,
        )

    def ask_delete(self):
        confirm_popup(
            "Delete this day?",
            "This removes the day, its inventory and its crew list for good.\n"
            "A line in the history will say who deleted it.",
            "Yes, delete",
            self.delete_day,
            300,
        )

    def delete_day(self):
        app = App.get_running_app()
        if not (self.event_id and can_delete_day(app.current_user_role)):
            return
        try:
            app.db.delete_event(self.event_id, app.current_user_id)
        except ValueError as err:
            self._say(str(err))
            return
        app.refresh_totals()
        app.go("calendar", "right")

    def export_day(self):
        app = App.get_running_app()
        try:
            date_str, location, items, team_ids, crew_names, _ = self._collect()
        except ValueError as err:
            self._say(str(err))
            return

        event = app.db.get_event(date_str)
        if event is not None and event["submitted_at"]:
            who = app.db.get_user(event["submitted_by"])
            status_text = (
                f"Submitted by {who['name'] if who else 'unknown'} "
                f"on {event['submitted_at'].replace('T', ' ')}"
            )
        elif event is not None:
            status_text = "Draft, not submitted yet"
        else:
            status_text = "Not saved yet"

        history = []
        if event is not None:
            labels = {
                "created": "created",
                "submitted": "submitted",
                "admin_edit": "edited by admin",
                "deleted": "deleted",
            }
            for entry in app.db.get_log(event["id"]):
                line = (
                    f"{entry['created_at'].replace('T', ' ')}  "
                    f"{labels.get(entry['action'], entry['action'])} by {entry['user_name'] or 'unknown'}"
                )
                if entry["detail"]:
                    line += f": {entry['detail']}"
                history.append(line)

        names = [u["name"] for u in app.db.list_users() if u["id"] in team_ids] + crew_names
        rows = [
            dict(it, used=consumed(it["before"], it["after"])) for it in items
        ]
        has_cups = any(it["unit"] == "cups" for it in items)
        data = {
            "title": "Post-event inventory report",
            "date_text": datetime.strptime(date_str, "%Y-%m-%d").strftime("%A, %B %d, %Y"),
            "location": location,
            "crew_text": ", ".join(names) or "none listed",
            "status_text": status_text,
            "items": rows,
            "cups": cup_totals(items) if has_cups else None,
            "history": history,
            "generated_text": timestamp_text(),
        }
        export_popup(app, data, f"Pod_inventory_{date_str}")


# ------------------------------------------------------------------------ app
class PodInventoryApp(App):
    current_user_id = NumericProperty(0)
    current_user_name = StringProperty("")
    current_user_role = StringProperty(CREW)       # ADMIN, LEADER or CREW
    current_user_role_text = StringProperty("")
    current_user_initial = StringProperty("")
    total_events = NumericProperty(0)
    next_duty_text = StringProperty("")
    target_date = StringProperty("")

    def build(self):
        self.title = "The Pod Inventory"
        self.db = Database(os.path.join(self.user_data_dir, "pod_inventory.db"))
        manager = ScreenManager(transition=SlideTransition(duration=0.18))
        manager.add_widget(ChooseUserScreen(name="choose"))
        manager.add_widget(CreateAccountScreen(name="create_account"))
        manager.add_widget(HomeScreen(name="home"))
        manager.add_widget(CalendarScreen(name="calendar"))
        manager.add_widget(CreateDayScreen(name="create_day"))
        return manager

    def go(self, screen_name, direction="left"):
        self.root.transition.direction = direction
        self.root.current = screen_name

    def refresh_totals(self):
        self.total_events = self.db.count_events()
        upcoming = self.db.next_booking(date.today().isoformat())
        if upcoming:
            nice = datetime.strptime(upcoming, "%Y-%m-%d").strftime("%a, %b %d")
            self.next_duty_text = f"Next pending work day: {nice}"
        else:
            self.next_duty_text = "No pending work days booked"

    def try_login(self, user_id):
        """Open a profile. Profiles with a PIN ask for it first."""
        user = self.db.get_user(user_id)
        if user is None:
            return
        if not user["pin_hash"]:
            self.login(user_id)
            return

        def check(pin):
            if self.db.verify_pin(user_id, pin):
                self.login(user_id)
                return ""
            return "Wrong PIN. Try again."

        input_popup(
            f"PIN for {user['name']}", "PIN", "Open", check,
            password=True, digits_only=True, max_length=6,
        )

    def login(self, user_id):
        user = self.db.get_user(user_id)
        if user is None:
            return
        self.current_user_id = user["id"]
        self.current_user_name = user["name"]
        self.current_user_role = user["role"]
        self.current_user_role_text = role_label(user["role"])
        self.current_user_initial = user["name"][:1].upper()
        self.refresh_totals()
        self.go("home")

    def logout(self):
        self.current_user_id = 0
        self.current_user_name = ""
        self.current_user_role = CREW
        self.current_user_role_text = ""
        self.go("choose", "right")


if __name__ == "__main__":
    PodInventoryApp().run()
