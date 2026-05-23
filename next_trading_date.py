#!/usr/bin/env python3
"""
Print the next trading date.

Simple weekday calendar:
- Mon-Thu -> next day
- Fri/Sat/Sun -> Monday

This intentionally ignores market holidays for now. We can add NYSE holiday
support later.
"""

from datetime import date, timedelta

d = date.today() + timedelta(days=1)

while d.weekday() >= 5:
    d += timedelta(days=1)

print(d.isoformat())
