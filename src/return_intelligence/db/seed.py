from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from ..config import DEFAULT_DEMO_CLOCK
from .connection import transaction
from .fixtures import ORDERS, PRODUCTS
from .repositories import Repository

DEMO_DATE = DEFAULT_DEMO_CLOCK


def seed_database(db_path: Path | str, project_root: Path | str | None = None) -> dict:
    path = Path(db_path)
    repo = Repository(path)
    repo.initialize()
    with transaction(path, True) as connection:
        connection.executemany(
            "INSERT OR IGNORE INTO products(sku,model_id,name,season_profile,similar_group,active) VALUES(?,?,?,?,?,?)",
            PRODUCTS,
        )
        for sku, *_ in PRODUCTS:
            connection.execute(
                "INSERT OR IGNORE INTO batches VALUES(?,?,?,1)",
                (f"SYN-B-{sku}", sku, "2025-10-01"),
            )
        for index, (order_id, sku, size, color, returnable, delivered) in enumerate(ORDERS, 1):
            connection.execute(
                "INSERT OR IGNORE INTO orders VALUES(?,?,?,?,1)",
                (order_id, "2025-12-15", "DELIVERED" if delivered else "NOT_DELIVERED", "SYN-ZONE-1"),
            )
            connection.execute(
                "INSERT OR IGNORE INTO order_items VALUES(?,?,?,?,?,?,?,?,?)",
                (f"SYN-OI-{index:03}", order_id, sku, f"SYN-B-{sku}", size, color, 1, returnable, delivered),
            )
        destinations = [
            (
                "SYN-STORE-1",
                "ALDO Downtown Demo Store",
                "RETAIL_STORE",
                "SYN-ZONE-1",
                "1000 Sainte-Catherine St W, Montréal, QC H3B 1E2 (DEMO)",
                1,
                1,
                100,
                30,
                12,
                0.25,
                0.90,
                "OPEN",
            ),
            (
                "SYN-STORE-2",
                "ALDO North Demo Store",
                "RETAIL_STORE",
                "SYN-ZONE-2",
                "1500 Jean-Talon St E, Montréal, QC H2E 1S1 (DEMO)",
                1,
                1,
                120,
                50,
                8,
                0.30,
                0.70,
                "OPEN",
            ),
            (
                "SYN-OUTLET-1",
                "Synthetic Outlet East",
                "OUTLET",
                "SYN-ZONE-2",
                "200 Demo Outlet Rd, Montréal, QC (INTERNAL DEMO)",
                1,
                0,
                200,
                80,
                20,
                0.35,
                0.80,
                "OPEN",
            ),
            (
                "SYN-OUTLET-2",
                "Synthetic Outlet West",
                "OUTLET",
                "SYN-ZONE-3",
                "300 Demo Outlet Rd, Montréal, QC (INTERNAL DEMO)",
                1,
                0,
                180,
                70,
                15,
                0.40,
                0.75,
                "OPEN",
            ),
            (
                "SYN-WH-1",
                "Synthetic Company Warehouse",
                "COMPANY_WAREHOUSE",
                "SYN-ZONE-4",
                "400 Demo Logistics Rd, Montréal, QC (INTERNAL DEMO)",
                1,
                0,
                500,
                200,
                40,
                0.20,
                0.60,
                "OPEN",
            ),
        ]
        connection.executemany(
            "INSERT OR IGNORE INTO destinations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            destinations,
        )
        for index, destination in enumerate(destinations):
            connection.execute(
                "INSERT OR IGNORE INTO destination_distances VALUES(?,?,?)",
                ("SYN-ZONE-1", destination[0], 5 + index * 12),
            )
        inventory = [
            ("SYN-RUNNER-100", "9", "Blue", "SYN-STORE-1", 8, 1),
            ("SYN-RUNNER-100", "10", "Blue", "SYN-STORE-1", 0, 0),
            ("SYN-RUNNER-100", "8", "Red", "SYN-STORE-1", 4, 0),
            ("SYN-RUNNER-110", "8", "White", "SYN-STORE-1", 5, 0),
            ("SYN-SANDAL-200", "7", "Tan", "SYN-OUTLET-1", 3, 0),
            ("SYN-BOOT-300", "9", "Black", "SYN-OUTLET-1", 2, 0),
        ]
        connection.executemany("INSERT OR IGNORE INTO inventory VALUES(?,?,?,?,?,?)", inventory)
        sales = [
            ("SYN-SALE-R8", "2025-10-17", "2026-01-15", "SYN-RUNNER-100", "8", "Blue", "SYN-B-SYN-RUNNER-100", 25),
            ("SYN-SALE-R9", "2025-10-17", "2026-01-15", "SYN-RUNNER-100", "9", "Blue", "SYN-B-SYN-RUNNER-100", 100),
            ("SYN-SALE-ALT", "2025-10-17", "2026-01-15", "SYN-RUNNER-110", "8", "White", "SYN-B-SYN-RUNNER-110", 100),
        ]
        connection.executemany("INSERT OR IGNORE INTO sales_volume VALUES(?,?,?,?,?,?,?,?)", sales)
        for index in range(4):
            connection.execute(
                "INSERT OR IGNORE INTO historical_complaints VALUES(?,?,?,?,?,?,?,?, 'SYNTHETIC')",
                (
                    f"SYN-HC-{index + 1}",
                    f"2025-12-{10 + index:02}T12:00:00+00:00",
                    "SYN-RUNNER-100",
                    "8",
                    "Blue",
                    "SYN-B-SYN-RUNNER-100",
                    "Wrong Size",
                    "too_small",
                ),
            )
        connection.execute(
            "INSERT OR IGNORE INTO historical_complaints VALUES(?,?,?,?,?,?,?,?, 'SYNTHETIC')",
            (
                "SYN-HC-BASE",
                "2025-12-12T12:00:00+00:00",
                "SYN-RUNNER-100",
                "9",
                "Blue",
                "SYN-B-SYN-RUNNER-100",
                "Wrong Size",
                "too_small",
            ),
        )
    return {
        "products": repo.one("SELECT count(*) n FROM products")["n"],
        "orders": repo.one("SELECT count(*) n FROM orders")["n"],
        "synthetic": True,
    }


