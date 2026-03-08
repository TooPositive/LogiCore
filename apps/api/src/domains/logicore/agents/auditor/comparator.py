"""Auditor Agent -- compares contract rates against invoice billing.

Pure function: takes Invoice + ContractRate list, returns Discrepancy list.
No LLM needed for basic comparison -- deterministic math.
Idempotent: same inputs always produce same outputs.
"""

from decimal import Decimal

from apps.api.src.domains.logicore.models.audit import (
    ContractRate,
    Discrepancy,
    Invoice,
    classify_discrepancy_band,
)


class AuditorAgent:
    """Compares invoice line items against contract rates.

    Matches by cargo_type. Classifies discrepancies into 4 bands.
    """

    async def compare(
        self, invoice: Invoice, rates: list[ContractRate]
    ) -> list[Discrepancy]:
        """Compare invoice line items against contract rates.

        Returns a list of discrepancies (empty if all rates match).
        Line items without matching contract rates are skipped.
        """
        # Build rate lookup by cargo_type
        rate_map: dict[str | None, ContractRate] = {
            r.cargo_type: r for r in rates
        }

        discrepancies: list[Discrepancy] = []

        for idx, item in enumerate(invoice.line_items):
            contract_rate = rate_map.get(item.cargo_type)
            if contract_rate is None:
                continue

            if contract_rate.rate == Decimal("0"):
                continue

            # Calculate discrepancy
            expected_total = contract_rate.rate * item.quantity
            actual_total = item.total
            difference = actual_total - expected_total

            percentage = (
                (item.unit_price - contract_rate.rate) / contract_rate.rate
            ) * Decimal("100")

            band = classify_discrepancy_band(percentage)

            # Only report if there is an actual difference
            if difference == Decimal("0"):
                continue

            discrepancies.append(
                Discrepancy(
                    line_item_index=idx,
                    description=item.description,
                    expected_rate=contract_rate.rate,
                    actual_rate=item.unit_price,
                    expected_total=expected_total,
                    actual_total=actual_total,
                    difference=abs(difference),
                    percentage=percentage,
                    band=band,
                    currency=invoice.currency,
                )
            )

        return discrepancies
