#!/usr/bin/env python
"""End-to-end smoke test for the Cronometer client against a REAL account.

Reads CRONOMETER_USERNAME / CRONOMETER_PASSWORD from the environment or the
repo-root .env. Read-only by default; pass --write to also exercise the write
path (logs a test food + weight, then removes the test food).

    uv run python smoke_test.py
    uv run python smoke_test.py --write

This is the Phase-1 validation gate from PLAN.md: prove the highest-risk
dependency works before building the agents on top of it.
"""

import argparse
import sys
from datetime import date

from dotenv import find_dotenv, load_dotenv

from cronometer_mcp.client import CronometerClient, CronometerError


def _section(title: str) -> None:
    print(f"\n=== {title} ===")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write",
        action="store_true",
        help="Also test writes (log + remove a test entry, log a weight).",
    )
    args = parser.parse_args()

    # Load repo-root .env without overriding real env vars.
    load_dotenv(find_dotenv(usecwd=True), override=False)

    client = CronometerClient()

    _section("1. Login")
    try:
        client.login()
        print(f"OK — user_id={client._user_id}")
    except CronometerError as e:
        print(f"FAIL — {e}")
        return 1

    _section("2. Search food ('eggs')")
    foods = client.search_food("eggs")
    if not foods:
        print("FAIL — no results")
        return 1
    top = foods[0]
    print(f"OK — {len(foods)} results; top: {top.get('name')} (id={top.get('id')})")

    _section("3. Read today's diary")
    diary = client.get_diary(date.today())
    entries = diary.get("diary", [])
    print(f"OK — {len(entries)} entries today")

    _section("4. Daily nutrition summary")
    nutrition = client.get_consumed_nutrients(date.today())
    macros = nutrition.get("macros", {})
    print(f"OK — energy={macros.get('energy')} protein={macros.get('protein')}")

    if not args.write:
        print("\nRead-only checks passed. Re-run with --write to test logging.")
        return 0

    _section("5. WRITE — log a test serving")
    measure_id = top.get("measureId") or 0
    translation_id = top.get("translationId") or 0
    logged = client.add_serving(
        food_id=top["id"],
        measure_id=measure_id,
        grams=50.0,
        translation_id=translation_id,
    )
    serving_id = logged.get("id") or logged.get("servingId")
    print(f"OK — logged serving id={serving_id}")

    _section("6. WRITE — remove the test serving")
    if serving_id:
        removed = client.delete_entries([str(serving_id)])
        print(f"OK — removed {removed.get('count', 0)} entr(y/ies)")
    else:
        print("SKIP — no serving id returned; check the diary and remove manually")

    _section("7. WRITE — log a test weight on a distinctive PAST date, read back")
    # Use an old date + odd value so it won't disturb your real weight trend
    # and is trivial to spot/delete in the app.
    test_day = date(2015, 6, 15)
    test_val = 111.1
    try:
        resp = client.add_biometric("weight", test_val, unit="lbs", day=test_day)
        print(f"OK — add_biometric response: {resp}")
        hist = client.get_biometric_history(
            "weight", unit="lbs", start=test_day, end=test_day
        )
        print(f"OK — read back {test_day}: {hist}")
        print(
            f"  If you see {test_val} lb on {test_day}, weight logging works. "
            "Delete that one old entry in the Cronometer app."
        )
    except Exception as e:  # noqa: BLE001 -- report and continue
        print(f"FAIL — {type(e).__name__}: {e}")

    print("\nWrite checks complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
