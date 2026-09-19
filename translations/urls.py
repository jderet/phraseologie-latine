from django.urls import path

from . import collab_views, editor_views, views, workshop_views

app_name = "translations"

urlpatterns = [
    path("textes/", views.source_list, name="source_list"),
    path("textes/ajouter/", views.source_create, name="source_create"),
    path("textes/<int:pk>/", views.source_detail, name="source"),
    path("textes/<int:pk>/modifier/", views.source_edit, name="source_edit"),
    path("textes/<int:pk>/phrases/", views.source_sentences, name="source_sentences"),
    path(
        "textes/<int:pk>/phrases/ajouter/",
        views.source_sentence_insert,
        name="source_sentence_insert",
    ),
    path(
        "textes/<int:pk>/phrases/<int:number>/modifier/",
        views.source_sentence_edit,
        name="source_sentence_edit",
    ),
    path(
        "textes/<int:pk>/phrases/<int:number>/scinder/",
        views.source_sentence_split,
        name="source_sentence_split",
    ),
    path(
        "textes/<int:pk>/phrases/<int:number>/fusionner/",
        views.source_sentence_merge,
        name="source_sentence_merge",
    ),
    path("textes/<int:pk>/propositions/", views.source_proposal_list, name="source_proposal_list"),
    path("propositions-texte/<int:pk>/", views.source_proposal_detail, name="source_proposal"),
    path(
        "propositions-texte/<int:pk>/envoyer/",
        views.source_proposal_send,
        name="source_proposal_send",
    ),
    path(
        "propositions-texte/<int:pk>/<slug:action>/",
        views.source_proposal_act,
        name="source_proposal_act",
    ),
    path("textes/<int:source_pk>/nouveau-projet/", views.project_create, name="project_create"),
    path("projets/", views.project_list, name="project_list"),
    path("projets/<int:pk>/", views.project_detail, name="project"),
    path("projets/<int:pk>/modifier/", views.project_edit, name="project_edit"),
    path("projets/<int:pk>/comparer/", views.project_compare, name="project_compare"),
    path(
        "projets/<int:pk>/propositions/",
        workshop_views.project_proposals,
        name="project_proposals",
    ),
    path("projets/<int:pk>/activite/", workshop_views.project_activity, name="project_activity"),
    path("projets/<int:pk>/sujets/", workshop_views.topic_list, name="topic_list"),
    path("projets/<int:pk>/sujets/nouveau/", workshop_views.topic_create, name="topic_create"),
    path("projets/<int:pk>/sujets/<int:number>/", workshop_views.topic_detail, name="topic"),
    path(
        "projets/<int:pk>/sujets/<int:number>/modifier/",
        workshop_views.topic_edit,
        name="topic_edit",
    ),
    path(
        "projets/<int:pk>/sujets/<int:number>/etat/",
        workshop_views.topic_status,
        name="topic_status",
    ),
    path("projets/<int:pk>/glossaire/", workshop_views.glossary, name="glossary"),
    path(
        "projets/<int:pk>/glossaire/<int:entry_pk>/modifier/",
        workshop_views.glossary_edit,
        name="glossary_edit",
    ),
    path(
        "projets/<int:pk>/glossaire/<int:entry_pk>/decider/",
        workshop_views.glossary_decide,
        name="glossary_decide",
    ),
    path("traduction/concordance/", workshop_views.concordance, name="concordance"),
    path("traduction/aide/", workshop_views.help_page, name="help"),
    path("traduction/premiers-pas/", workshop_views.hide_first_steps, name="hide_first_steps"),
    path("projets/<int:pk>/reference/", views.project_reference, name="project_reference"),
    path(
        "projets/<int:project_pk>/nouvelle-version/",
        views.version_create,
        name="version_create",
    ),
    path("versions/<int:pk>/", views.version_detail, name="version"),
    path("versions/<int:pk>/traduire/", views.version_edit, name="version_edit"),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/",
        views.translation_save,
        name="translation_save",
    ),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/statut/",
        editor_views.sentence_status,
        name="sentence_status",
    ),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/memoire/",
        editor_views.memory_panel,
        name="editor_memory",
    ),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/glossaire/",
        editor_views.glossary_panel,
        name="editor_glossary",
    ),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/commentaires/",
        editor_views.comments_panel,
        name="editor_comments",
    ),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/commenter/",
        editor_views.comment_post,
        name="comment_post",
    ),
    path("commentaires/<int:pk>/resoudre/", editor_views.comment_resolve, name="comment_resolve"),
    path("versions/<int:pk>/commentaires/", editor_views.version_comments, name="version_comments"),
    path(
        "versions/<int:pk>/commentaires/nouveau/",
        editor_views.comment_post_by_number,
        name="comment_post_by_number",
    ),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/historique/",
        editor_views.history_panel,
        name="editor_history",
    ),
    path(
        "versions/<int:pk>/phrases/<int:segment_pk>/retablir/",
        editor_views.sentence_restore,
        name="sentence_restore",
    ),
    path("versions/<int:pk>/controle/", editor_views.quality_report, name="quality_report"),
    path("versions/<int:pk>/statistiques/", editor_views.version_stats_page, name="version_stats"),
    path("versions/<int:pk>/remplacer/", editor_views.find_replace, name="find_replace"),
    path(
        "versions/<int:pk>/controle/tout-montrer/",
        editor_views.quality_reset,
        name="quality_reset",
    ),
    path("versions/<int:pk>/mise-a-jour/", collab_views.sync_copy, name="sync_copy"),
    path("versions/<int:pk>/etapes/", views.step_list, name="step_list"),
    path("versions/<int:pk>/etapes/nouvelle/", views.step_create, name="step_create"),
    path("versions/<int:pk>/etapes/comparer/", views.step_compare, name="step_compare"),
    path("versions/<int:pk>/etapes/<int:number>/", views.step_detail, name="step"),
    path("versions/<int:pk>/etapes/<int:number>/copier/", views.version_copy, name="version_copy"),
    path("versions/<int:pk>/proposer/", views.proposal_create, name="proposal_create"),
    path("versions/<int:pk>/propositions/", views.proposal_list, name="proposal_list"),
    path("propositions/<int:pk>/", views.proposal_detail, name="proposal"),
    path("propositions/<int:pk>/retirer/", views.proposal_withdraw, name="proposal_withdraw"),
    path(
        "propositions/phrases/<int:pk>/decider/",
        views.proposed_sentence_decide,
        name="proposed_sentence_decide",
    ),
    path("versions/<int:pk>/style/", views.version_settings, name="version_settings"),
    path("versions/<int:pk>/co-auteurs/", workshop_views.version_members, name="version_members"),
    path("co-auteurs/<int:pk>/repondre/", workshop_views.member_answer, name="member_answer"),
    path("co-auteurs/<int:pk>/retirer/", workshop_views.member_remove, name="member_remove"),
    path("versions/<int:pk>/publier/", views.version_publish, name="version_publish"),
    path(
        "versions/<int:pk>/export/bilingue.txt",
        views.version_export_text,
        name="version_export_text",
    ),
    path(
        "versions/<int:pk>/export/version.tei.xml",
        views.version_export_tei,
        name="version_export_tei",
    ),
    path(
        "versions/<int:pk>/export/version.tmx", views.version_export_tmx, name="version_export_tmx"
    ),
    path(
        "versions/<int:pk>/export/imprimer/",
        views.version_export_print,
        name="version_export_print",
    ),
]
