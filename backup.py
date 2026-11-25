"""Backup file for The Pod: one .podbackup file holds every account (with its
PIN, so the same PIN still works), every work day, the history and the
profile pictures.

The file is a zip with three kinds of parts:
    manifest.json      what it is, when it was made, a checksum of data.json
    data.json          every table as plain rows (column name -> value)
    avatars/<id>.jpg   profile pictures

Rows are stored by column NAME, not by position, and restoring only fills the
columns the new version of the app knows. So a backup made by an old version
still restores after the app gets new columns - that is what makes the file
usable "no matter how many times the app updates".
"""
import hashlib
import json
import os
import shutil
import zipfile
from contextlib import closing
from datetime import datetime

from permissions import ADMIN, CREW, LEADER

APP_ID = "the-pod-inventory"
FORMAT = 2            # 2 = adds "scope" (everything / one account); 1 files still restore
EXTENSION = ".podbackup"
TABLES = [
    "users", "events", "event_team", "event_crew",
    "inventory_items", "photos", "bookings", "event_log",
]
MAX_DATA_BYTES = 100 * 1024 * 1024
MAX_AVATAR_BYTES = 5 * 1024 * 1024


class BackupError(Exception):
    """The file is not a usable backup. The message is safe to show the user."""


def suggested_name(now=None, who=None):
    now = now or datetime.now()
    if who:
        safe = "".join(c if c.isalnum() else "-" for c in who).strip("-").lower() or "account"
        return f"the-pod-{safe}-{now:%Y-%m-%d_%H%M}{EXTENSION}"
    return f"the-pod-backup-{now:%Y-%m-%d_%H%M}{EXTENSION}"


def _rows(conn, table):
    return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]


def _account_data(conn, user_id):
    """Everything one account owns: its profile, its own days and bookings.

    People are written by NAME (not id) because ids differ from phone to phone."""
    users = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM users")}
    data = {t: [] for t in TABLES}
    data["users"] = [dict(r) for r in conn.execute("SELECT * FROM users WHERE id = ?", (user_id,))]
    events = [dict(r) for r in conn.execute("SELECT * FROM events WHERE created_by = ?", (user_id,))]
    ids = [e["id"] for e in events]
    for e in events:
        e["submitted_by_name"] = users.get(e.get("submitted_by"))
    data["events"] = events
    marks = ",".join("?" for _ in ids)
    if ids:
        data["inventory_items"] = [dict(r) for r in conn.execute(
            f"SELECT * FROM inventory_items WHERE event_id IN ({marks})", ids)]
        data["event_crew"] = [dict(r) for r in conn.execute(
            f"SELECT * FROM event_crew WHERE event_id IN ({marks})", ids)]
        data["event_team"] = [
            {"event_id": r["event_id"], "name": users.get(r["user_id"], "")}
            for r in conn.execute(f"SELECT * FROM event_team WHERE event_id IN ({marks})", ids)
        ]
        data["event_log"] = [
            dict(r, user_name=users.get(r["user_id"]))
            for r in conn.execute(f"SELECT * FROM event_log WHERE event_id IN ({marks})", ids)
        ]
    data["bookings"] = [dict(r) for r in conn.execute(
        "SELECT * FROM bookings WHERE created_by = ?", (user_id,))]
    return data


def make_backup(db, out_path, app_version="", user_id=None):
    """Write records to out_path: everything, or only one account (user_id).
    Returns the same summary as peek()."""
    data = {}
    avatars = {}
    with closing(db._connect()) as conn:
        if user_id is None:
            for table in TABLES:
                data[table] = _rows(conn, table)
        else:
            data = _account_data(conn, user_id)
            if not data["users"]:
                raise BackupError("That account does not exist.")
    for user in data["users"]:
        path = user.get("photo_path")
        if path and os.path.isfile(path):
            avatars[user["id"]] = path
        user["photo_path"] = None            # pictures travel as their own files
        user["has_avatar"] = user["id"] in avatars
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    manifest = {
        "app": APP_ID,
        "format": FORMAT,
        "scope": "everything" if user_id is None else "account",
        "account_name": data["users"][0]["name"] if user_id is not None else "",
        "app_version": app_version,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "data_sha256": hashlib.sha256(payload).hexdigest(),
        "counts": {t: len(data[t]) for t in TABLES},
    }
    tmp = out_path + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
        zf.writestr("data.json", payload)
        for user_id, path in avatars.items():
            zf.write(path, f"avatars/{user_id}.jpg")
    os.replace(tmp, out_path)
    return summarize(manifest)


