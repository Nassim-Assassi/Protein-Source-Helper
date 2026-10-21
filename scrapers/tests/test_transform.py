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
