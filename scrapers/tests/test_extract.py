import logging
from unittest.mock import Mock, call, patch

import pytest
from bs4 import BeautifulSoup

from scrapers.morrisons_scraper import extract
from scrapers.morrisons_scraper.extract import _nutrition_table


class TestNutritionTable:
    def test_selects_per_item_column_for_count_pack_without_weight(self) -> None:
        markup = """
        <table class="nutrition">
            <tr>
                <th>Typical Values</th>
                <th>100g contains</th>
                <th>Each swirl contains</th>
            </tr>
            <tr><td>Energy</td><td>300kcal</td><td>151kcal</td></tr>
            <tr><td>Protein</td><td>7.7g</td><td>3.9g</td></tr>
        </table>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser"),
            "St Pierre Brioche Swirls 6 Pack",
            prefer_per_item=True,
        )

        assert nutrition["energy_kcal"] == "151"
        assert nutrition["protein_g"] == "3.9g"
        assert basis == "per_item"

    def test_extracts_per_100g_and_each_serving_weight(self) -> None:
        markup = """
        <table class="nutrition">
            <tr>
                <th>Typical Values</th>
                <th>100g contains</th>
                <th>Each swirl (50g) contains</th>
            </tr>
            <tr><td>Energy</td><td>1264kJ</td><td>635kJ</td></tr>
            <tr><td></td><td>300kcal</td><td>151kcal</td></tr>
            <tr><td>Protein</td><td>7.7g</td><td>3.9g</td></tr>
        </table>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser"),
            "St Pierre Brioche Swirls 6 Pack",
        )

        assert nutrition["energy_kcal"] == "300"
        assert nutrition["protein_g"] == "7.7g"
        assert nutrition["serving_size_g"] == "50"
        assert basis == "per_100g"

    def test_selects_product_component_table_when_multiple_are_present(
        self,
    ) -> None:
        markup = """
        <div>
            Hot Honey:<br/>
            <table class="nutrition">
                <tr><th>Typical Values</th><th>Per 100ml</th></tr>
                <tr><td>Energy</td><td>1377kJ / 324kcal</td></tr>
                <tr><td>Protein</td><td>0g</td></tr>
            </table>
            <br/><br/>Pizza:<br/>
            <table class="nutrition">
                <tr>
                    <th>Typical Values</th>
                    <th>when heated according to instructions Per 100g</th>
                    <th>Per 1/2 Pizza</th>
                </tr>
                <tr><td>Energy</td><td>1234kJ / 294kcal</td><td>623kcal</td></tr>
                <tr><td>Protein</td><td>15.3g</td><td>32.4g</td></tr>
            </table>
        </div>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser"),
            "Zizzi Rustica Sticky Pig Pizza 443g",
        )

        assert nutrition["energy_kcal"] == "294"
        assert nutrition["protein_g"] == "15.3g"
        assert basis == "per_100g"

    def test_extracts_kcal_after_parenthesized_kj_value(self) -> None:
        markup = """
        <table class="nutrition">
            <tr>
                <th>Typical Values</th><th>Per 100g</th>
                <th>1 serving (150g)</th>
            </tr>
            <tr><td>Energy, (kJ) kcal</td><td>(330) 79</td><td>(495) 119</td></tr>
            <tr><td>Fat (g)</td><td>3.0</td><td>4.5</td></tr>
            <tr><td>Protein (g)</td><td>9.0</td><td>14</td></tr>
        </table>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser")
        )

        assert nutrition["energy_kcal"] == "79"
        assert nutrition["protein_g"] == "9.0"
        assert basis == "per_100g"

    def test_extracts_nutrition_from_unit_and_basis_columns(self) -> None:
        markup = """
        <table class="nutrition">
            <tr>
                <th>Typical Values</th><th>Unit</th>
                <th>Per 100 g</th><th>Per portion (15 g)</th>
            </tr>
            <tr><td>Energy</td><td>(kJ</td><td>2252 /</td><td>336 /</td></tr>
            <tr><td></td><td>kcal)</td><td>539</td><td>80</td></tr>
            <tr><td>Fat</td><td>(g)</td><td>30.9</td><td>4.6</td></tr>
            <tr><td>Protein</td><td>(g)</td><td>6.3</td><td>0.9</td></tr>
            <tr><td>Salt</td><td>(g)</td><td>0.107</td><td>0.016</td></tr>
        </table>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser")
        )

        assert nutrition["energy_kcal"] == "539"
        assert nutrition["protein_g"] == "6.3"
        assert nutrition["fat_g"] == "30.9"
        assert nutrition["salt_g"] == "0.107"
        assert basis == "per_100g"

    def test_extracts_nutrition_from_div_rows(self) -> None:
        markup = """
        <section>
            <h2>Nutritional Data</h2>
            <div>
                <br/>This pack contains 6 Servings
                <span> </span>Per 100g<span> </span>Per Serving<br/>
                Energy kJ/kcal<span> </span>719kJ<span> </span>1394kJ<br/>
                171kcal<span> </span>332kcal<br/>
                Fat (g)<span> </span>5.9<span> </span>11<br/>
                Of which Saturates (g)<span> </span>1<span> </span>1.9<br/>
                Carbohydrate (g)<span> </span>25<span> </span>48<br/>
                Of which Sugars (g)<span> </span>4.9<span> </span>9.5<br/>
                Fibre (g)<span> </span>0.9<span> </span>1.7<br/>
                Protein (g)<span> </span>4.2<span> </span>8.2<br/>
                Salt (g)<span> </span>1.5<span> </span>3
            </div>
        </section>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser")
        )

        assert nutrition == {
            "energy_kcal": "171",
            "fat_g": "5.9",
            "saturates_g": "1",
            "carbohydrates_g": "25",
            "sugars_g": "4.9",
            "fibre_g": "0.9",
            "protein_g": "4.2",
            "salt_g": "1.5",
        }
        assert basis == "per_100g"

    def test_extracts_energy_when_kcal_value_follows_unit(self) -> None:
        markup = """
        <section>
            <h2>Nutritional Data</h2>
            <div>
                <br/>Per 100g<br/>
                Energy<br/>
                kJ 1199<br/>
                kcal 285<br/>
                Fat (g) 6.90<br/>
                Protein (g) 8.40
            </div>
        </section>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser")
        )

        assert nutrition["energy_kcal"] == "285"
        assert basis == "per_100g"

    def test_extracts_weight_from_fractional_cake_serving_header(self) -> None:
        markup = """
        <table class="nutrition">
            <tr>
                <th>Typical Values</th>
                <th>Per 100g:</th>
                <th>Per 1/8th of a Cake (32g):</th>
            </tr>
            <tr><td>Energy</td><td>1611kJ (382kcal)</td><td>517kJ (123kcal)</td></tr>
            <tr><td>Protein</td><td>4.8g</td><td>1.5g</td></tr>
        </table>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser")
        )

        assert nutrition["serving_size_g"] == "32"
        assert nutrition["protein_g"] == "4.8g"
        assert basis == "per_100g"

    def test_selects_named_per_item_column_for_counted_product(self) -> None:
        markup = """
        <table class="nutrition">
            <tr>
                <th>Typical Values</th>
                <th>Per 100g of product</th>
                <th>Per average bagel (50g)</th>
            </tr>
            <tr><td>Energy</td><td>1142kJ</td><td>571kJ</td></tr>
            <tr><td></td><td>272kcal</td><td>136kcal</td></tr>
            <tr><td>Protein</td><td>10.5g</td><td>5.3g</td></tr>
        </table>
        """

        nutrition, basis = _nutrition_table(
            BeautifulSoup(markup, "html.parser"),
            "Warburtons 6 Sesame Thin Bagels",
        )

        assert nutrition["energy_kcal"] == "136"
        assert nutrition["protein_g"] == "5.3g"
        assert nutrition["serving_size_g"] == "50"
        assert nutrition["serving_unit"] == "bagel"
        assert basis == "per_item"


