"""What the pages of a project gather across its versions: counts and lists for the tabs."""

from moderation.registry import can_view

from .models import ChangeProposal, TranslationVersion


def visible_proposals(user, project):
    """Change proposals made to the versions of a project that the user may see, open first."""
    queryset = ChangeProposal.objects.filter(
        version__project=project, version__state=TranslationVersion.State.PUBLISHED
    ).select_related("version__author", "version__project", "author")
    proposals = [proposal for proposal in queryset if can_view(user, proposal)]
    proposals.sort(key=lambda proposal: (not proposal.is_open, -proposal.created_at.timestamp()))
    return proposals


def project_counts(user, project):
    """Numbers shown next to the tabs of a project."""
    open_proposals = ChangeProposal.objects.filter(
        version__project=project,
        version__state=TranslationVersion.State.PUBLISHED,
        version__is_hidden=False,
        status=ChangeProposal.Status.OPEN,
        is_hidden=False,
    ).count()
    return {"proposals": open_proposals}
