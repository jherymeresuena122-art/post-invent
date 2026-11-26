"""Local SQLite storage for The Pod inventory app.

Everything the app remembers lives in one small database file on the phone.
A submitted day is locked: only the Creator admin can unlock it for editing,
and every such edit is written to the day's history.
"""
import hashlib
import hmac
import os
import sqlite3
from contextlib import closing
from datetime import datetime

from permissions import ADMIN, normalize_role


class EventLockedError(Exception):
    """Raised when someone tries to change a day that was already submitted."""


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _hash_pin(pin, salt_hex):
    return hashlib.pbkdf2_hmac(
        "sha256", pin.encode("utf-8"), bytes.fromhex(salt_hex), 100_000
    ).hex()


def _show(value):
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{round(value, 3):g}"
    return str(value)


def _describe_changes(old, new):
    """Short plain-text list of what an admin changed on a submitted day."""
    notes = []
    if old["location"] != new["location"]:
        notes.append(f"location: {old['location']} -> {new['location']}")
    if old["cups_target"] != new["cups_target"]:
        notes.append(
            f"cups to serve: {_show(old['cups_target'])} -> {_show(new['cups_target'])}"
        )
    old_items = {i["name"]: i for i in old["items"]}
    new_items = {i["name"]: i for i in new["items"]}
    for name, item in new_items.items():
        before = old_items.get(name)
        if before is None:
            notes.append(f"added {name}")
            continue
        for key in ("before", "after", "unit"):
            if before[key] != item[key]:
                notes.append(f"{name} {key}: {_show(before[key])} -> {_show(item[key])}")
    for name in old_items:
        if name not in new_items:
            notes.append(f"removed {name}")
    if old["team"] != new["team"]:
        notes.append("team changed")
    if old["crew"] != new["crew"]:
        notes.append("crew names changed")
    return "; ".join(notes) or "no changes"


