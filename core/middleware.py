"""Middleware applied to every response."""


class TDMReservationMiddleware:
    """Reserve text and data mining rights on every response (W3C TDMRep, HTTP header).

    The site refuses the use of its pages to train models (cahier des charges, section 5).
    The same reservation is published in /.well-known/tdmrep.json, in robots.txt and in a
    meta tag of each page.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        response.headers.setdefault("tdm-reservation", "1")
        return response
