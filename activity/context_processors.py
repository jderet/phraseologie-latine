from .services import unread_count


def notifications(request):
    """The number of unread notifications, for the bell in the header."""
    user = getattr(request, "user", None)
    if user is None or not user.is_authenticated:
        return {}
    return {"unread_notifications": unread_count(user)}