def summarize(manifest):
    counts = manifest.get("counts", {})
    return {
        "accounts": counts.get("users", 0),
        "days": counts.get("events", 0),
        "created_at": manifest.get("created_at", ""),
        "app_version": manifest.get("app_version", ""),
        "scope": manifest.get("scope", "everything"),
        "name": manifest.get("account_name", ""),
    }


def read_backup(path):
    """Check the file and return (manifest, data, zipfile-names). Raises BackupError."""
    try:
        zf = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        raise BackupError("This is not a Pod backup file.")
    with zf:
        names = set(zf.namelist())
        if "manifest.json" not in names or "data.json" not in names:
            raise BackupError("This is not a Pod backup file.")
        try:
            manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BackupError("The backup file is damaged.")
        if manifest.get("app") != APP_ID:
            raise BackupError("This file was not made by The Pod.")
        if int(manifest.get("format", 0)) > FORMAT:
            raise BackupError("This backup is from a newer version of the app. Update the app first.")
        if zf.getinfo("data.json").file_size > MAX_DATA_BYTES:
            raise BackupError("The backup file is too large to be real.")
        payload = zf.read("data.json")
        if hashlib.sha256(payload).hexdigest() != manifest.get("data_sha256"):
            raise BackupError("The backup file is damaged (checksum does not match).")
        try:
            data = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            raise BackupError("The backup file is damaged.")
    return manifest, data


def peek(path):
    """Quick look for the confirmation screen: accounts, days, date made."""
    manifest, _data = read_backup(path)
    return summarize(manifest)


def restore_any(db, path, avatar_folder):
    """Restore whatever kind of backup the file is. Returns a summary with 'scope'."""
    manifest, _data = read_backup(path)
    if manifest.get("scope", "everything") == "account":
        return restore_account(db, path, avatar_folder)
    return restore_backup(db, path, avatar_folder)


