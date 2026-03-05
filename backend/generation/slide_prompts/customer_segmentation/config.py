"""Shared config for Customer Segmentation slide prompts."""

# Row schema definitions for Customer Segmentation (for reference / future use)
ROW_SCHEMA: list[dict[str, str]] = [
    {
        "row_label": "Demographics",
        "definition": (
            "age, gender, and personal identity attributes only."
            "Exclude location, city tier, hospital level, institution type, and patient volume."
        ),
    },
    {
        "row_label": "Preferences",
        "definition": (
            "Scope components: channel preference, detailing style, call frequency. "
            "Refers only to engagement preferences toward pharmaceutical sales representatives. "
            "Excludes patient communication and treatment preference."
        ),
    },
    {
        "row_label": "Attitudes/Beliefs",
        "definition": (
            "Scope components: overall mindset, treatment approach, product perceptions. "
            "Refers to explicitly stated beliefs or evaluations. "
            "Excludes observable prescribing behavior."
        ),
    },
    {
        "row_label": "Capabilities",
        "definition": (
            "Scope components: support staff availability, caregiver support, "
            "knowledge level, clinical experience. "
            "Refers to ability or available resources. "
            "Excludes attitudes and environment."
        ),
    },
    {
        "row_label": "Environment",
        "definition": (
            "Scope components: practice size, socio-economic environment, location. "
            "Includes city tier, hospital level, patient volume, and institutional setting. "
            "Excludes personal identity attributes."
        ),
    },
    {
        "row_label": "Behaviors",
        "definition": (
            "Scope components: product usage, early adopter status, practice affinity, "
            "prescribing patterns, treatment sequencing, adoption timing. "
            "Refers only to observable actions."
        ),
    },
    {
        "row_label": "Drivers",
        "definition": (
            "Scope component: explicitly stated motivating factors for prescribing the product. "
            "Must directly describe reasons to prescribe the product."
        ),
    },
    {
        "row_label": "Barriers",
        "definition": (
            "Scope component: explicitly stated discouraging factors for prescribing the product. "
            "Must directly describe reasons not to prescribe the product."
        ),
    },
]

# Lookup: row_label (lower) → definition
SCHEMA_BY_LABEL: dict[str, str] = {
    row["row_label"].lower(): row["definition"]
    for row in ROW_SCHEMA
}

# Normalized row labels that identify slide 2 (segment summary table)
SLIDE2_INDEXES = [
    "segment summary",
    "current behavior",
    "desired behavior",
    "segment prioritization",
]
