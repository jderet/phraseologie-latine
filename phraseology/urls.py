from django.urls import path

from . import views

app_name = "phraseology"

urlpatterns = [
    path("recherche/schema/", views.schema_search, name="schema_search"),
    path("recherche/schema/lemmes/", views.schema_help_lemmas, name="schema_lemmas"),
    path("recherche/schema/verifier/", views.schema_help_check, name="schema_check"),
    path("lecture/mots/<int:pk>/", views.reading_word, name="reading_word"),
    path("lecture/annoter/", views.annotate_selection, name="annotate_selection"),
    path("lecture/annoter/rattacher/", views.annotate_attach, name="annotate_attach"),
    path("lecture/reperages/nouveau/", views.sighting_create, name="sighting_create"),
    path("lecture/notes/nouvelle/", views.reading_note_create, name="reading_note_create"),
    path("reperages/", views.sighting_list, name="sightings"),
    path("relecture/passages/", views.review_queue, name="review_queue"),
    path("relecture/", views.reviewer_page, name="reviewer"),
    path("mes-annotations/", views.annotator_page, name="annotator"),
    path("chiffres/", views.figures_page, name="figures"),
    path("passages/<int:pk>/relu/", views.passage_review, name="passage_review"),
    path("reperages/<int:pk>/classer/", views.sighting_dismiss, name="sighting_dismiss"),
    path("lecture/suggestions/", views.suggestion_panel, name="suggestion_panel"),
    path("lecture/suggestions/confirmer/", views.suggestion_confirm, name="suggestion_confirm"),
    path("profils/", views.collocation_profile, name="collocation_profile"),
    path("profils/<str:lemma>/", views.collocation_profile, name="collocation_lemma"),
    path("fiches/", views.unit_list, name="unit_list"),
    path("fiches/nouvelle/", views.unit_create, name="unit_create"),
    path("fiches/<int:pk>/", views.unit_detail, name="unit"),
    path("fiches/<int:pk>/modifier/", views.unit_edit, name="unit_edit"),
    path("fiches/<int:pk>/frequence/", views.unit_frequency, name="unit_frequency"),
    path("fiches/<int:pk>/proposer/", views.unit_propose, name="unit_propose"),
    path("fiches/<int:pk>/valider/", views.unit_validate, name="unit_validate"),
    path("fiches/<int:pk>/contester/", views.unit_contest, name="unit_contest"),
    path("fiches/<int:pk>/lever/", views.unit_resolve, name="unit_resolve"),
    path("fiches/<int:pk>/attestations/", views.attestation_add, name="attestation_add"),
    path("fiches/<int:pk>/releve/", views.unit_survey, name="unit_survey"),
    path("fiches/<int:pk>/releve/lancer/", views.unit_survey_run, name="unit_survey_run"),
    path("fiches/<int:pk>/releve/examen/", views.unit_survey_review, name="unit_survey_review"),
    path("fiches/<int:pk>/ajouter/<slug:kind>/", views.part_create, name="part_create"),
    path("fiches/elements/<slug:kind>/<int:pk>/", views.part_edit, name="part_edit"),
    path(
        "fiches/elements/<slug:kind>/<int:pk>/retirer/",
        views.part_withdraw,
        name="part_withdraw",
    ),
    path(
        "attestations/<int:pk>/retirer/",
        views.attestation_withdraw,
        name="attestation_withdraw",
    ),
    path("attestations/<int:pk>/", views.attestation_detail, name="attestation"),
    path("attestations/<int:pk>/doute/", views.attestation_doubt, name="attestation_doubt"),
    path(
        "attestations/<int:pk>/doutes/trancher/",
        views.attestation_doubts_decide,
        name="attestation_doubts_decide",
    ),
    path("attestations/<int:pk>/contester/", views.attestation_contest, name="attestation_contest"),
    path(
        "attestations/<int:pk>/contestation/lever/",
        views.attestation_contest_resolve,
        name="attestation_contest_resolve",
    ),
    path("attestations/<int:pk>/examen/", views.attestation_review, name="attestation_review"),
    path("attestations/<int:pk>/exemple/", views.attestation_example, name="attestation_example"),
    path("neologismes/", views.neologism_list, name="neologism_list"),
    path("neologismes/nouveau/", views.neologism_create, name="neologism_create"),
    path("neologismes/<int:pk>/", views.neologism_detail, name="neologism"),
    path("neologismes/<int:pk>/modifier/", views.neologism_edit, name="neologism_edit"),
    path("neologismes/<int:pk>/valider/", views.neologism_validate, name="neologism_validate"),
    path(
        "neologismes/<int:pk>/equivalents/",
        views.neologism_equivalent_add,
        name="neologism_equivalent_add",
    ),
    path(
        "neologismes/equivalents/<int:pk>/retirer/",
        views.neologism_equivalent_withdraw,
        name="neologism_equivalent_withdraw",
    ),
    path(
        "neologismes/<int:pk>/preuves/", views.neologism_evidence_add, name="neologism_evidence_add"
    ),
    path(
        "neologismes/preuves/<int:pk>/retirer/",
        views.neologism_evidence_withdraw,
        name="neologism_evidence_withdraw",
    ),
    path("recherches-infructueuses/", views.negative_search_list, name="negative_search_list"),
    path(
        "recherches-infructueuses/nouvelle/",
        views.negative_search_create,
        name="negative_search_create",
    ),
    path(
        "recherches-infructueuses/<int:pk>/", views.negative_search_detail, name="negative_search"
    ),
    path("candidats/", views.candidate_list, name="candidate_list"),
    path("candidats/<int:pk>/", views.candidate_detail, name="candidate"),
    path("candidats/<int:pk>/rejeter/", views.candidate_reject, name="candidate_reject"),
    path("candidats/<int:pk>/rouvrir/", views.candidate_reopen, name="candidate_reopen"),
    path("candidats/<int:pk>/rattacher/", views.candidate_attach, name="candidate_attach"),
    path(
        "versions/<int:version_pk>/phrases/<int:segment_pk>/unites/",
        views.units_in_sentence,
        name="units_in_sentence",
    ),
]
