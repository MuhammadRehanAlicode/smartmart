from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.finance.models import Expense
from apps.inventory.models import StockMovement
from apps.inventory.services import change_stock
from apps.products.models import Product
from apps.reports.csv_utils import csv_safe
from apps.reports.services import REPORTS, best_sellers, daily_series, parse_range, sales_report
from apps.sales.services import create_return, create_sale

PW = "S3cure-pass-987"


class ReportBase(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user("owner", password=PW, role="owner")
        self.staff = User.objects.create_user("cash", password=PW, role="staff")
        self.rice = Product.objects.create(name="Rice", sku="R", selling_price=Decimal("100.00"), cost_price=Decimal("60.00"))
        self.tea = Product.objects.create(name="Tea", sku="T", selling_price=Decimal("50.00"), cost_price=Decimal("30.00"))
        self.slow = Product.objects.create(name="Slowpoke", sku="SL", selling_price=Decimal("10.00"), cost_price=Decimal("5.00"))
        for p, n in ((self.rice, 20), (self.tea, 20), (self.slow, 4)):
            change_stock(p, n, StockMovement.Type.OPENING)
        self.today = timezone.localdate()

    def sell(self, items):
        return create_sale(user=self.owner, items=items, payment_method="cash")


class ServiceTests(ReportBase):
    def test_daily_series_fills_missing_days_and_sums(self):
        self.sell([(self.rice.pk, 3)])
        rows = daily_series(self.today - timedelta(days=2), self.today)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["revenue"], Decimal("0.00"))
        last = rows[-1]
        self.assertEqual((last["count"], last["revenue"], last["cogs"], last["gross"]), (1, Decimal("300.00"), Decimal("180.00"), Decimal("120.00")))

    def test_daily_series_matches_summary_with_return(self):
        s = self.sell([(self.rice.pk, 3)])
        create_return(sale_id=s.pk, user=self.owner, quantities={s.items.get().pk: 1}, reason="x")
        row = daily_series(self.today, self.today)[0]
        self.assertEqual((row["net"], row["cogs"], row["gross"]), (Decimal("200.00"), Decimal("120.00"), Decimal("80.00")))

    def test_monthly_grouping(self):
        self.sell([(self.rice.pk, 1)]); self.sell([(self.tea.pk, 2)])
        report = sales_report(self.today.replace(day=1), self.today, {"group": "month"})
        rows = report.sections[0].rows
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1:3], [2, Decimal("200.00")])

    def test_best_sellers_net_of_returns_and_slow_movers(self):
        s = self.sell([(self.rice.pk, 5), (self.tea.pk, 4)])
        create_return(sale_id=s.pk, user=self.owner, quantities={i.pk: 3 for i in s.items.all() if i.product_id == self.tea.pk}, reason="x")
        best = best_sellers(self.today, self.today)
        self.assertEqual([(b["product_name"], b["units"]) for b in best], [("Rice", 5), ("Tea", 1)])
        _, func, _ = REPORTS["products"]
        slow = func(self.today, self.today, {}).sections[1].rows
        self.assertEqual(slow[0][0], "Slowpoke")
        self.assertEqual(slow[0][3], 0)

    def test_stock_valuation_total(self):
        _, func, _ = REPORTS["stock-valuation"]
        rpt = func(self.today, self.today, {})
        self.assertEqual(rpt.sections[0].total[4], Decimal("20") * 60 + Decimal("20") * 30 + Decimal("4") * 5)

    def test_parse_range_validation(self):
        today = self.today
        self.assertIsNone(parse_range({"date_from": "2026-01-01", "date_to": "2026-01-31"})[2])
        self.assertIsNotNone(parse_range({"date_from": "nonsense"})[2])
        self.assertIsNotNone(parse_range({"date_from": "2026-02-01", "date_to": "2026-01-01"})[2])
        self.assertIsNotNone(parse_range({"date_from": "2020-01-01", "date_to": "2026-01-01"})[2])
        s, e, err = parse_range({})
        self.assertEqual((e, (e - s).days, err), (today, 29, None))

    def test_csv_safe(self):
        self.assertEqual(csv_safe("=HYPERLINK(1)"), "'=HYPERLINK(1)")
        self.assertEqual(csv_safe("@x"), "'@x")
        self.assertEqual(csv_safe(Decimal("-5")), "-5.00")
        self.assertEqual(csv_safe(None), "")
        self.assertEqual(csv_safe("Rice"), "Rice")


class ViewTests(ReportBase):
    def test_owner_dashboard_shows_real_figures(self):
        self.sell([(self.rice.pk, 3)])
        Expense.objects.create(date=self.today, description="Power", amount=Decimal("20.00"))
        self.client.force_login(self.owner)
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "300.00")                    # today's sales
        self.assertContains(r, "Net profit")
        self.assertEqual(r.context["today"].net_profit, Decimal("100.00"))   # 300 - 180 - 20

    def test_staff_dashboard_hides_financials(self):
        self.sell([(self.rice.pk, 3)])
        self.client.force_login(self.staff)
        r = self.client.get(reverse("dashboard:home"))
        self.assertEqual(r.status_code, 200)
        for hidden in ("Net profit", "Gross profit", "Inventory value", "Purchase expenditure"):
            self.assertNotContains(r, hidden)
        self.assertContains(r, "Recent in-store sales")

    def test_empty_dashboard_renders(self):
        self.client.force_login(self.owner)
        self.assertContains(self.client.get(reverse("dashboard:home") + "?days=7"), "No sales in this period yet.")

    def test_reports_owner_only(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse("reports:index")).status_code, 403)
        self.assertEqual(self.client.get(reverse("reports:report", args=["profit"])).status_code, 403)

    def test_all_reports_render_and_export_csv(self):
        s = self.sell([(self.rice.pk, 2)])
        create_return(sale_id=s.pk, user=self.owner, quantities={s.items.get().pk: 1}, reason="=cmd|' /C calc'!A0")
        Expense.objects.create(date=self.today, description="Rent", amount=Decimal("10.00"))
        self.client.force_login(self.owner)
        for slug in REPORTS:
            url = reverse("reports:report", args=[slug])
            self.assertEqual(self.client.get(url).status_code, 200, slug)
            r = self.client.get(url, {"format": "csv"})
            self.assertEqual(r.status_code, 200, slug)
            self.assertTrue(r["Content-Type"].startswith("text/csv"))
            self.assertIn("attachment", r["Content-Disposition"])
        body = self.client.get(reverse("reports:report", args=["returns"]), {"format": "csv"}).content.decode()
        self.assertIn("'=cmd", body)                       # formula injection neutralised
        self.assertNotIn(",=cmd", body)

    def test_unknown_report_404(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.get(reverse("reports:report", args=["nope"])).status_code, 404)

    def test_profit_report_figures(self):
        self.sell([(self.rice.pk, 3)])
        self.client.force_login(self.owner)
        r = self.client.get(reverse("reports:report", args=["profit"]))
        self.assertContains(r, "180.00")
        self.assertContains(r, "120.00")

    def test_bad_dates_fall_back_with_message(self):
        self.client.force_login(self.owner)
        r = self.client.get(reverse("reports:report", args=["sales"]), {"date_from": "garbage"})
        self.assertContains(r, "last 30 days")
