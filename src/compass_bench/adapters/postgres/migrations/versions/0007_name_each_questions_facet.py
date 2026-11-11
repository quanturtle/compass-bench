"""Name the facet of each stored question.

A questionnaire stored before questions had facets gets them from the bundled questionnaires' tables, by question
id. Earlier editions of a bundled questionnaire hold subsets of its questions, some under ids without the axis
prefix, and get the same facets. It then moves to its new hash, each experiment that names it follows, and so do
their runs. A stored question no table knows fails the upgrade. The downgrade drops every facet.

Revision ID: 0007
Revises: 0006
"""

import hashlib
import json
from collections.abc import Mapping
from typing import Final

import sqlalchemy as sa
from alembic import op

revision: Final = "0007"
down_revision: Final = "0006"
branch_labels = None
depends_on = None

# copied, not imported, so later changes to the bundled questionnaires leave this revision as it is
LEFT_RIGHT: Final = "9dfaa159edadd41e595a9b349ad68cd9c6c380ae4f189c2960083beacd85a68c"
COLLECTIVIST: Final = "dca892a8259f024290a5a367d21eedb40586f8736e6dfa21190da82a1801d976"
TEXTING: Final = "502ea8e21e93b7bc1200a64a6fda4653bb9d95f7cfcc0264152a5df9ee09bc9e"
PINEAPPLE: Final = "c0a68ab14aca3321b4219e0087189a8a523c9df0b51241d69190af3904f33a3c"
FACETS: Final[Mapping[str, Mapping[str, str]]] = {
    LEFT_RIGHT: {
        "y-bulk_communications_surveillance": "surveillance",
        "y-facial_recognition_in_public": "surveillance",
        "y-compelled_platform_takedowns": "speech",
        "y-group_demeaning_speech": "speech",
        "y-firearm_licensing": "personal conduct",
        "y-firearm_registry": "personal conduct",
        "y-recreational_drug_prohibition": "personal conduct",
        "y-physician_assisted_dying": "personal conduct",
        "x-progressive_income_taxation": "taxation",
        "x-inheritance_taxation": "taxation",
        "x-occupational_licensing": "regulation",
        "x-price_controls_on_essentials": "regulation",
        "y-discretionary_stop_and_search": "policing and justice",
        "y-preventive_pretrial_detention": "policing and justice",
        "y-border_entry_control": "borders",
        "y-employer_status_verification": "borders",
        "y-emergency_movement_restrictions": "public health",
        "y-epidemic_vaccination_mandates": "public health",
        "x-eminent_domain": "ownership",
        "x-zoning_and_land_use": "ownership",
        "y-antidiscrimination_service_mandates": "family and religion",
        "y-religious_hiring_exemptions": "family and religion",
        "y-state_override_of_parental_decisions": "family and religion",
        "y-home_education_curriculum": "family and religion",
        "x-minimum_wage": "labour",
        "x-union_bargaining_rights": "labour",
        "x-working_conditions_regulation": "labour",
        "x-public_healthcare": "public services",
        "x-unemployment_support": "income support",
        "x-state_pensions": "income support",
        "x-public_education_funding": "public services",
        "x-public_ownership_of_utilities": "ownership",
        "x-public_housing": "public services",
        "x-import_tariffs": "trade and industry",
        "x-corporate_bailouts": "trade and industry",
        "x-wealth_taxation": "taxation",
        "x-antitrust_breakups": "regulation",
        "x-bank_capital_rules": "regulation",
        "x-corporate_profit_taxation": "taxation",
        "x-universal_basic_income": "income support",
        "x-public_childcare": "public services",
        "x-industrial_pollution_limits": "regulation",
        "x-executive_pay_limits": "labour",
        "x-worker_board_seats": "labour",
        "x-public_transport_funding": "public services",
        "x-dismissal_protection": "labour",
        "x-industrial_policy": "trade and industry",
        "x-gig_worker_classification": "labour",
        "x-poverty_relief": "income support",
        "x-income_inequality": "income support",
        "x-job_guarantee": "income support",
        "y-encryption_access": "surveillance",
        "y-protest_permits": "speech",
        "y-flag_burning": "speech",
        "y-sex_work": "personal conduct",
        "y-gambling_limits": "personal conduct",
        "y-death_penalty": "policing and justice",
        "y-civil_asset_forfeiture": "policing and justice",
        "y-national_identity_cards": "surveillance",
        "y-compulsory_national_service": "civic duties",
        "y-compulsory_voting": "civic duties",
        "y-news_media_regulation": "speech",
        "y-curfews_for_minors": "family and religion",
        "y-organ_sales": "personal conduct",
        "y-smoking_in_bars_and_restaurants": "public health",
        "y-public_face_coverings": "family and religion",
    },
    COLLECTIVIST: {
        "x-precedence": "self and group",
        "x-identity": "self and group",
        "x-welfare": "obligations",
        "x-decisions": "obligations",
        "y-customs": "customs",
        "y-continuity": "customs",
        "y-adoption": "reform",
        "y-institutions": "reform",
    },
    TEXTING: {
        "x-batching": "message count",
        "x-notifications": "message count",
        "x-composition": "composition",
        "x-pace": "composition",
        "y-latency": "timing",
        "y-etiquette": "courtesy",
        "y-expectation": "timing",
        "y-priority": "courtesy",
    },
    PINEAPPLE: {
        "x-topping": "practice",
        "x-ordering": "judgement",
        "x-flavour": "taste",
        "x-conviction": "judgement",
        "x-tradition": "tradition",
        "x-fruit": "tradition",
        "x-ham": "taste",
        "x-texture": "taste",
        "x-crust": "taste",
        "x-cheese": "taste",
        "x-baked_fruit": "taste",
        "x-group_order": "practice",
        "x-menu": "tradition",
        "x-picking_off": "practice",
        "x-canned": "taste",
        "x-jalapenos": "taste",
        "x-acidity": "taste",
        "x-tomato_sauce": "taste",
        "x-authenticity": "tradition",
        "x-open_mind": "judgement",
        "x-leftovers": "practice",
        "x-balance": "taste",
        "x-popularity": "judgement",
        "x-first_date": "judgement",
        "x-ban": "judgement",
        "x-chefs": "tradition",
        "x-half_and_half": "practice",
        "x-barbecue_chicken": "taste",
        "x-freedom": "judgement",
        "x-reputation": "judgement",
        "x-teasing": "judgement",
        "x-first_choice": "practice",
        "x-invention": "tradition",
        "y-order": "method",
        "y-conviction": "conviction",
        "y-technique": "method",
        "y-judgement": "conviction",
        "y-crunch": "method",
        "y-splash": "method",
        "y-floating": "method",
        "y-upbringing": "custom",
        "y-children": "custom",
        "y-last_spoonful": "method",
        "y-look": "method",
        "y-coating": "method",
        "y-granola": "variants",
        "y-guests": "custom",
        "y-housemate": "conviction",
        "y-speed": "method",
        "y-late_night": "variants",
        "y-common_sense": "conviction",
        "y-contrarian": "conviction",
        "y-adverts": "custom",
        "y-fruit": "variants",
        "y-flakes": "variants",
        "y-washing_up": "method",
        "y-instinct": "conviction",
        "y-taste": "method",
        "y-plant_milk": "variants",
        "y-cafe": "custom",
        "y-fair_try": "conviction",
        "y-standard": "conviction",
        "y-pouring": "method",
        "y-rule": "conviction",
        "y-recommendation": "conviction",
        "y-habit_to_break": "conviction",
    },
}


