from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RetailerConfig:
    """Identify a retailer using its stable display name and website URL."""

    name: str
    url: str
