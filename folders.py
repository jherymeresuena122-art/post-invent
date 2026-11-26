"""Folder helpers for the file picker. No Kivy in here, so they are easy to test."""
import os

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp")
BACKUP_EXTS = (".podbackup",)
BAD_NAME_CHARS = '\\/:*?"<>|'


def list_entries(path, file_exts=None):
    """Return (folders, files) inside path. Hidden items are skipped.

    folders: [(name, full_path)] A to Z.   files: [(name, full_path, modified)] newest first.
    Only files that end with one of file_exts are listed (none when file_exts is None).
    Raises OSError if the folder cannot be opened.
    """
    folders, files = [], []
    with os.scandir(path) as entries:
        for entry in entries:
            if entry.name.startswith("."):
                continue
            try:
                if entry.is_dir():
                    folders.append((entry.name, entry.path))
                elif file_exts and entry.name.lower().endswith(tuple(file_exts)):
                    files.append((entry.name, entry.path, entry.stat().st_mtime))
            except OSError:
                continue
    folders.sort(key=lambda item: item[0].lower())
    files.sort(key=lambda item: -item[2])
    return folders, files


def parent_of(path):
    """The folder above path. At the top it returns path itself."""
    path = os.path.normpath(path)
    parent = os.path.dirname(path)
    return parent if parent and parent != path else path


def clean_folder_name(name):
    """Returns (clean_name, error). error is '' when the name is fine."""
    name = (name or "").strip().rstrip(". ")
    if not name:
        return "", "Type a name for the folder."
    if any(ch in name for ch in BAD_NAME_CHARS):
        return "", 'A folder name cannot contain  \\ / : * ? " < > |'
    if len(name) > 80:
        return "", "That name is too long."
    return name, ""


def make_folder(parent, name):
    """Create a folder inside parent. Returns (new_path, error)."""
    clean, error = clean_folder_name(name)
    if error:
        return "", error
    path = os.path.join(parent, clean)
    if os.path.exists(path):
        return "", "A folder with that name already exists."
    try:
        os.mkdir(path)
    except OSError as err:
        return "", f"Could not create the folder: {err.strerror or err}"
    return path, ""


def shortcut_list(extra=()):
    """Quick places shown as chips: [(label, path)] for folders that exist."""
    home = os.path.expanduser("~")
    places = list(extra)
    for label in ("Documents", "Downloads", "Pictures", "Desktop"):
        places.append((label, os.path.join(home, label)))
    seen, result = set(), []
    for label, path in places:
        key = os.path.normpath(path)
        if os.path.isdir(path) and key not in seen:
            seen.add(key)
            result.append((label, path))
    return result


def pretty_path(path, max_len=40):
    """Shorten a long path from the left: .../Documents/Pod"""
    path = os.path.normpath(path)
    return path if len(path) <= max_len else "..." + path[-(max_len - 3):]
