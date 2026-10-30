import pytest


class TestDepartmentStockLedgerCalculations:
    """Tests for department stock ledger running balance calculations and chronological sorting."""

    def test_running_balance_calculation_mixed_transactions(self):
        """Verify cumulative balance calculation across receipts, issues, and returns."""
        transactions = [
            {'txn_date': '2026-08-01', 'type': 'Stock Added', 'in_qty': 100, 'out_qty': 0},
            {'txn_date': '2026-08-03', 'type': 'PPE Issued', 'in_qty': 0, 'out_qty': 20},
            {'txn_date': '2026-08-05', 'type': 'PPE Issued', 'in_qty': 0, 'out_qty': 30},
            {'txn_date': '2026-08-10', 'type': 'Stock Added', 'in_qty': 50, 'out_qty': 0},
            {'txn_date': '2026-08-12', 'type': 'Contractor Issued', 'in_qty': 0, 'out_qty': 15},
            {'txn_date': '2026-08-15', 'type': 'Returned', 'in_qty': 5, 'out_qty': 0},
        ]

        # Chronological forward calculation
        running_balance = 0
        total_in = 0
        total_out = 0

        for row in transactions:
            in_q = int(row.get('in_qty') or 0)
            out_q = int(row.get('out_qty') or 0)
            total_in += in_q
            total_out += out_q
            running_balance += (in_q - out_q)
            row['balance'] = running_balance

        assert total_in == 155
        assert total_out == 65
        assert running_balance == 90

        # Verify running balance at each point in time
        assert transactions[0]['balance'] == 100
        assert transactions[1]['balance'] == 80
        assert transactions[2]['balance'] == 50
        assert transactions[3]['balance'] == 100
        assert transactions[4]['balance'] == 85
        assert transactions[5]['balance'] == 90

    def test_reverse_display_preserves_historical_balance(self):
        """When transactions are reversed for display (latest on top), running balance must remain historical."""
        transactions = [
            {'txn_date': '2026-08-01', 'type': 'Stock Added', 'in_qty': 50, 'out_qty': 0},
            {'txn_date': '2026-08-02', 'type': 'PPE Issued', 'in_qty': 0, 'out_qty': 10},
        ]

        running_balance = 0
        for row in transactions:
            in_q = int(row.get('in_qty') or 0)
            out_q = int(row.get('out_qty') or 0)
            running_balance += (in_q - out_q)
            row['balance'] = running_balance

        display_history = list(reversed(transactions))

        # Top row is newest (2026-08-02), but its balance reflects 40
        assert display_history[0]['txn_date'] == '2026-08-02'
        assert display_history[0]['balance'] == 40

        # Bottom row is oldest (2026-08-01), with initial balance 50
        assert display_history[1]['txn_date'] == '2026-08-01'
        assert display_history[1]['balance'] == 50

    def test_chronological_sort_with_receipts_before_issues_on_same_date(self):
        """When receipt and issue occur on the same date, receipts sort first so balance doesn't falsely dip negative."""
        unsorted_txns = [
            {'txn_date': '2026-08-05', 'type': 'PPE Issued', 'in_qty': 0, 'out_qty': 10},
            {'txn_date': '2026-08-05', 'type': 'Stock Added', 'in_qty': 20, 'out_qty': 0},
        ]

        # Sorting rule: date first, then Stock Added (0) before Issued (1)
        sorted_txns = sorted(
            unsorted_txns,
            key=lambda x: (str(x.get('txn_date') or ''), 0 if x.get('type') == 'Stock Added' else 1)
        )

        assert sorted_txns[0]['type'] == 'Stock Added'
        assert sorted_txns[1]['type'] == 'PPE Issued'

        bal = 0
        for r in sorted_txns:
            bal += r['in_qty'] - r['out_qty']
            r['balance'] = bal

        assert sorted_txns[0]['balance'] == 20
        assert sorted_txns[1]['balance'] == 10

