"""Export current Protein Source Helper data for the static dashboard."""

import argparse
import json
import os
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import psycopg
from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_DATA = (
    PROJECT_ROOT
    / "static_summary_pages"
    / "data"
    / "dashboard-data.json"
)


def load_database_settings() -> dict[str, str]:
    env_file = PROJECT_ROOT / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)
    else:
        load_dotenv(PROJECT_ROOT / "local.env", override=False)

    required = (
        "DATABASE_HOST",
        "DATABASE_PORT",
        "DATABASE_NAME",
        "DATABASE_USER",
        "DATABASE_PASSWORD",
    )
    missing = [name for name in required if not os.environ.get(name)]
    if missing:
        raise RuntimeError("Missing database settings: " + ", ".join(missing))
    return {name: os.environ[name] for name in required}


def valid_number(value):
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    return None


def mean(rows, field):
    values = [valid_number(row[field]) for row in rows]
    values = [value for value in values if value is not None]
    return round(sum(values) / len(values), 2) if values else None


def mean_scaled(rows, field, multiplier):
    value = mean(rows, field)
    return round(value * multiplier, 2) if value is not None else None


def as_product(row):
    return {
        "retailer_listing_id": row["retailer_listing_id"],
        "name": row["retailer_listing_name"],
        "canonical_product_name": row["canonical_product_name"],
        "retailer_id": row["retailer_id"],
        "retailer_name": row["retailer_name"],
        "brand_name": row["brand_name"],
        "source_url": row["retailer_listing_source_url"],
        "image_url": row["retailer_listing_image_url"],
        "barcode": row["canonical_barcode_gtin"],
        "price": valid_number(row["snapshot_price"]),
        "package_quantity": valid_number(row["snapshot_package_quantity"]),
        "package_unit": row["snapshot_package_unit"],
        "energy_kcal": valid_number(row["total_energy_kcal"]),
        "protein_g": valid_number(row["total_protein_g"]),
        "cost_per_100_kcal": valid_number(row["cost_per_100_kcal"]),
        "cost_per_100_kcal_normalized_score": valid_number(
            row["cost_per_100_kcal_normalized_score"]
        ),
        "protein_g_per_100_kcal": valid_number(row["protein_g_per_100_kcal"]),
        "cost_per_100g_protein": valid_number(row["cost_per_100g_protein"]),
        "cost_per_100g_protein_normalized_score": valid_number(
            row["cost_per_100g_protein_normalized_score"]
        ),
        "value_score": valid_number(row["value_score"]),
        "protein_score": valid_number(row["protein_score"]),
        "balanced_overall_score": valid_number(row["balanced_overall_score"]),
        "value_focused_overall_score": valid_number(
            row["value_focused_overall_score"]
        ),
        "protein_focused_overall_score": valid_number(
            row["protein_focused_overall_score"]
        ),
    }


