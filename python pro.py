from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    import matplotlib.pyplot as plt

    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


# ==============================================================================
# ANSI Terminal Styling & Constants
# ==============================================================================
class ANSI:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[91m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    BLUE = "\033[94m"
    CYAN = "\033[96m"
    WHITE = "\033[97m"


DATA_DIR = Path("data")
EXPORTS_DIR = Path("exports")
JSON_STORE = DATA_DIR / "bills.json"
CSV_STORE = DATA_DIR / "bills.csv"

CATEGORIES = [
    "Food & Dining",
    "Travel & Cab",
    "Groceries",
    "Utilities & Rent",
    "Entertainment",
    "Other",
]

HIGH_BILL_THRESHOLD = 5000.00
HIGH_SHARE_THRESHOLD = 1500.00


def style(text: str, *codes: str) -> str:
    return f"{''.join(codes)}{text}{ANSI.RESET}"


# ==============================================================================
# Data Model & Schema Validation
# ==============================================================================
@dataclass
class BillRecord:
    bill_id: str
    title: str
    category: str
    base_amount: float
    tip_percent: float
    total_amount: float
    participants: list[str]
    per_person_share: float
    created_at: str
    notes: str = ""
    flags: list[str] = field(default_factory=list)


def validate_record_dict(raw: Any) -> BillRecord | None:
    """Validate and coerce a dictionary against the expected BillRecord schema."""
    if not isinstance(raw, dict):
        return None

    required_fields = {
        "bill_id": str,
        "title": str,
        "category": str,
        "base_amount": (int, float),
        "tip_percent": (int, float),
        "total_amount": (int, float),
        "participants": list,
        "per_person_share": (int, float),
        "created_at": str,
    }

    for key, expected_type in required_fields.items():
        if key not in raw or not isinstance(raw[key], expected_type):
            return None

    participants = [str(p).strip() for p in raw["participants"] if str(p).strip()]
    if len(participants) < 1:
        return None

    base_amount = float(raw["base_amount"])
    tip_percent = float(raw["tip_percent"])
    total_amount = float(raw["total_amount"])
    per_person_share = float(raw["per_person_share"])

    if base_amount <= 0 or tip_percent < 0 or total_amount <= 0 or per_person_share <= 0:
        return None

    try:
        datetime.fromisoformat(raw["created_at"])
    except ValueError:
        return None

    notes = str(raw.get("notes", "")).strip()
    flags = [str(f) for f in raw.get("flags", [])] if isinstance(raw.get("flags"), list) else []

    return BillRecord(
        bill_id=raw["bill_id"].strip(),
        title=raw["title"].strip(),
        category=raw["category"].strip(),
        base_amount=round(base_amount, 2),
        tip_percent=round(tip_percent, 2),
        total_amount=round(total_amount, 2),
        participants=participants,
        per_person_share=round(per_person_share, 2),
        created_at=raw["created_at"].strip(),
        notes=notes,
        flags=flags,
    )


# ==============================================================================
# Core Business Logic Engine
# ==============================================================================
def compute_bill_split(
    title: str,
    category: str,
    base_amount: float,
    tip_percent: float,
    participants: list[str],
    existing_count: int,
    notes: str = "",
) -> BillRecord:
    """Calculate tip, total bill, per-person share, and threshold warnings."""
    tip_amount = base_amount * (tip_percent / 100.0)
    total_amount = round(base_amount + tip_amount, 2)

    count = len(participants)
    # Round up to nearest paise (0.01) so no payer is under-charged on fractional splits
    per_person_share = math.ceil((total_amount / count) * 100) / 100.0

    flags: list[str] = []
    if total_amount >= HIGH_BILL_THRESHOLD:
        flags.append(f"HIGH_BILL (>=₹{HIGH_BILL_THRESHOLD:.0f})")
    if per_person_share >= HIGH_SHARE_THRESHOLD:
        flags.append(f"HIGH_SHARE (>=₹{HIGH_SHARE_THRESHOLD:.0f}/person)")

    timestamp = datetime.now().isoformat(timespec="seconds")
    bill_id = f"BILL-{datetime.now().strftime('%Y%m%d')}-{existing_count + 1:03d}"

    return BillRecord(
        bill_id=bill_id,
        title=title.strip(),
        category=category,
        base_amount=round(base_amount, 2),
        tip_percent=round(tip_percent, 2),
        total_amount=total_amount,
        participants=participants,
        per_person_share=per_person_share,
        created_at=timestamp,
        notes=notes.strip(),
        flags=flags,
    )


# ==============================================================================
# Local Persistence (JSON + CSV + Seed Data)
# ==============================================================================
def ensure_directories() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    EXPORTS_DIR.mkdir(parents=True, exist_ok=True)


def get_seed_records() -> list[BillRecord]:
    """Initial realistic dataset for first-time runs or recovery."""
    raw_seed = [
        ("Team Lunch at Paradise", "Food & Dining", 2400.0, 10.0, ["Aarav", "Meera", "Kabir", "Diya"], "Friday team lunch"),
        ("Airport Cab Split", "Travel & Cab", 1250.0, 0.0, ["Aarav", "Meera"], "Terminal 1 drop"),
        ("Monthly Flat Groceries", "Groceries", 3600.0, 0.0, ["Aarav", "Kabir", "Rohan"], "DMart stock-up"),
        ("Concert Passes", "Entertainment", 6400.0, 5.0, ["Meera", "Diya", "Kabir", "Rohan"], "Weekend pass"),
        ("Electricity & Wi-Fi", "Utilities & Rent", 4200.0, 0.0, ["Aarav", "Meera", "Kabir", "Rohan"], "November bills"),
    ]
    records: list[BillRecord] = []
    for idx, (title, cat, base, tip, people, note) in enumerate(raw_seed):
        rec = compute_bill_split(title, cat, base, tip, people, idx, note)
        records.append(rec)
    return records


def save_records_json(records: list[BillRecord], path: Path = JSON_STORE) -> None:
    ensure_directories()
    payload = {
        "schema_version": "1.0",
        "updated_at": datetime.now().isoformat(timespec="seconds"),
        "records": [asdict(r) for r in records],
    }
    tmp_path = path.with_suffix(".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)


def sync_records_csv(records: list[BillRecord], path: Path = CSV_STORE) -> None:
    ensure_directories()
    fieldnames = [
        "bill_id",
        "title",
        "category",
        "base_amount",
        "tip_percent",
        "total_amount",
        "participants",
        "participant_count",
        "per_person_share",
        "created_at",
        "notes",
        "flags",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "bill_id": r.bill_id,
                    "title": r.title,
                    "category": r.category,
                    "base_amount": f"{r.base_amount:.2f}",
                    "tip_percent": f"{r.tip_percent:.2f}",
                    "total_amount": f"{r.total_amount:.2f}",
                    "participants": "|".join(r.participants),
                    "participant_count": len(r.participants),
                    "per_person_share": f"{r.per_person_share:.2f}",
                    "created_at": r.created_at,
                    "notes": r.notes,
                    "flags": "; ".join(r.flags),
                }
            )


def load_records(path: Path = JSON_STORE) -> list[BillRecord]:
    """Load records safely; recreate clean default store if missing or corrupted."""
    ensure_directories()
    if not path.exists():
        print(style("[INFO] Storage file not found. Initializing fresh dataset...", ANSI.YELLOW))
        seed = get_seed_records()
        save_records_json(seed, path)
        sync_records_csv(seed)
        return seed

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(style(f"[WARN] Corrupted or unreadable JSON store ({exc}). Resetting cleanly...", ANSI.RED))
        seed = get_seed_records()
        save_records_json(seed, path)
        sync_records_csv(seed)
        return seed

    raw_items = data.get("records") if isinstance(data, dict) else None
    if not isinstance(raw_items, list):
        print(style("[WARN] Invalid JSON schema structure. Reinitializing dataset...", ANSI.RED))
        seed = get_seed_records()
        save_records_json(seed, path)
        sync_records_csv(seed)
        return seed

    valid_records: list[BillRecord] = []
    skipped = 0
    for item in raw_items:
        parsed = validate_record_dict(item)
        if parsed is not None:
            valid_records.append(parsed)
        else:
            skipped += 1

    if skipped > 0:
        print(style(f"[WARN] Skipped {skipped} malformed record(s) during schema check.", ANSI.YELLOW))

    return valid_records


def import_csv_dataset(csv_path_str: str, current_records: list[BillRecord]) -> tuple[list[BillRecord], int, int]:
    """Bulk import bills from a CSV file with row-level validation."""
    csv_path = Path(csv_path_str.strip())
    if not csv_path.exists() or not csv_path.is_file():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    added = 0
    rejected = 0
    updated = list(current_records)

    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row_num, row in enumerate(reader, start=2):
            try:
                title = (row.get("title") or "").strip()
                category = (row.get("category") or "Other").strip()
                if category not in CATEGORIES:
                    category = "Other"
                base_amount = float(row.get("base_amount", ""))
                tip_percent = float(row.get("tip_percent", "0") or "0")
                people_raw = row.get("participants", "")
                participants = [p.strip() for p in people_raw.replace(",", "|").split("|") if p.strip()]
                notes = (row.get("notes") or "").strip()

                if not title or base_amount <= 0 or tip_percent < 0 or len(participants) < 1:
                    raise ValueError("Domain constraint failed")

                rec = compute_bill_split(
                    title=title,
                    category=category,
                    base_amount=base_amount,
                    tip_percent=tip_percent,
                    participants=participants,
                    existing_count=len(updated),
                    notes=notes,
                )
                updated.append(rec)
                added += 1
            except Exception as err:
                rejected += 1
                print(style(f"  Row {row_num} skipped: {err}", ANSI.YELLOW))

    return updated, added, rejected


# ==============================================================================
# Defensive Console Input Helpers
# ==============================================================================
def prompt_non_empty(label: str) -> str:
    while True:
        val = input(style(f"{label}: ", ANSI.CYAN)).strip()
        if val:
            return val
        print(style("  [!] Input cannot be blank. Please enter a valid value.", ANSI.RED))


def prompt_float(label: str, min_val: float | None = None, max_val: float | None = None) -> float:
    while True:
        raw = input(style(f"{label}: ", ANSI.CYAN)).strip().replace(",", "")
        try:
            num = float(raw)
            if math.isnan(num) or math.isinf(num):
                raise ValueError("Non-finite number")
            if min_val is not None and num < min_val:
                print(style(f"  [!] Value must be >= {min_val}.", ANSI.RED))
                continue
            if max_val is not None and num > max_val:
                print(style(f"  [!] Value must be <= {max_val}.", ANSI.RED))
                continue
            return num
        except ValueError:
            print(style("  [!] Please enter a valid numeric value.", ANSI.RED))


def prompt_category() -> str:
    print(style("\nAvailable Categories:", ANSI.DIM))
    for idx, cat in enumerate(CATEGORIES, start=1):
        print(f"  {idx}. {cat}")
    while True:
        choice = input(style("Select category number or name: ", ANSI.CYAN)).strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(CATEGORIES):
                return CATEGORIES[idx]
        for cat in CATEGORIES:
            if choice.lower() == cat.lower():
                return cat
        print(style("  [!] Invalid category. Choose a valid number or category name.", ANSI.RED))


def prompt_participants() -> list[str]:
    while True:
        raw = input(style("Participants (comma-separated names, e.g., Aarav, Meera, Kabir): ", ANSI.CYAN)).strip()
        names = [p.strip().title() for p in raw.split(",") if p.strip()]
        # Deduplicate while preserving order
        unique_names = list(dict.fromkeys(names))
        if len(unique_names) >= 2:
            return unique_names
        print(style("  [!] Enter at least 2 distinct participant names to split a bill.", ANSI.RED))


# ==============================================================================
# Analytics, Tables, Reports & Charts
# ==============================================================================
def print_records_table(records: list[BillRecord], page_size: int = 10) -> None:
    if not records:
        print(style("\nNo matching bill records found.", ANSI.YELLOW))
        return

    header = f"{'ID':<17} {'Title':<24} {'Category':<18} {'Total (₹)':>11} {'Share (₹)':>11} {'People':>6}"
    separator = "-" * len(header)

    for start in range(0, len(records), page_size):
        chunk = records[start : start + page_size]
        print("\n" + style(header, ANSI.BOLD, ANSI.BLUE))
        print(style(separator, ANSI.DIM))
        for r in chunk:
            title_short = r.title[:21] + "..." if len(r.title) > 24 else r.title
            cat_short = r.category[:15] + "..." if len(r.category) > 18 else r.category
            flag_marker = style(" *", ANSI.YELLOW) if r.flags else ""
            print(
                f"{r.bill_id:<17} {title_short:<24} {cat_short:<18} "
                f"{r.total_amount:>11.2f} {r.per_person_share:>11.2f} {len(r.participants):>6}{flag_marker}"
            )
        if start + page_size < len(records):
            cont = input(style("\nPress Enter for next page (or 'q' to stop): ", ANSI.CYAN)).strip().lower()
            if cont == "q":
                break


def show_analytics(records: list[BillRecord]) -> None:
    if not records:
        print(style("\nNo data available for analytics.", ANSI.YELLOW))
        return

    total_spend = round(sum(r.total_amount for r in records), 2)
    total_base = round(sum(r.base_amount for r in records), 2)
    total_tips = round(total_spend - total_base, 2)
    avg_bill = round(total_spend / len(records), 2)
    max_record = max(records, key=lambda r: r.total_amount)
    min_record = min(records, key=lambda r: r.total_amount)

    print("\n" + style("=== EXECUTIVE ANALYTICS SUMMARY ===", ANSI.BOLD, ANSI.GREEN))
    print(f"  Total Recorded Bills : {len(records)}")
    print(f"  Base Spend           : ₹{total_base:,.2f}")
    print(f"  Total Tips           : ₹{total_tips:,.2f}")
    print(f"  Grand Total Spend    : ₹{total_spend:,.2f}")
    print(f"  Average Bill Size    : ₹{avg_bill:,.2f}")
    print(f"  Highest Bill         : ₹{max_record.total_amount:,.2f} ({max_record.title})")
    print(f"  Lowest Bill          : ₹{min_record.total_amount:,.2f} ({min_record.title})")

    # Category breakdown table
    cat_totals: dict[str, float] = {}
    cat_counts: dict[str, int] = {}
    for r in records:
        cat_totals[r.category] = round(cat_totals.get(r.category, 0.0) + r.total_amount, 2)
        cat_counts[r.category] = cat_counts.get(r.category, 0) + 1

    print("\n" + style("--- Spend by Category ---", ANSI.BOLD, ANSI.CYAN))
    print(f"{'Category':<20} {'Bills':>6} {'Total (₹)':>13} {'Share %':>9}")
    print("-" * 52)
    for cat, amt in sorted(cat_totals.items(), key=lambda x: x[1], reverse=True):
        pct = (amt / total_spend * 100.0) if total_spend > 0 else 0.0
        print(f"{cat:<20} {cat_counts[cat]:>6} {amt:>13,.2f} {pct:>8.1f}%")

    # Participant balance summary (equal split assumption per logged bill)
    person_totals: dict[str, float] = {}
    for r in records:
        for person in r.participants:
            person_totals[person] = round(person_totals.get(person, 0.0) + r.per_person_share, 2)

    print("\n" + style("--- Cumulative Share per Participant ---", ANSI.BOLD, ANSI.CYAN))
    print(f"{'Participant':<20} {'Cumulative Share (₹)':>22}")
    print("-" * 44)
    for person, amt in sorted(person_totals.items(), key=lambda x: x[1], reverse=True):
        print(f"{person:<20} {amt:>22,.2f}")

    # Threshold warnings
    flagged = [r for r in records if r.flags]
    if flagged:
        print("\n" + style("--- Threshold Warnings ---", ANSI.BOLD, ANSI.YELLOW))
        for r in flagged:
            print(f"  {style('!', ANSI.YELLOW)} {r.bill_id} ({r.title}): {', '.join(r.flags)}")


def export_markdown_report(records: list[BillRecord]) -> Path:
    ensure_directories()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = EXPORTS_DIR / f"bill_splitter_report_{stamp}.md"

    total_spend = sum(r.total_amount for r in records)
    lines = [
        "# Bill Splitter — Summary Report",
        "",
        f"- **Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"- **Total Bills:** {len(records)}",
        f"- **Grand Total:** ₹{total_spend:,.2f}",
        "",
        "## Recorded Bills",
        "",
        "| ID | Title | Category | Total (₹) | Share/Person (₹) | Participants | Flags |",
        "| --- | --- | --- | ---: | ---: | --- | --- |",
    ]

    for r in records:
        people = ", ".join(r.participants)
        flags = ", ".join(r.flags) if r.flags else "-"
        lines.append(
            f"| {r.bill_id} | {r.title} | {r.category} | {r.total_amount:.2f} | "
            f"{r.per_person_share:.2f} | {people} | {flags} |"
        )

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def export_chart(records: list[BillRecord]) -> Path | None:
    if not HAS_MATPLOTLIB:
        print(
            style(
                "[INFO] Matplotlib is not installed. Install with `pip install matplotlib` to generate charts.",
                ANSI.YELLOW,
            )
        )
        return None
    if not records:
        print(style("[INFO] No records to plot.", ANSI.YELLOW))
        return None

    ensure_directories()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    chart_path = EXPORTS_DIR / f"bill_trends_{stamp}.png"

    cat_totals: dict[str, float] = {}
    for r in records:
        cat_totals[r.category] = cat_totals.get(r.category, 0.0) + r.total_amount

    labels = [r.bill_id[-3:] + "\n" + r.title[:10] for r in records]
    totals = [r.total_amount for r in records]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))

    ax1.plot(range(len(records)), totals, marker="o", linewidth=2)
    ax1.set_title("Bill Totals Trend (₹)")
    ax1.set_xticks(range(len(records)))
    ax1.set_xticklabels(labels, rotation=35, ha="right", fontsize=8)
    ax1.set_ylabel("Amount (₹)")
    ax1.grid(True, linestyle="--", alpha=0.5)

    cats = list(cat_totals.keys())
    cat_vals = list(cat_totals.values())
    ax2.bar(cats, cat_vals)
    ax2.set_title("Spend by Category (₹)")
    ax2.tick_params(axis="x", rotation=30, labelsize=8)
    ax2.set_ylabel("Total (₹)")
    ax2.grid(True, axis="y", linestyle="--", alpha=0.5)

    plt.tight_layout()
    plt.savefig(chart_path, dpi=150)
    plt.close(fig)
    return chart_path


