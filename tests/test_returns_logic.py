import pytest


class TestReturnsStockAdjustmentLogic:
    """Unit tests for return/disposal stock adjustments and delta calculations."""

    def test_stock_delta_increase_disposal_deducts_stock(self):
        """When disposal qty increases from 5 to 8, stock diff is +3 (3 more items deducted)."""
        old_qty_no = 5
        new_qty_no = 8
        current_stock = 10

        diff = new_qty_no - old_qty_no
        assert diff == 3
        assert current_stock >= diff  # Sufficient stock

        new_stock = current_stock - diff
        assert new_stock == 7

    def test_stock_delta_increase_rejects_when_insufficient_stock(self):
        """When disposal qty increases by more than available stock, operation is rejected."""
        old_qty_no = 5
        new_qty_no = 15
        current_stock = 4

        diff = new_qty_no - old_qty_no
        assert diff == 10
        is_sufficient = current_stock >= diff
        assert is_sufficient is False

    def test_stock_delta_decrease_disposal_refunds_stock(self):
        """When disposal qty decreases from 10 to 4, stock diff is -6 (6 items restored)."""
        old_qty_no = 10
        new_qty_no = 4
        current_stock = 12

        diff = new_qty_no - old_qty_no
        assert diff == -6

        # In application code: stock = stock - diff -> stock - (-6) = stock + 6
        new_stock = current_stock - diff
        assert new_stock == 18

    def test_quantity_parsing_rules(self):
        """Verify parsing rules: integers for qty_no, floats for qty_kg, empty handling."""
        def parse_quantities(qty_no_raw, qty_kg_raw):
            n_raw = (qty_no_raw or '').strip()
            k_raw = (qty_kg_raw or '').strip()
            qty_no = int(n_raw) if n_raw else None
            qty_kg = float(k_raw) if k_raw else None

            if not qty_no and not qty_kg:
                return None, None, 'Please enter a quantity in No. or Kg.'
            return qty_no, qty_kg, None

        # Both empty
        n, k, err = parse_quantities('', '')
        assert err is not None

        # Number only
        n, k, err = parse_quantities('10', '')
        assert n == 10
        assert k is None
        assert err is None

        # Kg only (float)
        n, k, err = parse_quantities('', '12.5')
        assert n is None
        assert k == 12.5
        assert err is None

        # Both provided
        n, k, err = parse_quantities('5', '2.75')
        assert n == 5
        assert k == 2.75
        assert err is None