def export_dashboard(output_path: Path = DASHBOARD_DATA) -> dict:
    settings = load_database_settings()
    with psycopg.connect(
        host=settings["DATABASE_HOST"],
        port=settings["DATABASE_PORT"],
        dbname=settings["DATABASE_NAME"],
        user=settings["DATABASE_USER"],
        password=settings["DATABASE_PASSWORD"],
    ) as connection:
        with connection.cursor(row_factory=psycopg.rows.dict_row) as cursor:
            cursor.execute("""
                SELECT *
                FROM protein_source_helper.current_data
                WHERE snapshot_out_of_stock = false
                  AND retailer_listing_active = true
            """)
            rows = cursor.fetchall()

            cursor.execute("""
                SELECT
                    count(*) FILTER (WHERE retailer_listing_active) AS active_listings,
                    count(*) FILTER (
                        WHERE canonical_barcode_gtin IS NOT NULL
                    ) AS listings_with_barcode,
                    count(*) FILTER (
                        WHERE retailer_listing_image_url IS NOT NULL
                          AND retailer_listing_image_url <> ''
                    ) AS listings_with_image,
                    count(*) FILTER (
                        WHERE retailer_listing_source_url IS NOT NULL
                          AND retailer_listing_source_url <> ''
                    ) AS listings_with_source,
                    count(*) AS total_listings
                FROM (
                    SELECT
                        rl.retailer_listing_active,
                        cp.barcode_gtin AS canonical_barcode_gtin,
                        rl.retailer_listing_image_url,
                        rl.retailer_listing_source_url
                    FROM protein_source_helper.retailer_listing rl
                    LEFT JOIN protein_source_helper.canonical_product cp
                        ON rl.canonical_product_id = cp.canonical_product_id
                    INNER JOIN protein_source_helper.retailer r
                        ON rl.retailer_id = r.retailer_id
                    WHERE r.retailer_active = true
                ) coverage
            """)
            coverage = cursor.fetchone()

    latest_scrape = max(
        (row["scrape_run_finished_at"] for row in rows),
        default=None,
    )

    unique_retailer_ids = {row["retailer_id"] for row in rows}
    unique_product_ids = {
        row["canonical_product_id"]
        for row in rows
        if row["canonical_product_id"] is not None
    }
    unique_brand_ids = {
        row["brand_id"] for row in rows if row["brand_id"] is not None
    }

    retailer_groups = {}
    for row in rows:
        retailer_groups.setdefault(row["retailer_id"], {
            "retailer_id": row["retailer_id"],
            "retailer_name": row["retailer_name"],
            "rows": [],
        })["rows"].append(row)

    retailers = []
    for retailer in retailer_groups.values():
        retailer_rows = retailer.pop("rows")
        retailer["listing_count"] = len(retailer_rows)
        retailer["average_value_score"] = mean(retailer_rows, "value_score")
        retailer["average_protein_score"] = mean(
            retailer_rows, "protein_score")
        retailers.append(retailer)
    retailers.sort(
        key=lambda retailer: (
            -(retailer["average_value_score"] or float("-inf")),
            retailer["retailer_name"] or "",
        )
    )

    def ranked_products(field):
        valid = [row for row in rows if valid_number(row[field]) is not None]
        if field in ("cost_per_100_kcal", "cost_per_100g_protein"):
            valid.sort(key=lambda row: (
                row[field], row["retailer_listing_id"]))
        else:
            valid.sort(
                key=lambda row: (row[field], row["retailer_listing_id"]),
                reverse=True,
            )
        return [as_product(row) for row in valid[:25]]

    export_timestamp = datetime.now(timezone.utc).isoformat()

    payload = {
        "export_timestamp": export_timestamp,
        "latest_scrape_finished_at": (
            latest_scrape.isoformat() if latest_scrape else None
        ),
        "currency": "GBP",
        "kpis": {
            "individual_listings": len({
                row["retailer_listing_id"] for row in rows
            }),
            "canonical_products": len(unique_product_ids),
            "retailers": len(unique_retailer_ids),
            "brands": len(unique_brand_ids),
            "average_listed_price": mean(rows, "snapshot_price"),
            "average_cost_per_100_kcal": mean(rows, "cost_per_100_kcal"),
            "average_protein_per_100_kcal": mean(
                rows, "protein_g_per_100_kcal"
            ),
            "average_value_score": mean(rows, "value_score"),
            "average_protein_score": mean(rows, "protein_score"),
            "average_cost_per_100g_protein": mean(
                rows, "cost_per_100g_protein"
            ),
        },
        "coverage": {
            "active_listings": coverage["active_listings"],
            "eligible_in_stock_listings": len({
                row["retailer_listing_id"] for row in rows
            }),
            "total_listings": coverage["total_listings"],
            "listings_with_barcode": coverage["listings_with_barcode"],
            "listings_with_image": coverage["listings_with_image"],
            "listings_with_source": coverage["listings_with_source"],
        },
        "retailers": retailers,
        "rankings": {
            "value": ranked_products("value_score"),
            "protein": ranked_products("protein_score"),
            "balanced_overall": ranked_products("balanced_overall_score"),
            "value_focused_overall": ranked_products(
                "value_focused_overall_score"
            ),
            "protein_focused_overall": ranked_products(
                "protein_focused_overall_score"
            ),
            "cost_per_100_kcal": ranked_products("cost_per_100_kcal"),
            "cost_per_100g_protein": ranked_products("cost_per_100g_protein"),
        },
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DASHBOARD_DATA)
    args = parser.parse_args()
    payload = export_dashboard(args.output)
    print(json.dumps({
        "output": str(args.output),
        "individual_listings": payload["kpis"]["individual_listings"],
        "retailers": payload["kpis"]["retailers"],
    }))


if __name__ == "__main__":
    main()