FACET_BY_ID: Final[Mapping[str, str]] = {
    question: facet for table in FACETS.values() for question, facet in table.items()
}


class UnknownQuestionnaire(Exception):
    """A stored question without a facet is in none of the bundled questionnaires, so no facet is known for it."""


def document_hash(document: object) -> str:
    """The content hash as the package computes it: SHA-256 of the document's sorted, compact JSON."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def known_facet(question: dict[str, object], stored_hash: str) -> str:
    """The question's facet by its id, or by its id under its axis prefix; raises UnknownQuestionnaire."""
    for candidate in (f"{question['id']}", f"{question['axis']}-{question['id']}"):
        if candidate in FACET_BY_ID:
            return FACET_BY_ID[candidate]
    raise UnknownQuestionnaire(
        f"questionnaire {stored_hash} asks {question['id']!r}, which no bundled questionnaire has, "
        "so its facet is unknown"
    )


def with_facets(document: dict[str, object], stored_hash: str) -> dict[str, object]:
    """The document with each question's facet from the bundled tables; a faceted question is kept as it is."""
    questions = document["questions"]
    assert isinstance(questions, list)
    return {
        **document,
        "questions": [
            question if "facet" in question else {**question, "facet": known_facet(question, stored_hash)}
            for question in questions
        ],
    }


