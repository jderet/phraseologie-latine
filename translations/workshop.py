"""What the pages of a project gather: counts and lists for the tabs."""

from .models import Topic


def project_counts(user, project):
    """Numbers shown next to the tabs of a project."""
    open_topics = project.topics.filter(status=Topic.Status.OPEN, is_hidden=False).count()
    return {"topics": open_topics}