# ==============================================================================
# Interactive Menu & Application Loop
# ==============================================================================
def print_banner() -> None:
    print(style("\n" + "=" * 60, ANSI.CYAN))
    print(style("   BILL SPLITTER  |  Smart Group Expense & Analytics CLI   ", ANSI.BOLD, ANSI.WHITE))
    print(style("   Local JSON/CSV Storage • Input Guardrails • Trend Charts ", ANSI.DIM))
    print(style("=" * 60, ANSI.CYAN))


def print_menu() -> None:
    print(style("\nMain Menu:", ANSI.BOLD, ANSI.BLUE))
    print("  1. Record a New Group Bill")
    print("  2. View All Bills")
    print("  3. Search & Filter Bills")
    print("  4. Run Analytics & Summary")
    print("  5. Export Report (Markdown) & Chart (PNG)")
    print("  6. Import Legacy CSV Dataset")
    print("  7. Save & Exit")


def handle_add_bill(records: list[BillRecord]) -> list[BillRecord]:
    print(style("\n--- Record a New Group Bill ---", ANSI.BOLD, ANSI.GREEN))
    title = prompt_non_empty("Bill title (e.g., Dinner at Mainland China)")
    category = prompt_category()
    base_amount = prompt_float("Base bill amount in ₹ (> 0)", min_val=0.01)
    tip_percent = prompt_float("Tip percentage (0 to 100)", min_val=0.0, max_val=100.0)
    participants = prompt_participants()
    notes = input(style("Optional notes (press Enter to skip): ", ANSI.CYAN)).strip()

    record = compute_bill_split(
        title=title,
        category=category,
        base_amount=base_amount,
        tip_percent=tip_percent,
        participants=participants,
        existing_count=len(records),
        notes=notes,
    )
    records.append(record)
    save_records_json(records)
    sync_records_csv(records)

    print(style("\n[SAVED] Bill recorded and persisted to JSON & CSV:", ANSI.GREEN, ANSI.BOLD))
    print(f"  ID          : {record.bill_id}")
    print(f"  Total Bill  : ₹{record.total_amount:,.2f} (includes {record.tip_percent:.1f}% tip)")
    print(f"  Split Among : {', '.join(record.participants)} ({len(record.participants)} people)")
    print(f"  Per Person  : {style(f'₹{record.per_person_share:,.2f}', ANSI.BOLD, ANSI.YELLOW)}")
    for flag in record.flags:
        print(style(f"  [ALERT] {flag}", ANSI.YELLOW))

    return records


