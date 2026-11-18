import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from html.parser import HTMLParser
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "static_summary_pages"
sys.path.insert(0, str(PROJECT_ROOT))

from static_summary_pages.summary_pages_generator import (
    export_dashboard,
)


class MarkupIndex(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.panel_attrs: dict[str, str] = {}
        self.tabs: list[dict[str, str]] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = {key: value or "" for key, value in attrs}
        if attributes.get("id") == "ranking-panel":
            self.panel_attrs = attributes
        if attributes.get("role") == "tab":
            self.tabs.append(attributes)


class TestStaticDashboardMarkup:
    def test_ranking_tabs_are_accessible_and_share_a_panel(self) -> None:
        markup = MarkupIndex()
        markup.feed((STATIC_ROOT / "index.html").read_text(encoding="utf-8"))

        assert markup.panel_attrs["role"] == "tabpanel"
        assert len(markup.tabs) == 3
        assert all(
            tab.get("aria-controls") == "ranking-panel" for tab in markup.tabs
        )
        assert markup.tabs[0]["aria-selected"] == "true"
        assert markup.tabs[0]["tabindex"] == "0"
        assert markup.tabs[1]["tabindex"] == "-1"
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        assert html.index(
            ">Value-focused</button>") < html.index(">Balanced</button>")
        assert html.index(
            ">Balanced</button>") < html.index(">Protein-focused</button>")
        assert "overall-score-heading" not in html

    def test_keyboard_navigation_is_delegated_to_the_tablist(self) -> None:
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        assert 'document.addEventListener("keydown"' in app
        assert 'activeElement === document.body' in app
        assert 'activeElement?.closest("[role=\'tab\']")' in app

    def test_rankings_use_one_simple_heading(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        assert "Best value products" in html
        assert "Individual listings" not in html
        assert "Top product listings" not in html

    def test_comparison_metrics_are_optional_and_hidden_by_default(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        for column in (
            "cost-per-100-kcal",
            "protein-per-100-kcal",
            "cost-per-100g-protein",
        ):
            assert f'data-column-toggle value="{column}"' in html
            assert f'data-column="{column}" hidden' in html
            assert f'createMetricCell("{column}"' in app
        assert "function updateOptionalColumns()" in app

    def test_table_places_clickable_image_before_product_name(self) -> None:
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        assert 'const imageLink = createElement("a", "product-image-link", null);' in app
        assert 'imageLink.target = "_blank";' in app
        assert 'imageLink.rel = "noopener";' in app

        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        image_column = html.index('aria-label="Product image"')
        name_column = html.index("<th>Product/listing</th>")
        assert image_column < name_column
        assert "Calories (kcal)" in html
        assert "Protein (g)" in html
        assert html.index("</table>") < html.index(
            'class="scope-note">Calories and protein are totals'
        )

    def test_scope_note_is_removed(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        assert "Rolling recent-data snapshot" not in html


class TestStaticDashboardBrowserCode:
    def test_dynamic_values_use_dom_construction_or_text_content(self) -> None:
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        assert "replaceChildren" in app
        assert "textContent" in app
        assert 'textContent = `Unable to load dashboard data:' in app

    def test_source_urls_allow_only_web_schemes(self) -> None:
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        assert '["https:", "http:"].includes(url.protocol)' in app
        assert 'function safeSourceUrl(value)' in app


class TestDashboardDataPayload:
    def test_export_has_empty_malicious_and_normal_usable_values(
        self, tmp_path: Path
    ) -> None:
        normal = {
            "retailer_listing_id": 1,
            "retailer_listing_name": "Chicken breast",
            "canonical_product_name": "Chicken breast",
            "retailer_id": 1,
            "retailer_name": "Example retailer",
            "brand_name": "Example brand",
            "retailer_listing_source_url": "https://example.com/product",
            "retailer_listing_image_url": "https://example.com/image.jpg",
            "canonical_barcode_gtin": "1234567890123",
            "snapshot_price": 2.5,
            "snapshot_package_quantity": 300,
            "snapshot_package_unit": "g",
            "total_energy_kcal": 330,
            "total_protein_g": 69,
            "cost_per_100_kcal": 0.76,
            "cost_per_100_kcal_normalized_score": 75,
            "protein_g_per_100_kcal": 20.91,
            "cost_per_100g_protein": 3.62,
            "cost_per_100g_protein_normalized_score": 80,
            "value_score": 75,
            "protein_score": 80,
            "balanced_overall_score": 78,
            "value_focused_overall_score": 76,
            "protein_focused_overall_score": 79,
            "scrape_run_finished_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
            "canonical_product_id": 1,
            "brand_id": 1,
        }
        empty_name = {
            **normal,
            "retailer_listing_id": 2,
            "retailer_listing_name": None,
        }
        malicious = {
            **normal,
            "retailer_listing_id": 3,
            "retailer_listing_name": '<img src=x onerror="alert(1)">',
            "retailer_listing_source_url": "javascript:alert(1)",
        }
        settings = {
            "DATABASE_HOST": "localhost",
            "DATABASE_PORT": "5432",
            "DATABASE_NAME": "test_db",
            "DATABASE_USER": "test_user",
            "DATABASE_PASSWORD": "test_password",
        }
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [normal, empty_name, malicious]
        cursor.fetchone.return_value = {
            "active_listings": 3,
            "listings_with_barcode": 3,
            "listings_with_image": 3,
            "listings_with_source": 3,
            "total_listings": 3,
        }

        with (
            patch(
                "static_summary_pages.summary_pages_generator.load_database_settings",
                return_value=settings,
            ),
            patch(
                "static_summary_pages.summary_pages_generator.psycopg.connect",
                return_value=MagicMock(),
            ) as connect,
        ):
            connect.return_value.__enter__.return_value = connection
            output_path = tmp_path / "dashboard-data.json"
            export_dashboard(output_path)

        payload = json.loads(output_path.read_text(encoding="utf-8"))

        assert payload["kpis"]
        assert payload["retailers"]
        assert all(payload["rankings"].values())

        exported = {
            product["retailer_listing_id"]: product
            for product in payload["rankings"]["value"]
        }
        normal_product = exported[1]
        assert normal_product["name"] == "Chicken breast"
        assert normal_product["source_url"].startswith("https://")
        assert "nutrition_basis" not in normal_product
        assert normal_product["energy_kcal"] > 0
        assert normal_product["protein_g"] > 0
        assert "cost_per_100g_protein" in normal_product
        assert "price_per_protein_g" not in normal_product
        assert 0 <= normal_product["value_score"] <= 100
        assert 0 <= normal_product["protein_score"] <= 100
        for field in (
            "balanced_overall_score",
            "value_focused_overall_score",
            "protein_focused_overall_score",
        ):
            assert 0 <= normal_product[field] <= 100
        assert exported[2]["name"] is None
        assert "<img" in exported[3]["name"]
        assert exported[3]["source_url"].startswith("javascript:")

    def test_overview_uses_focused_kpi_labels(self) -> None:
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        for label in (
            "In-stock product count",
            "Retailers",
            "Brands",
            "Average cost / 100 kcal",
            "Average protein / 100 kcal",
            "Average cost / 100 g protein",
        ):
            assert label in app
        assert "Average value score" not in app
        assert "Average listed price" not in app

    def test_coverage_cards_follow_requested_order(self) -> None:
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        coverage_block = app[app.index("function renderCoverage()"):]
        active = coverage_block.index('["Active listings"')
        eligible = coverage_block.index('["Eligible in stock"')
        retailers = coverage_block.index('["Retailers"')
        brands = coverage_block.index('["Brands"')
        assert active < eligible < retailers < brands

    def test_retailer_comparison_uses_one_measure_selector(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        app = (STATIC_ROOT / "app.js").read_text(encoding="utf-8")
        assert html.count('class="measure-control"') == 1
        assert '<option value="average_value_score">Value score</option>' in html
        assert '<option value="average_protein_score">Protein score</option>' in html
        assert '<option value="listing_count">Listing count</option>' in html
        assert '$("#value-measure").addEventListener("change", renderRetailerChart)' in app
        assert '$("#retailer-measure")' not in app


class TestSummaryPagesGenerator:
    def test_export_scopes_connection_context(self, tmp_path: Path) -> None:
        settings = {
            "DATABASE_HOST": "localhost",
            "DATABASE_PORT": "5432",
            "DATABASE_NAME": "test_db",
            "DATABASE_USER": "test_user",
            "DATABASE_PASSWORD": "test_password",
        }
        connection = MagicMock()
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = []
        cursor.fetchone.return_value = {
            "active_listings": 0,
            "listings_with_barcode": 0,
            "listings_with_image": 0,
            "listings_with_source": 0,
            "total_listings": 0,
        }

        with (
            patch(
                "static_summary_pages.summary_pages_generator.load_database_settings",
                return_value=settings,
            ),
            patch(
                "static_summary_pages.summary_pages_generator.psycopg.connect",
                return_value=MagicMock()
            ) as connect,
        ):
            connect.return_value.__enter__.return_value = connection
            payload = export_dashboard(tmp_path / "dashboard-data.json")

        connect.assert_called_once_with(
            host="localhost",
            port="5432",
            dbname="test_db",
            user="test_user",
            password="test_password",
        )
        connect.return_value.__exit__.assert_called_once()
        assert payload["kpis"]["individual_listings"] == 0
