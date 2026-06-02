#!/usr/bin/env python3
"""Print optional AI/infra dependency readiness."""

from __future__ import annotations

import json

from services.optional_dependency_service import optional_dependency_status


def main() -> int:
    print(json.dumps(optional_dependency_status(), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
