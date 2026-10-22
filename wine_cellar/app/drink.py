"""The one rule for where a wine stands in its drinking window.

Everything that needs a status uses this file: the wine list, the dinner pairing, the weekly alert,
the Home Assistant sensors and the database views. Windows are whole years.

    nowin  no window is set
    past   the last year of the window is over
    hold   the window has not started
    soon   the last year of the window is this year
    ready  inside the window (and not in its last year)
"""
from datetime import datetime

STATUSES = ("nowin", "past", "hold", "soon", "ready")


def this_year():
    return datetime.now().year


def status(begin, end, year=None):
    year = year or this_year()
    if not begin and not end:
        return "nowin"
    if end and end < year:
        return "past"
    if begin and begin > year:
        return "hold"
    if end and end == year:
        return "soon"
    return "ready"


def is_ready(s):
    """Ready to open now: inside the window, including its last year."""
    return s in ("ready", "soon")


def sql_case(year_sql, labels=None, begin="begin_consume", end="end_consume"):
    """The same rule as status(), as a SQL CASE expression, for the read-only database views."""
    lab = dict(zip(STATUSES, STATUSES))
    if labels:
        lab.update(labels)
    b, e = "NULLIF(%s, 0)" % begin, "NULLIF(%s, 0)" % end
    return ("CASE WHEN %s IS NULL AND %s IS NULL THEN '%s' WHEN %s < %s THEN '%s' WHEN %s > %s THEN '%s' WHEN %s = %s THEN '%s' ELSE '%s' END"
            % (b, e, lab["nowin"], e, year_sql, lab["past"], b, year_sql, lab["hold"], e, year_sql, lab["soon"], lab["ready"]))