class TestExtractProductsWithStats:
    @pytest.mark.parametrize(
        ("product_count", "log_level", "expect_progress"),
        [
            (99, logging.DEBUG, False),
            (100, logging.DEBUG, True),
            (100, logging.INFO, False),
        ],
    )
    def test_logs_progress_every_100_pages_only_at_debug_level(
        self, caplog, product_count: int, log_level: int,
        expect_progress: bool,
    ) -> None:
        product_categories = {
            f"https://example.com/product/{index}": "Category"
            for index in range(product_count)
        }
        caplog.set_level(log_level, logger="scrapers")

        with (
            patch.object(
                extract,
                "_crawl_product_categories",
                return_value=product_categories,
            ),
            patch.object(
                extract, "_extract_product", return_value={"product": {}}
            ),
        ):
            result = extract.extract_products_with_stats()

        assert len(result.products) == product_count
        assert result.failed_count == 0
        progress_messages = [
            record.getMessage()
            for record in caplog.records
            if record.getMessage().startswith("Extraction progress:")
        ]
        assert bool(progress_messages) is expect_progress
        if expect_progress:
            assert "100/100" in progress_messages[0]


class TestNavigate:
    def test_logs_navigation_before_opening_page(self) -> None:
        page = Mock()
        events = Mock()

        with patch.object(extract.logger, "debug") as debug_log:
            events.attach_mock(debug_log, "debug")
            events.attach_mock(page.goto, "goto")
            assert extract._navigate(page, "https://example.com/category")

        assert events.mock_calls == [
            call.debug(
                "Navigating to %s (attempt %d/%d).",
                "https://example.com/category",
                1,
                3,
            ),
            call.goto(
                "https://example.com/category",
                wait_until="domcontentloaded",
                timeout=60000,
            ),
        ]


class TestCrawlCategoryProductUrls:
    def test_continues_scrolling_past_twenty_iterations(self) -> None:
        page = Mock()
        late_product_link = (
            "https://groceries.morrisons.com/products/example/123"
        )
        page.evaluate.side_effect = [
            value
            for height in range(1, 26)
            for value in (None, height)
        ] + [None, 25, None, 25]
        page.locator.return_value.evaluate_all.side_effect = (
            [[] for _ in range(24)]
            + [[late_product_link], [], []]
        )

        product_urls = extract._crawl_category_product_urls(page)

        assert product_urls == {late_product_link}

    def test_keeps_product_links_that_disappear_after_scrolling(self) -> None:
        page = Mock()
        product_link = (
            "https://groceries.morrisons.com/products/example/123?source=category"
        )
        page.evaluate.side_effect = [None, 100, None, 100, None, 100]
        page.locator.return_value.evaluate_all.side_effect = [
            [product_link],
            [],
            [],
        ]

        product_urls = extract._crawl_category_product_urls(page)

        assert product_urls == {
            "https://groceries.morrisons.com/products/example/123"
        }
