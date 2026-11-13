"""Shared result contracts for ETL stages."""

from collections.abc import Mapping
from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Products extracted and counts for discovered and failed product URLs."""

    products: list[Mapping[str, object]]
    discovered_count: int
    failed_count: int


@dataclass(frozen=True, slots=True)
class TransformResult:
    """Normalized products and the number of skipped input rows."""

    products: pd.DataFrame
    skipped_count: int


@dataclass(frozen=True, slots=True)
class LoadResult:
    """Summarize data added during a scrape load."""

    loaded_count: int
    new_brand_count: int
    new_product_count: int
    new_retailer_category_count: int


@dataclass(slots=True)
class ScrapeRunMetrics:
    """Counts and durations collected while processing one scrape run."""

    discovered_count: int | None = None
    extracted_count: int | None = None
    extraction_failed_count: int | None = None
    transformed_count: int | None = None
    transformation_skipped_count: int | None = None
    loaded_count: int | None = None
    extraction_duration_seconds: float | None = None
    transformation_duration_seconds: float | None = None
    load_duration_seconds: float | None = None
