from datetime import date

from django.contrib import messages
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.views import View
from django.views.generic import CreateView, ListView

from apps.accounts.permissions import OwnerRequiredMixin
from apps.core.audit import log_action

from .forms import ExpenseForm
from .models import Expense


def _parse(value):
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


class ExpenseListView(OwnerRequiredMixin, ListView):
    template_name = "finance/expense_list.html"
    paginate_by = 25
    context_object_name = "expenses"

    def get_queryset(self):
        qs = Expense.objects.all()
        if d := _parse(self.request.GET.get("date_from")):
            qs = qs.filter(date__gte=d)
        if d := _parse(self.request.GET.get("date_to")):
            qs = qs.filter(date__lte=d)
        self.filtered = qs
        return qs

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["filtered_total"] = self.filtered.aggregate(t=Sum("amount"))["t"] or 0
        return ctx


class ExpenseCreateView(OwnerRequiredMixin, CreateView):
    form_class = ExpenseForm
    template_name = "dashboard/generic_form.html"
    success_url = reverse_lazy("expenses:list")
    extra_context = {"title": "Record expense", "back_url": reverse_lazy("expenses:list")}

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        r = super().form_valid(form)
        log_action(self.request.user, "expense.created", self.object.pk, amount=str(self.object.amount))
        messages.success(self.request, "Expense recorded.")
        return r


class ExpenseDeleteView(OwnerRequiredMixin, View):
    def post(self, request, pk):
        e = get_object_or_404(Expense, pk=pk)
        log_action(request.user, "expense.deleted", pk, amount=str(e.amount), description=e.description)
        e.delete()
        messages.success(request, "Expense deleted.")
        return redirect("expenses:list")