def reset_database(db_path: Path | str, project_root: Path | str, confirm: bool = False):
    if not confirm:
        raise ValueError("reset requires --confirm-synthetic-only")
    root = Path(project_root).resolve()
    path = Path(db_path).resolve()
    allowed = (root / "data").resolve()
    if allowed not in path.parents:
        raise ValueError("refusing to reset a database outside project data/")
    for suffix in ("", "-wal", "-shm"):
        candidate = Path(str(path) + suffix)
        if candidate.exists():
            candidate.unlink()
    for folder in (root / "uploads", root / "artifacts"):
        if folder.exists():
            for child in folder.iterdir():
                if child.name != ".gitkeep":
                    shutil.rmtree(child) if child.is_dir() else child.unlink()
    return seed_database(path, root)


def generate_fixture_images(root: Path):
    target = root / "tests" / "fixtures" / "generated"
    target.mkdir(parents=True, exist_ok=True)
    for key, color in {
        "unclear": "gray",
        "eligible_a_95": "green",
        "eligible_75": "gold",
        "eligible_a_90": "olive",
        "worn_ineligible": "brown",
        "worn_low_confidence": "sienna",
        "suspected_defect": "red",
        "defect_low_confidence": "maroon",
    }.items():
        for angle in ("front", "left", "right"):
            path = target / f"{key}-{angle}.png"
            if not path.exists():
                image = Image.new("RGB", (800, 600), color)
                ImageDraw.Draw(image).text((30, 30), f"SYNTHETIC {key} {angle}", fill="white")
                image.save(path)
    return target


def main():
    parser = argparse.ArgumentParser(description="Seed/reset synthetic local demo data")
    parser.add_argument("--db", default="data/return_intelligence.db")
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--confirm-synthetic-only", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    result = (
        reset_database(args.db, root, args.confirm_synthetic_only)
        if args.reset
        else seed_database(args.db, root)
    )
    generate_fixture_images(root)
    print(f"Seeded synthetic local data: {result}")


if __name__ == "__main__":
    main()