class Database:
    def __init__(self, path):
        self.path = path
        self._create_tables()

    # ------------------------------------------------------------------ setup
    def _connect(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _create_tables(self):
        with closing(self._connect()) as conn, conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    name        TEXT NOT NULL,
                    role        TEXT NOT NULL DEFAULT 'crew',
                    photo_path  TEXT,
                    created_at  TEXT NOT NULL,
                    pin_hash    TEXT,
                    pin_salt    TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    deleted_at  TEXT                      -- NULL = account is active
                );

                CREATE TABLE IF NOT EXISTS events (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_date    TEXT NOT NULL,          -- YYYY-MM-DD
                    location      TEXT NOT NULL,
                    created_by    INTEGER REFERENCES users(id),
                    created_at    TEXT NOT NULL,
                    submitted_by  INTEGER REFERENCES users(id),
                    submitted_at  TEXT,                   -- NULL = still a draft
                    cups_target   REAL,                   -- cups the day's contract says to serve
                    UNIQUE (event_date, created_by)       -- one record per account per date
                );

                CREATE TABLE IF NOT EXISTS event_team (
                    event_id  INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    user_id   INTEGER NOT NULL REFERENCES users(id),
                    PRIMARY KEY (event_id, user_id)
                );

                -- crew members of a day who do not have a profile in the app
                CREATE TABLE IF NOT EXISTS event_crew (
                    event_id  INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    name      TEXT NOT NULL,
                    PRIMARY KEY (event_id, name)
                );

                CREATE TABLE IF NOT EXISTS inventory_items (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id    INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    item_name   TEXT NOT NULL,
                    unit        TEXT NOT NULL DEFAULT '',
                    before_qty  REAL,                    -- counted before the event
                    after_qty   REAL,                    -- counted after the event
                    sort_order  INTEGER NOT NULL DEFAULT 0,
                    UNIQUE (event_id, item_name)
                );

                CREATE TABLE IF NOT EXISTS photos (
                    id         INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id   INTEGER NOT NULL REFERENCES events(id) ON DELETE CASCADE,
                    file_path  TEXT NOT NULL,
                    taken_at   TEXT NOT NULL
                );

                -- pending work days booked in advance (not started yet)
                CREATE TABLE IF NOT EXISTS bookings (
                    work_date   TEXT NOT NULL,            -- YYYY-MM-DD
                    created_by  INTEGER NOT NULL REFERENCES users(id),
                    created_at  TEXT NOT NULL,
                    PRIMARY KEY (work_date, created_by)
                );

                -- who did what to a day. event_id has no foreign key on purpose,
                -- so the history of a deleted day is kept.
                CREATE TABLE IF NOT EXISTS event_log (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id    INTEGER,
                    event_date  TEXT NOT NULL,
                    user_id     INTEGER REFERENCES users(id),
                    action      TEXT NOT NULL,
                    detail      TEXT NOT NULL DEFAULT '',
                    created_at  TEXT NOT NULL
                );
                """
            )
            self._upgrade_old_tables(conn)
        self._make_data_per_account()

    @staticmethod
    def _upgrade_old_tables(conn):
        """Open databases made by earlier versions of the app without losing data."""
        items_cols = {r["name"] for r in conn.execute("PRAGMA table_info(inventory_items)")}
        if "before_qty" not in items_cols:
            conn.execute("ALTER TABLE inventory_items ADD COLUMN before_qty REAL")
            conn.execute("ALTER TABLE inventory_items ADD COLUMN after_qty REAL")
            conn.execute(
                "ALTER TABLE inventory_items ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 0"
            )
            if "quantity" in items_cols:
                conn.execute("UPDATE inventory_items SET after_qty = quantity")

        user_cols = {r["name"] for r in conn.execute("PRAGMA table_info(users)")}
        if "pin_hash" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN pin_hash TEXT")
            conn.execute("ALTER TABLE users ADD COLUMN pin_salt TEXT")

        event_cols = {r["name"] for r in conn.execute("PRAGMA table_info(events)")}
        if "cups_target" not in event_cols:
            conn.execute("ALTER TABLE events ADD COLUMN cups_target REAL")

        if "description" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN description TEXT NOT NULL DEFAULT ''")
        if "deleted_at" not in user_cols:
            conn.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")

        # older versions saved the unit as "litres"; it is now spelled "liters"
        conn.execute("UPDATE inventory_items SET unit = 'liters' WHERE unit = 'litres'")

        # old free-text roles ("Team lead") become one of the three role keys
        for row in conn.execute("SELECT id, role FROM users").fetchall():
            fixed = normalize_role(row["role"])
            if fixed != row["role"]:
                conn.execute("UPDATE users SET role = ? WHERE id = ?", (fixed, row["id"]))

    def _make_data_per_account(self):
        """Versions before 2.1 allowed one record per date for the whole phone.
        Now every account has its own days, so the same date can exist once per
        account. SQLite cannot change a constraint in place, so the tables are
        rebuilt (all rows are kept)."""
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            old_events = False
            for idx in conn.execute("PRAGMA index_list(events)").fetchall():
                if idx["unique"]:
                    cols = [r["name"] for r in conn.execute(f"PRAGMA index_info('{idx['name']}')")]
                    if cols == ["event_date"]:
                        old_events = True
            booking_pk = {
                r["name"]: r["pk"] for r in conn.execute("PRAGMA table_info(bookings)")
            }
            old_bookings = booking_pk.get("created_by", 0) == 0
            if not (old_events or old_bookings):
                return
            conn.execute("PRAGMA foreign_keys = OFF")
            admin_row = conn.execute(
                "SELECT id FROM users WHERE role = ? ORDER BY id LIMIT 1", (ADMIN,)
            ).fetchone()
            first = admin_row[0] if admin_row else (
                conn.execute("SELECT MIN(id) FROM users").fetchone()[0] or 0
            )
            if old_events:
                conn.executescript(
                    f"""
                    BEGIN;
                    CREATE TABLE events_new (
                        id            INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_date    TEXT NOT NULL,
                        location      TEXT NOT NULL,
                        created_by    INTEGER REFERENCES users(id),
                        created_at    TEXT NOT NULL,
                        submitted_by  INTEGER REFERENCES users(id),
                        submitted_at  TEXT,
                        cups_target   REAL,
                        UNIQUE (event_date, created_by)
                    );
                    INSERT INTO events_new
                        (id, event_date, location, created_by, created_at,
                         submitted_by, submitted_at, cups_target)
                        SELECT id, event_date, location,
                               COALESCE(created_by, {first or 'NULL'}), created_at,
                               submitted_by, submitted_at, cups_target FROM events;
                    DROP TABLE events;
                    ALTER TABLE events_new RENAME TO events;
                    COMMIT;
                    """
                )
            if old_bookings:
                # a booking whose creator is unknown is given to the admin (or first account)
                conn.executescript(
                    f"""
                    BEGIN;
                    CREATE TABLE bookings_new (
                        work_date   TEXT NOT NULL,
                        created_by  INTEGER NOT NULL REFERENCES users(id),
                        created_at  TEXT NOT NULL,
                        PRIMARY KEY (work_date, created_by)
                    );
                    INSERT INTO bookings_new (work_date, created_by, created_at)
                        SELECT work_date, COALESCE(created_by, {int(first)}), created_at
                        FROM bookings;
                    DROP TABLE bookings;
                    ALTER TABLE bookings_new RENAME TO bookings;
                    COMMIT;
                    """
                )

    @staticmethod
    def _log(conn, event_id, event_date, user_id, action, detail=""):
        conn.execute(
            "INSERT INTO event_log (event_id, event_date, user_id, action, detail, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (event_id, event_date, user_id, action, detail, _now()),
        )

    # ------------------------------------------------------------------ users
    def add_user(self, name, role="crew", photo_path=None, pin=None):
        role = normalize_role(role)
        if role == ADMIN and self.has_admin():
            raise ValueError("There is already a Creator admin.")
        salt = pin_hash = None
        if pin:
            salt = os.urandom(16).hex()
            pin_hash = _hash_pin(pin, salt)
        with closing(self._connect()) as conn, conn:
            cur = conn.execute(
                "INSERT INTO users (name, role, photo_path, created_at, pin_hash, pin_salt) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (name.strip(), role, photo_path, _now(), pin_hash, salt),
            )
            return cur.lastrowid

    def has_admin(self):
        with closing(self._connect()) as conn:
            row = conn.execute("SELECT 1 FROM users WHERE role = ?", (ADMIN,)).fetchone()
        return row is not None

    def list_users(self):
        """Active accounts only. Removed accounts keep their name in past days."""
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM users WHERE deleted_at IS NULL ORDER BY name COLLATE NOCASE"
            ).fetchall()

    def get_user(self, user_id):
        with closing(self._connect()) as conn:
            return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    def verify_pin(self, user_id, pin):
        """True if the PIN is right. A profile with no PIN always passes."""
        user = self.get_user(user_id)
        if user is None or user["deleted_at"] is not None:
            return False
        if not user["pin_hash"]:
            return True
        guess = _hash_pin(pin or "", user["pin_salt"])
        return hmac.compare_digest(guess, user["pin_hash"])

    def set_description(self, user_id, text):
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET description = ? WHERE id = ?", ((text or "").strip(), user_id)
            )

    def set_photo(self, user_id, photo_path):
        """photo_path may be None to go back to the letter circle."""
        with closing(self._connect()) as conn, conn:
            conn.execute("UPDATE users SET photo_path = ? WHERE id = ?", (photo_path, user_id))

    def set_pin(self, user_id, new_pin):
        """Change a PIN (4 to 6 digits). Crew may clear it with an empty PIN."""
        user = self.get_user(user_id)
        if user is None or user["deleted_at"] is not None:
            raise ValueError("That account does not exist.")
        new_pin = (new_pin or "").strip()
        if not new_pin:
            if user["role"] != "crew":
                raise ValueError("Creator admin and Team leader must keep a PIN.")
            salt = pin_hash = None
        else:
            if not (new_pin.isdigit() and 4 <= len(new_pin) <= 6):
                raise ValueError("The PIN must be 4 to 6 digits.")
            salt = os.urandom(16).hex()
            pin_hash = _hash_pin(new_pin, salt)
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET pin_hash = ?, pin_salt = ? WHERE id = ?",
                (pin_hash, salt, user_id),
            )

    def delete_user(self, user_id):
        """Remove an account from the app. Past days keep the person's name.

        The Creator admin cannot be removed, so the app always has an admin.
        """
        user = self.get_user(user_id)
        if user is None or user["deleted_at"] is not None:
            raise ValueError("That account does not exist.")
        if user["role"] == ADMIN:
            raise ValueError("The Creator admin account cannot be deleted.")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "UPDATE users SET deleted_at = ?, pin_hash = NULL, pin_salt = NULL, "
                "photo_path = NULL, description = '' WHERE id = ?",
                (_now(), user_id),
            )

    # ----------------------------------------------------------------- events
    def count_events(self, owner_id=None):
        """Days of one account (owner_id), or of everybody when owner_id is None."""
        with closing(self._connect()) as conn:
            if owner_id is None:
                return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            return conn.execute(
                "SELECT COUNT(*) FROM events WHERE created_by = ?", (owner_id,)
            ).fetchone()[0]

    def get_event(self, event_date, owner_id=None):
        """The day this account recorded on that date (owner_id None = first found)."""
        with closing(self._connect()) as conn:
            if owner_id is None:
                return conn.execute(
                    "SELECT * FROM events WHERE event_date = ? ORDER BY id LIMIT 1",
                    (event_date,),
                ).fetchone()
            return conn.execute(
                "SELECT * FROM events WHERE event_date = ? AND created_by = ?",
                (event_date, owner_id),
            ).fetchone()

    @staticmethod
    def _items_of(conn, event_id):
        rows = conn.execute(
            """SELECT item_name, unit, before_qty, after_qty
               FROM inventory_items WHERE event_id = ?
               ORDER BY sort_order, id""",
            (event_id,),
        ).fetchall()
        return [
            {
                "name": r["item_name"],
                "unit": r["unit"],
                "before": r["before_qty"],
                "after": r["after_qty"],
            }
            for r in rows
        ]

    def get_items(self, event_id):
        """Items in the order they were entered: {"name", "unit", "before", "after"}."""
        with closing(self._connect()) as conn:
            return self._items_of(conn, event_id)

    def get_team(self, event_id):
        """Crew who have a profile in the app."""
        with closing(self._connect()) as conn:
            return conn.execute(
                """SELECT u.* FROM users u
                   JOIN event_team t ON t.user_id = u.id
                   WHERE t.event_id = ?
                   ORDER BY u.name COLLATE NOCASE""",
                (event_id,),
            ).fetchall()

    def get_crew_names(self, event_id):
        """Extra crew members who were typed in by name (no profile)."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT name FROM event_crew WHERE event_id = ? ORDER BY rowid", (event_id,)
            ).fetchall()
        return [r["name"] for r in rows]

    def save_event(
        self,
        event_date,
        location,
        items,
        team_ids,
        created_by,
        crew_names=None,
        allow_locked=False,
        editor_id=None,
        cups_target=None,
    ):
        """Create or update a day.

        items      -> [{"name": "Hot cups", "unit": "cups", "before": 150, "after": 100}, ...]
                      (before / after may be None while it is still a draft)
        team_ids   -> user ids of crew who have a profile
        crew_names -> extra crew names typed in by hand
        cups_target-> cups the day's contract says to serve (or None)
        A submitted day raises EventLockedError, unless allow_locked=True
        (the Creator admin editing it), which is recorded in the day's history.
        """
        crew_names = [n.strip() for n in (crew_names or []) if n and n.strip()]
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT id, location, submitted_at, cups_target FROM events "
                "WHERE event_date = ? AND created_by = ?",
                (event_date, created_by),
            ).fetchone()
            locked = row is not None and row["submitted_at"] is not None
            if locked and not allow_locked:
                raise EventLockedError("This day was already submitted and is locked.")

            old = None
            if row is None:
                cur = conn.execute(
                    "INSERT INTO events (event_date, location, created_by, created_at, "
                    "cups_target) VALUES (?, ?, ?, ?, ?)",
                    (event_date, location, created_by, _now(), cups_target),
                )
                event_id = cur.lastrowid
                self._log(conn, event_id, event_date, created_by, "created")
            else:
                event_id = row["id"]
                if locked:
                    old = {
                        "location": row["location"],
                        "cups_target": row["cups_target"],
                        "items": self._items_of(conn, event_id),
                        "team": {
                            r["user_id"]
                            for r in conn.execute(
                                "SELECT user_id FROM event_team WHERE event_id = ?", (event_id,)
                            )
                        },
                        "crew": {
                            r["name"]
                            for r in conn.execute(
                                "SELECT name FROM event_crew WHERE event_id = ?", (event_id,)
                            )
                        },
                    }
                conn.execute(
                    "UPDATE events SET location = ?, cups_target = ? WHERE id = ?",
                    (location, cups_target, event_id),
                )

            conn.execute("DELETE FROM inventory_items WHERE event_id = ?", (event_id,))
            for position, item in enumerate(items):
                conn.execute(
                    "INSERT INTO inventory_items "
                    "(event_id, item_name, unit, before_qty, after_qty, sort_order) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        event_id,
                        item["name"],
                        item["unit"],
                        item["before"],
                        item["after"],
                        position,
                    ),
                )

            conn.execute("DELETE FROM event_team WHERE event_id = ?", (event_id,))
            for uid in sorted(set(team_ids)):
                conn.execute(
                    "INSERT INTO event_team (event_id, user_id) VALUES (?, ?)",
                    (event_id, uid),
                )
            conn.execute("DELETE FROM event_crew WHERE event_id = ?", (event_id,))
            for name in dict.fromkeys(crew_names):  # keeps order, drops duplicates
                conn.execute(
                    "INSERT INTO event_crew (event_id, name) VALUES (?, ?)", (event_id, name)
                )

            if old is not None:
                new = {
                    "location": location,
                    "cups_target": cups_target,
                    "items": items,
                    "team": set(team_ids),
                    "crew": set(crew_names),
                }
                self._log(
                    conn, event_id, event_date, editor_id or created_by,
                    "admin_edit", _describe_changes(old, new),
                )

            # the day has started, so it is no longer just a booking
            conn.execute(
                "DELETE FROM bookings WHERE work_date = ? AND created_by = ?",
                (event_date, created_by),
            )
            return event_id

    def submit_event(self, event_id, user_id):
        """Lock a day. After this, save_event() refuses to touch it."""
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT event_date, submitted_at FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is None:
                raise ValueError("That day does not exist.")
            if row["submitted_at"] is not None:
                raise EventLockedError("This day was already submitted.")
            conn.execute(
                "UPDATE events SET submitted_by = ?, submitted_at = ? WHERE id = ?",
                (user_id, _now(), event_id),
            )
            self._log(conn, event_id, row["event_date"], user_id, "submitted")

    def delete_event(self, event_id, user_id):
        """Remove a day with its items, crew and photos. The history line stays."""
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT event_date, location, submitted_at FROM events WHERE id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise ValueError("That day does not exist.")
            state = "submitted" if row["submitted_at"] else "draft"
            self._log(
                conn, event_id, row["event_date"], user_id, "deleted",
                f"{state} day at {row['location']}",
            )
            conn.execute("DELETE FROM events WHERE id = ?", (event_id,))

    def get_log(self, event_id):
        """History of one day, oldest first."""
        with closing(self._connect()) as conn:
            rows = conn.execute(
                """SELECT l.action, l.detail, l.created_at, u.name AS user_name
                   FROM event_log l LEFT JOIN users u ON u.id = l.user_id
                   WHERE l.event_id = ? ORDER BY l.id""",
                (event_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def month_status(self, year, month, owner_id=None):
        """Return {'2026-11-08': 'submitted' or 'draft'} for one month of one account."""
        prefix = f"{year:04d}-{month:02d}-"
        sql = "SELECT event_date, submitted_at FROM events WHERE event_date LIKE ?"
        args = [prefix + "%"]
        if owner_id is not None:
            sql += " AND created_by = ?"
            args.append(owner_id)
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, args).fetchall()
        return {
            r["event_date"]: ("submitted" if r["submitted_at"] else "draft") for r in rows
        }

    # --------------------------------------------------------------- bookings
    def add_booking(self, work_date, user_id):
        """Mark a date as a pending work day."""
        if self.get_event(work_date, user_id) is not None:
            raise ValueError("That day already has a record.")
        with closing(self._connect()) as conn, conn:
            conn.execute(
                "INSERT OR IGNORE INTO bookings (work_date, created_by, created_at) "
                "VALUES (?, ?, ?)",
                (work_date, user_id, _now()),
            )

    def remove_booking(self, work_date, owner_id=None):
        sql, args = "DELETE FROM bookings WHERE work_date = ?", [work_date]
        if owner_id is not None:
            sql += " AND created_by = ?"
            args.append(owner_id)
        with closing(self._connect()) as conn, conn:
            conn.execute(sql, args)

    def has_booking(self, work_date, owner_id=None):
        sql, args = "SELECT 1 FROM bookings WHERE work_date = ?", [work_date]
        if owner_id is not None:
            sql += " AND created_by = ?"
            args.append(owner_id)
        with closing(self._connect()) as conn:
            row = conn.execute(sql, args).fetchone()
        return row is not None

    def month_bookings(self, year, month, owner_id=None):
        prefix = f"{year:04d}-{month:02d}-"
        sql, args = "SELECT work_date FROM bookings WHERE work_date LIKE ?", [prefix + "%"]
        if owner_id is not None:
            sql += " AND created_by = ?"
            args.append(owner_id)
        with closing(self._connect()) as conn:
            rows = conn.execute(sql, args).fetchall()
        return {r["work_date"] for r in rows}

    def next_booking(self, from_date, owner_id=None):
        """The soonest pending work day on or after from_date, or None."""
        sql, args = "SELECT MIN(work_date) AS d FROM bookings WHERE work_date >= ?", [from_date]
        if owner_id is not None:
            sql += " AND created_by = ?"
            args.append(owner_id)
        with closing(self._connect()) as conn:
            row = conn.execute(sql, args).fetchone()
        return row["d"]

    # ----------------------------------------------------------------- photos
    def add_photo(self, event_id, file_path):
        with closing(self._connect()) as conn, conn:
            row = conn.execute(
                "SELECT submitted_at FROM events WHERE id = ?", (event_id,)
            ).fetchone()
            if row is not None and row["submitted_at"] is not None:
                raise EventLockedError("This day was already submitted and is locked.")
            conn.execute(
                "INSERT INTO photos (event_id, file_path, taken_at) VALUES (?, ?, ?)",
                (event_id, file_path, _now()),
            )

    def get_photos(self, event_id):
        with closing(self._connect()) as conn:
            return conn.execute(
                "SELECT * FROM photos WHERE event_id = ? ORDER BY taken_at", (event_id,)
            ).fetchall()
