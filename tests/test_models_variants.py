import pytest
from pydantic import ValidationError

from service.models import FormatSpec


def test_format_spec_accepts_distinct_variants():
    spec = FormatSpec(ratio="9:16", min=8, max=12, variants=["16:9", "1:1"])
    assert spec.variants == ["16:9", "1:1"]


@pytest.mark.parametrize(
    "variants",
    [["16:9", "16:9"], ["9:16"]],
)
def test_format_spec_rejects_duplicate_or_primary_variant(variants):
    with pytest.raises(ValidationError):
        FormatSpec(ratio="9:16", min=8, max=12, variants=variants)
