"""Who is allowed to do what. No Kivy in here, so it is easy to test.

Creator admin  - adds inventory for any past date, edits ANY day (even submitted
                 ones), and can delete a day. Only one creator admin exists.
Team leader    - adds inventory for today or a past date (for a forgotten day)
                 and edits unsubmitted days, but cannot change a submitted day
                 or delete anything.
Crew           - adds inventory for today only.

Dates are 'YYYY-MM-DD' text, so comparing them as text compares them as dates.
"""

ADMIN = "creator_admin"
LEADER = "team_leader"
CREW = "crew"

ROLE_LABELS = {
    ADMIN: "Creator admin",
    LEADER: "Team leader",
    CREW: "Crew",
}

ROLE_DESCRIPTIONS = {
    ADMIN: "Adds and edits any date, edits submitted days, and can delete a day.",
    LEADER: "Adds inventory for today or a past day, but cannot edit submitted days or delete.",
    CREW: "Adds inventory for today only.",
}


def normalize_role(value):
    """Turn old free-text roles into one of the three role keys."""
    text = (value or "").strip().lower().replace("-", " ").replace("_", " ")
    if text in ("creator admin", "creator", "admin"):
        return ADMIN
    if text in ("team leader", "team lead", "leader", "lead"):
        return LEADER
    return CREW


def role_label(role):
    return ROLE_LABELS.get(role, ROLE_LABELS[CREW])


def can_start_day(role, date_str, today_str):
    """May this role record inventory for that date (new or unsubmitted)?"""
    if role not in ROLE_LABELS:
        return False
    if date_str > today_str:
        return False  # the future can only be booked as a pending work day
    if date_str == today_str:
        return True
    return role in (ADMIN, LEADER)


def start_denied_reason(role, date_str, today_str):
    """Plain-words reason for a refusal, or '' when it is allowed."""
    if can_start_day(role, date_str, today_str):
        return ""
    if date_str > today_str:
        return "This date is in the future. Mark it as a pending work day and start it on the day."
    return "Only a Team leader or the Creator admin can add inventory for a past day."


def can_edit_submitted(role):
    return role == ADMIN


def can_delete_day(role):
    return role == ADMIN
