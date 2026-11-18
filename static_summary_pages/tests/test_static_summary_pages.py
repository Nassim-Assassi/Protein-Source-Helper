from static_summary_pages.summary_pages_generator import (
    export_dashboard,
)
import json
import sys
from pathlib import Path
from html.parser import HTMLParser
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
STATIC_ROOT = PROJECT_ROOT / "static_summary_pages"
sys.path.insert(0, str(PROJECT_ROOT))


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
    def test_export_has_empty_malicious_and_normal_usable_values(self) -> None:
        payload = json.loads(
            (STATIC_ROOT / "data" / "dashboard-data.json").read_text(
                encoding="utf-8"
            )
        )

        assert payload["kpis"]
        assert payload["retailers"]
        assert all(payload["rankings"].values())

        normal = payload["rankings"]["value"][0]
        assert normal["name"]
        assert normal["source_url"].startswith("https://")
        assert "nutrition_basis" not in normal
        assert normal["energy_kcal"] > 0
        assert normal["protein_g"] > 0
        assert "cost_per_100g_protein" in normal
        assert "price_per_protein_g" not in normal
        assert 0 <= normal["value_score"] <= 100
        assert 0 <= normal["protein_score"] <= 100
        for field in (
            "balanced_overall_score",
            "value_focused_overall_score",
            "protein_focused_overall_score",
        ):
            assert 0 <= normal[field] <= 100

        empty_name = {**normal, "name": None}
        malicious_name = {**normal, "name": '<img src=x onerror="alert(1)">'}
        malicious_url = {**normal, "source_url": "javascript:alert(1)"}

        assert empty_name["name"] is None
        assert "<img" in malicious_name["name"]
        assert malicious_url["source_url"].startswith("javascript:")

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

    def test_retailer_comparison_defaults_to_listing_count(self) -> None:
        html = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
        assert '<option value="listing_count">Listing count</option>' in html
        assert "average_value_score" not in html


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