def restore_account(db, path, avatar_folder):
    """Add ONE account from an account backup, without touching anything else.

    - The account is created with its PIN, unless an active account with the same
      name already exists (then the existing profile and PIN are kept).
    - Days are added; a date this account already has is left alone.
    - An admin account is never added as a second admin.
    """
    manifest, data = read_backup(path)
    if manifest.get("scope") != "account" or len(data.get("users", [])) != 1:
        raise BackupError("This is not an account backup.")
    src = data["users"][0]
    result = {"scope": "account", "name": src["name"], "created": False,
              "added": 0, "skipped": 0, "accounts": 1}
    with closing(db._connect()) as conn:
        with conn:
            existing = conn.execute(
                "SELECT id FROM users WHERE lower(name) = lower(?) AND deleted_at IS NULL",
                (src["name"],),
            ).fetchone()
            if existing:
                owner = existing["id"]
            else:
                role = src.get("role") or CREW
                if role == ADMIN and conn.execute(
                    "SELECT 1 FROM users WHERE role = ? AND deleted_at IS NULL", (ADMIN,)
                ).fetchone():
                    role = LEADER
                cur = conn.execute(
                    "INSERT INTO users (name, role, created_at, pin_hash, pin_salt, description) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (src["name"], role, src.get("created_at") or "", src.get("pin_hash"),
                     src.get("pin_salt"), src.get("description") or ""),
                )
                owner = cur.lastrowid
                result["created"] = True

            def user_by_name(name):
                if not name:
                    return None
                row = conn.execute(
                    "SELECT id FROM users WHERE lower(name) = lower(?) AND deleted_at IS NULL",
                    (name,),
                ).fetchone()
                return row["id"] if row else None

            for ev in data.get("events", []):
                if conn.execute(
                    "SELECT 1 FROM events WHERE event_date = ? AND created_by = ?",
                    (ev["event_date"], owner),
                ).fetchone():
                    result["skipped"] += 1
                    continue
                cur = conn.execute(
                    "INSERT INTO events (event_date, location, created_by, created_at, "
                    "submitted_by, submitted_at, cups_target) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (ev["event_date"], ev["location"], owner, ev.get("created_at") or "",
                     user_by_name(ev.get("submitted_by_name")), ev.get("submitted_at"),
                     ev.get("cups_target")),
                )
                new_id, old_id = cur.lastrowid, ev["id"]
                result["added"] += 1
                for it in data.get("inventory_items", []):
                    if it["event_id"] == old_id:
                        conn.execute(
                            "INSERT INTO inventory_items (event_id, item_name, unit, before_qty, "
                            "after_qty, sort_order) VALUES (?, ?, ?, ?, ?, ?)",
                            (new_id, it["item_name"], it.get("unit") or "", it.get("before_qty"),
                             it.get("after_qty"), it.get("sort_order") or 0),
                        )
                for crew in data.get("event_crew", []):
                    if crew["event_id"] == old_id:
                        conn.execute("INSERT OR IGNORE INTO event_crew (event_id, name) VALUES (?, ?)",
                                     (new_id, crew["name"]))
                for tm in data.get("event_team", []):
                    if tm["event_id"] != old_id:
                        continue
                    uid = user_by_name(tm.get("name"))
                    if uid:
                        conn.execute("INSERT OR IGNORE INTO event_team (event_id, user_id) VALUES (?, ?)",
                                     (new_id, uid))
                    elif tm.get("name"):         # not on this phone: keep them as a typed name
                        conn.execute("INSERT OR IGNORE INTO event_crew (event_id, name) VALUES (?, ?)",
                                     (new_id, tm["name"]))
                for lg in data.get("event_log", []):
                    if lg["event_id"] != old_id:
                        continue
                    uid = user_by_name(lg.get("user_name"))
                    detail = lg.get("detail") or ""
                    if uid is None and lg.get("user_name"):
                        detail = (detail + f" [by {lg['user_name']}]").strip()
                    conn.execute(
                        "INSERT INTO event_log (event_id, event_date, user_id, action, detail, created_at) "
                        "VALUES (?, ?, ?, ?, ?, ?)",
                        (new_id, lg["event_date"], uid, lg["action"], detail, lg["created_at"]),
                    )
            for bk in data.get("bookings", []):
                if conn.execute(
                    "SELECT 1 FROM events WHERE event_date = ? AND created_by = ?",
                    (bk["work_date"], owner),
                ).fetchone():
                    continue
                conn.execute(
                    "INSERT OR IGNORE INTO bookings (work_date, created_by, created_at) VALUES (?, ?, ?)",
                    (bk["work_date"], owner, bk.get("created_at") or ""),
                )
    if result["created"] and src.get("has_avatar"):
        name = f"avatars/{src['id']}.jpg"
        with zipfile.ZipFile(path) as zf:
            if name in zf.namelist() and zf.getinfo(name).file_size <= MAX_AVATAR_BYTES:
                os.makedirs(avatar_folder, exist_ok=True)
                target = os.path.join(avatar_folder, f"restored_user{owner}.jpg")
                with zf.open(name) as s, open(target, "wb") as d:
                    shutil.copyfileobj(s, d)
                db.set_photo(owner, target)
    return result


def restore_backup(db, path, avatar_folder):
    """Replace everything in db with the backup's contents.

    The current database file is first copied next to itself as
    '<name>.before_restore', so a wrong restore can still be undone by hand.
    Returns the summary of what was restored.
    """
    manifest, data = read_backup(path)
    if manifest.get("scope", "everything") != "everything":
        raise BackupError("This is a single-account backup, not a full one.")
    if not data.get("users"):
        raise BackupError("The backup has no accounts in it.")

    if os.path.isfile(db.path):
        shutil.copyfile(db.path, db.path + ".before_restore")

    with closing(db._connect()) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        try:
            with conn:
                for table in reversed(TABLES):
                    conn.execute(f"DELETE FROM {table}")
                for table in TABLES:
                    known = [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]
                    for row in data.get(table, []):
                        cols = [c for c in row if c in known]
                        if not cols:
                            continue
                        marks = ", ".join("?" for _ in cols)
                        conn.execute(
                            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({marks})",
                            [row[c] for c in cols],
                        )
        except Exception as exc:
            raise BackupError(f"Could not restore: {exc}")

    # profile pictures go back into the app's own folder
    os.makedirs(avatar_folder, exist_ok=True)
    with zipfile.ZipFile(path) as zf, closing(db._connect()) as conn:
        for user in data["users"]:
            name = f"avatars/{user['id']}.jpg"
            if not user.get("has_avatar") or name not in zf.namelist():
                continue
            if zf.getinfo(name).file_size > MAX_AVATAR_BYTES:
                continue
            target = os.path.join(avatar_folder, f"restored_user{user['id']}.jpg")
            with zf.open(name) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            with conn:
                conn.execute("UPDATE users SET photo_path = ? WHERE id = ?", (target, user["id"]))
    return summarize(manifest)
