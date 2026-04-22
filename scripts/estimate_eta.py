"""Compute a simple ETA estimator from historical completed AccountingTask records.

Outputs average seconds per journal entry and a simple estimator function.
Run with: `python -m scripts.estimate_eta` from project root.
"""

import asyncio
from statistics import mean

from app.db.mongodb import init_mongodb
from app.db.schemas import AccountingTask


async def main():
    await init_mongodb()
    tasks = await AccountingTask.find({"status": "completed"}).to_list()
    data = []
    for t in tasks:
        if t.started_at and t.completed_at:
            duration = (t.completed_at - t.started_at).total_seconds()
            num_entries = len(getattr(t, "journal_entries", []))
            if num_entries > 0:
                data.append((duration, num_entries))

    if not data:
        print("No completed tasks with journal entries found.")
        return

    durations = [d for d, n in data]
    per_entry = [d / n for d, n in data]

    print(f"Completed tasks: {len(data)}")
    print(f"Average job duration (s): {mean(durations):.2f}")
    print(f"Average seconds per journal entry: {mean(per_entry):.4f}")
    print("")
    print("Estimator: estimated_seconds = round(avg_seconds_per_entry * num_journal_entries)")


if __name__ == "__main__":
    asyncio.run(main())