def handle_search(records: list[BillRecord]) -> None:
    print(style("\n--- Search & Filter Bills ---", ANSI.BOLD, ANSI.CYAN))
    keyword = input(style("Keyword in title, participant, or notes (or Enter for any): ", ANSI.CYAN)).strip().lower()
    cat_filter = input(style("Category filter name (or Enter for any): ", ANSI.CYAN)).strip().lower()

    results = []
    for r in records:
        haystack = f"{r.title} {r.notes} {' '.join(r.participants)}".lower()
        kw_ok = not keyword or keyword in haystack
        cat_ok = not cat_filter or cat_filter in r.category.lower()
        if kw_ok and cat_ok:
            results.append(r)

    print_records_table(results)


def run() -> None:
    print_banner()
    records = load_records()
    print(style(f"[READY] Loaded {len(records)} bill record(s) from {JSON_STORE}.", ANSI.GREEN))

    while True:
        print_menu()
        choice = input(style("\nChoose an option (1-7): ", ANSI.CYAN)).strip()

        try:
            if choice == "1":
                records = handle_add_bill(records)
            elif choice == "2":
                print_records_table(records)
            elif choice == "3":
                handle_search(records)
            elif choice == "4":
                show_analytics(records)
            elif choice == "5":
                md_path = export_markdown_report(records)
                print(style(f"\n[EXPORTED] Markdown report saved to: {md_path}", ANSI.GREEN))
                chart_path = export_chart(records)
                if chart_path:
                    print(style(f"[EXPORTED] Trend chart saved to: {chart_path}", ANSI.GREEN))
            elif choice == "6":
                csv_input = prompt_non_empty("Enter CSV file path to import")
                records, added, rejected = import_csv_dataset(csv_input, records)
                save_records_json(records)
                sync_records_csv(records)
                print(
                    style(
                        f"[IMPORT COMPLETE] Added {added} record(s), skipped {rejected} invalid row(s).",
                        ANSI.GREEN,
                    )
                )
            elif choice == "7":
                save_records_json(records)
                sync_records_csv(records)
                print(style("\nAll data saved cleanly. See you next time!", ANSI.CYAN))
                break
            else:
                print(style("  [!] Please select a valid menu option from 1 to 7.", ANSI.RED))
        except KeyboardInterrupt:
            print(style("\n\n[INTERRUPTED] Saving state before exit...", ANSI.YELLOW))
            save_records_json(records)
            sync_records_csv(records)
            sys.exit(0)
        except Exception as exc:
            print(style(f"  [ERROR] Operation failed safely: {exc}", ANSI.RED))


if __name__ == "__main__":
    run()