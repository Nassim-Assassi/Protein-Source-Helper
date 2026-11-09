from bs4 import BeautifulSoup

from scrapers.morrisons_scraper.extract import _nutrition_table


class TestNutritionTable:
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
