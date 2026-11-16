from django.shortcuts import render


def _page(request, template, status):
    return render(request, template, status=status)


def permission_denied(request, exception=None):
    return _page(request, "403.html", 403)


def not_found(request, exception=None):
    return _page(request, "404.html", 404)


def server_error(request):
    # Standalone template: must not depend on context processors or the database.
    from django.http import HttpResponseServerError
    from django.template import loader
    return HttpResponseServerError(loader.get_template("500.html").render({}))