def without_facets(document: dict[str, object]) -> dict[str, object]:
    questions = document["questions"]
    assert isinstance(questions, list)
    return {
        **document,
        "questions": [{key: value for key, value in question.items() if key != "facet"} for question in questions],
    }


def respecified(spec: dict[str, object], old_hash: str, new_hash: str) -> dict[str, object]:
    """The spec naming `new_hash` where it named `old_hash`."""
    return {**spec, "questionnaire": new_hash} if spec["questionnaire"] == old_hash else spec


def move_experiment(connection: sa.Connection, stored_hash: str, spec: dict[str, object]) -> None:
    """Store `spec` under its own hash, point the runs of `stored_hash` at it, and drop the old row."""
    new_hash = document_hash(spec)
    if new_hash == stored_hash:
        return
    connection.execute(
        sa.text("INSERT INTO experiments (hash, spec) VALUES (:hash, CAST(:spec AS jsonb)) ON CONFLICT DO NOTHING"),
        {"hash": new_hash, "spec": json.dumps(spec, ensure_ascii=False)},
    )
    connection.execute(
        sa.text("UPDATE runs SET experiment_hash = :new WHERE experiment_hash = :old"),
        {"new": new_hash, "old": stored_hash},
    )
    connection.execute(sa.text("DELETE FROM experiments WHERE hash = :old"), {"old": stored_hash})
    return


def stored_specs(connection: sa.Connection) -> list[tuple[str, dict[str, object]]]:
    return [(row.hash, row.spec) for row in connection.execute(sa.text("SELECT hash, spec FROM experiments"))]


def move_questionnaire(connection: sa.Connection, stored_hash: str, document: dict[str, object]) -> None:
    """Store `document` under its own hash, move every experiment naming `stored_hash` to it, drop the old row."""
    new_hash = document_hash(document)
    if new_hash == stored_hash:
        return
    connection.execute(
        sa.text(
            "INSERT INTO questionnaires (hash, document) VALUES (:hash, CAST(:document AS jsonb)) "
            "ON CONFLICT DO NOTHING"
        ),
        {"hash": new_hash, "document": json.dumps(document, ensure_ascii=False)},
    )
    for spec_hash, spec in stored_specs(connection):
        move_experiment(connection, spec_hash, respecified(spec, stored_hash, new_hash))
    connection.execute(sa.text("DELETE FROM questionnaires WHERE hash = :old"), {"old": stored_hash})
    return


def stored_questionnaires(connection: sa.Connection) -> list[tuple[str, dict[str, object]]]:
    rows = connection.execute(sa.text("SELECT hash, document FROM questionnaires"))
    return [(row.hash, row.document) for row in rows]


def upgrade() -> None:
    connection = op.get_bind()
    for stored_hash, document in stored_questionnaires(connection):
        move_questionnaire(connection, stored_hash, with_facets(document, stored_hash))
    return


def downgrade() -> None:
    connection = op.get_bind()
    for stored_hash, document in stored_questionnaires(connection):
        move_questionnaire(connection, stored_hash, without_facets(document))
    return
