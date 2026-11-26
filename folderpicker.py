"""A friendly folder (and picture) browser: big rows, quick places, New folder.

The look is in podinventory.kv (<FolderPicker>, <FolderRow>, <FolderIcon>).
The file work is in folders.py, which is tested without a screen.
"""
import os
import time

from kivy.clock import Clock
from kivy.metrics import dp
from kivy.properties import BooleanProperty, ListProperty, NumericProperty, StringProperty
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.widget import Widget

import folders
import storage_access
import theme


class FolderIcon(Widget):
    kind = StringProperty("folder")          # "folder" or "image"
    tint = ListProperty(theme.rgba(theme.TEAL))


class FolderRow(ButtonBehavior, BoxLayout):
    title = StringProperty("")
    sub = StringProperty("")
    kind = StringProperty("folder")
    full_path = StringProperty("")


class PlaceChip(ButtonBehavior, BoxLayout):
    text = StringProperty("")
    full_path = StringProperty("")


PAGE = 40          # rows added at a time, so a folder with thousands of photos stays fast


def _when(stamp):
    return time.strftime("%b %d, %Y", time.localtime(stamp))


class FolderPicker(BoxLayout):
    path = StringProperty("")
    message = StringProperty("")
    need_access = BooleanProperty(False)
    allow_new_folder = BooleanProperty(True)
    show_files = BooleanProperty(False)
    crumb = StringProperty("")

    def __init__(self, start, ask_text, on_file=None, show_files=False, places=(), exts=None, **kwargs):
        self._entries = []
        self._shown = 0
        self._more_row = None
        super().__init__(**kwargs)
        self.ask_text = ask_text            # function(title, hint, ok_text, on_ok)
        self.on_file = on_file
        self.show_files = show_files
        self.allow_new_folder = not show_files
        self.exts = (exts or folders.IMAGE_EXTS) if show_files else None

        for label, folder in folders.shortcut_list(places):
            chip = PlaceChip(text=label, full_path=folder)
            chip.bind(on_release=lambda w: self.open_path(w.full_path))
            self.ids.places.add_widget(chip)
        self.start_path = start
        self.open_path(start)

    # ---------------------------------------------------------------- moving
    def open_path(self, path):
        self.path = path
        self.crumb = folders.pretty_path(path)
        self.reload()

    def go_up(self):
        self.open_path(folders.parent_of(self.path))

    def can_go_up(self):
        """True while 'back' should climb to the parent folder instead of closing."""
        return self.path != self.start_path and folders.parent_of(self.path) != self.path

    def reload(self, *_):
        self.need_access = not storage_access.has_all_files_access()
        box = self.ids.rows
        box.clear_widgets()
        self._more_row = None
        self._entries, self._shown = [], 0
        self.message = ""
        try:
            dirs, files = folders.list_entries(self.path, self.exts)
        except OSError:
            self.message = (
                "This folder can't be opened. Allow access to all files, "
                "or pick another folder."
            )
            return
        self._entries = (
            [(name, "Folder", "folder", full) for name, full in dirs]
            + [(name, _when(stamp), "image", full) for name, full, stamp in files]
        )
        if not self._entries:
            self.message = (
                "No matching files or folders here." if self.show_files
                else "This folder is empty. Tap New folder to make one."
            )
            return
        self.show_more()

    def show_more(self, *_):
        """Add the next page of rows (newest pictures come first)."""
        box = self.ids.rows
        if self._more_row is not None:
            box.remove_widget(self._more_row)
            self._more_row = None
        chunk = self._entries[self._shown:self._shown + PAGE]
        for name, sub, kind, full in chunk:
            box.add_widget(self._row(name, sub, kind, full))
        self._shown += len(chunk)
        left = len(self._entries) - self._shown
        if left > 0:
            self._more_row = FolderRow(title=f"Show more ({left} left)", kind="more")
            self._more_row.bind(on_release=self.show_more)
            box.add_widget(self._more_row)

    def _row(self, title, sub, kind, full):
        row = FolderRow(title=title, sub=sub, kind=kind, full_path=full)
        row.bind(on_release=self._tapped)
        return row

    def _tapped(self, row):
        if row.kind == "folder":
            self.open_path(row.full_path)
        elif self.on_file:
            self.on_file(row.full_path)

    # ------------------------------------------------------------ new folder
    def new_folder(self):
        def on_ok(text):
            new_path, error = folders.make_folder(self.path, text)
            if error:
                return error
            Clock.schedule_once(lambda dt: self.open_path(new_path), 0)
            return ""

        self.ask_text("New folder", "Folder name", "Create", on_ok)

    # ---------------------------------------------------------------- access
    def allow_access(self):
        storage_access.ask_all_files_access()
