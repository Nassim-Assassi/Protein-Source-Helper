from decimal import Decimal

import pytest

from scrapers.constants import PRODUCT_COLUMNS
from scrapers.morrisons_scraper.transform import transform_products


class TestTransformProducts:
    @staticmethod
    def raw_product(**product_overrides: object) -> dict[str, object]:
        product = {
            "name": "Morrisons British Chicken Breast Fillets 400g",
            "sku": "113028499",
            "size": "400g",
            "brand": "Morrisons",
            "offers": {"price": "4.30", "availability": "InStock"},
            "nutrition": {
                    "calories": "136 kcal",
                    "proteinContent": "30.4 g",
                "carbohydrateContent": "0.1 g",
                "sugarContent": "0.1 g",
                "fatContent": "1.4 g",
                "saturatedFatContent": "0.5 g",
                "fiberContent": "0.5 g",
                "saltContent": "0.1 g",
                "servingSize": "100g",
            },
            "image": "https://example.com/product.jpg",
            **product_overrides,
        }
        return {
            "product": product,
            "source_url": "https://example.com/product/113028499",
            "category_name": "Meat & Fish",
            "nutrition_table": {},
        }

    def test_maps_product_to_loader_columns(self) -> None:
        frame = transform_products([self.raw_product()])

        assert tuple(frame.columns) == PRODUCT_COLUMNS
        product = frame.iloc[0]
        assert product["listing_name"] == "Morrisons British Chicken Breast Fillets 400g"
        assert product["price"] == Decimal("4.30")
        assert product["package_quantity"] == Decimal("400")
        assert product["package_unit"] == "g"
        assert product["energy_kcal"] == Decimal("136")
        assert product["protein_g"] == Decimal("30.4")
        assert product["nutrition_basis"] == "per_100g"
        assert product["external_id"] == "113028499"
        assert product["category_name"] == "Meat & Fish"
        assert product["barcode_gtin"] is None

    def test_prefers_nutrition_table_values(self) -> None:
        raw = self.raw_product()
        raw["nutrition_table"] = {
            "protein_g": "31.2 g", "energy_kcal": "140 kcal"}

        product = transform_products([raw]).iloc[0]

        assert product["protein_g"] == Decimal("31.2")
        assert product["energy_kcal"] == Decimal("140")

    def test_converts_energy_units_to_kcal(self) -> None:
        mj_product = self.raw_product(nutrition={
            "calories": "1.68 MJ",
            "proteinContent": "30.4 g",
            "servingSize": "100g",
        })
        paired_product = self.raw_product(nutrition={
            "calories": "1.68 MJ / 401 kcal",
            "proteinContent": "30.4 g",
            "servingSize": "100g",
        })

        mj_energy, paired_energy = transform_products(
            [mj_product, paired_product]
        )["energy_kcal"].tolist()

        assert mj_energy == Decimal("1680") / Decimal("4.184")
        assert paired_energy == Decimal("401")

    def test_treats_less_than_nutrition_values_as_zero(self) -> None:
        raw = self.raw_product(nutrition={
            "calories": "<0.5 kcal",
            "proteinContent": "<0.5 g",
            "carbohydrateContent": "<0.5 g",
            "sugarContent": "<0.5 g",
            "fatContent": "<0.5 g",
            "saturatedFatContent": "<0.5 g",
            "fiberContent": "<0.5 g",
            "sodiumContent": "<0.5 g",
            "servingSize": "100g",
        })
        raw["nutrition_table"] = {"protein_g": "<0.5 g"}

        product = transform_products([raw]).iloc[0]

        for field in (
            "energy_kcal", "protein_g", "carbohydrates_g", "sugars_g",
            "fat_g", "saturates_g", "fibre_g", "salt_g",
        ):
            assert product[field] == Decimal("0")

    def test_normalizes_kilograms_and_litres(self) -> None:
        kilogram_product = self.raw_product(size="1.5kg")
        litre_product = self.raw_product(
            size="1.5l",
            nutrition={
                "calories": "62 kcal",
                "proteinContent": "10 g",
                "servingSize": "100ml",
            },
        )

        kilogram, litre = transform_products(
            [kilogram_product, litre_product]
        ).to_dict(orient="records")

        assert kilogram["package_quantity"] == Decimal("1500.0")
        assert kilogram["package_unit"] == "g"
        assert litre["package_quantity"] == Decimal("1500.0")
        assert litre["package_unit"] == "ml"

    def test_calculates_count_pack_mass_from_serving_weight(self) -> None:
        count_pack = self.raw_product(
            size="6 per pack",
            nutrition={
                "calories": "300 kcal",
                "proteinContent": "7.7 g",
                "servingSize": "100g",
            },
        )
        count_pack["nutrition_table"] = {"serving_size_g": "50"}

        product = transform_products([count_pack]).iloc[0]

        assert product["package_quantity"] == Decimal("300")
        assert product["package_unit"] == "g"
        assert product["nutrition_basis"] == "per_100g"

    def test_calculates_package_mass_from_serving_count(self) -> None:
        cake = self.raw_product(
            name="Mr Kipling Standard Battenberg Cake Family Size Serves 8",
            size=None,
            description="With 8 servings per Battenberg",
            nutrition={
                "calories": "382 kcal",
                "proteinContent": "4.8 g",
                "servingSize": "100g",
            },
        )
        cake["nutrition_table"] = {"serving_size_g": "32"}

        product = transform_products([cake]).iloc[0]

        assert product["package_quantity"] == Decimal("256")
        assert product["package_unit"] == "g"
        assert product["nutrition_basis"] == "per_100g"

    def test_extracts_count_and_uses_matching_item_nutrition_basis(self) -> None:
        bagels = self.raw_product(
            name="Warburtons 6 Sesame Thin Bagels",
            size=None,
            nutrition={
                "calories": "136 kcal",
                "proteinContent": "5.3 g",
                "servingSize": "100g",
            },
        )
        bagels["listing_name"] = bagels["product"]["name"]
        bagels["nutrition_table"] = {
            "energy_kcal": "136",
            "protein_g": "5.3g",
            "serving_size_g": "50",
            "serving_unit": "bagel",
        }
        bagels["nutrition_basis"] = "per_item"

        product = transform_products([bagels]).iloc[0]

        assert product["package_quantity"] == Decimal("6")
        assert product["package_unit"] == "each"
        assert product["energy_kcal"] == Decimal("136")
        assert product["nutrition_basis"] == "per_item"

    def test_uses_each_and_per_item_when_serving_weight_is_unknown(self) -> None:
        count_pack = self.raw_product(
            size="6 per pack",
            nutrition={
                "calories": "151 kcal",
                "proteinContent": "3.9 g",
                "servingSize": "per item",
            },
        )

        product = transform_products([count_pack]).iloc[0]

        assert product["package_quantity"] == Decimal("6")
        assert product["package_unit"] == "each"
        assert product["nutrition_basis"] == "per_item"

    def test_skips_invalid_rows_and_keeps_valid_products(self) -> None:
        valid = self.raw_product()
        invalid = self.raw_product()
        invalid["product"]["offers"] = {"availability": "InStock"}

        products = transform_products([valid, invalid])

        assert len(products) == 1
        assert products.iloc[0]["listing_name"] == (
            "Morrisons British Chicken Breast Fillets 400g"
        )

    def test_skips_nutrition_basis_incompatible_with_package_unit(self) -> None:
        valid = self.raw_product()
        incompatible = self.raw_product(size="500ml")

        products = transform_products([valid, incompatible])

        assert len(products) == 1
        assert products.iloc[0]["package_unit"] == "g"

    def test_all_invalid_rows_return_an_empty_loader_frame(self) -> None:
        invalid = self.raw_product()
        invalid["product"]["offers"] = {"availability": "InStock"}

        products = transform_products([invalid])

        assert products.empty
        assert tuple(products.columns) == PRODUCT_COLUMNS
