"""Operational denial categories.

Labels are internal descriptions for configurable mappings. They are not a copy
of the copyrighted X12 CARC/RARC code lists. Load the organization's current
licensed code list before production use.
"""

from datetime import date

DENIAL_CATEGORIES = (
    "authorization",
    "coding",
    "eligibility",
    "medical_necessity",
    "timely_filing",
    "duplicate_claims",
    "coordination_of_benefits",
    "documentation",
    "other",
    "unclassified",
)

CATEGORY_PRIORITY = {name: index for index, name in enumerate(DENIAL_CATEGORIES)}

# code, code_type, category, is_denial, label
DEFAULT_CODE_MAPPINGS: tuple[tuple[str, str, str, bool, str], ...] = (
    ("1", "CARC", "patient_responsibility", False, "Deductible"),
    ("2", "CARC", "patient_responsibility", False, "Coinsurance"),
    ("3", "CARC", "patient_responsibility", False, "Copay"),
    ("4", "CARC", "coding", True, "Procedure and modifier mismatch"),
    ("5", "CARC", "coding", True, "Procedure and place-of-service mismatch"),
    ("6", "CARC", "coding", True, "Procedure inconsistent with patient age"),
    ("9", "CARC", "coding", True, "Diagnosis inconsistent with patient age"),
    ("11", "CARC", "coding", True, "Diagnosis inconsistent with procedure"),
    ("15", "CARC", "authorization", True, "Authorization missing or invalid"),
    ("16", "CARC", "documentation", True, "Claim lacks information needed to adjudicate"),
    ("18", "CARC", "duplicate_claims", True, "Duplicate claim or service"),
    ("22", "CARC", "coordination_of_benefits", True, "Payer indicates another payer may be responsible"),
    ("23", "CARC", "coordination_of_benefits", False, "Impact of prior payer adjudication"),
    ("26", "CARC", "eligibility", True, "Expenses incurred before coverage"),
    ("27", "CARC", "eligibility", True, "Expenses incurred after coverage ended"),
    ("29", "CARC", "timely_filing", True, "Filing time limit expired"),
    ("31", "CARC", "eligibility", True, "Patient cannot be identified as insured"),
    ("32", "CARC", "eligibility", True, "Dependent is not eligible"),
    ("33", "CARC", "eligibility", True, "No dependent coverage"),
    ("39", "CARC", "authorization", True, "Denied when authorization was requested"),
    ("45", "CARC", "contractual", False, "Charge exceeds fee schedule or contracted rate"),
    ("50", "CARC", "medical_necessity", True, "Payer determined the service is not medically necessary"),
    ("55", "CARC", "medical_necessity", True, "Payer determined the service is experimental"),
    ("96", "CARC", "other", True, "Non-covered charge"),
    ("97", "CARC", "contractual", False, "Payment included in another service allowance"),
    ("109", "CARC", "eligibility", True, "Claim not covered by this payer"),
    ("119", "CARC", "other", True, "Benefit maximum reached"),
    ("167", "CARC", "medical_necessity", True, "Diagnosis not covered"),
    ("181", "CARC", "coding", True, "Procedure code not valid on the date of service"),
    ("189", "CARC", "coding", True, "Unlisted code is missing supporting detail"),
    ("197", "CARC", "authorization", True, "Precertification or authorization absent"),
    ("198", "CARC", "authorization", True, "Authorization limit exceeded"),
    ("204", "CARC", "eligibility", True, "Service is outside the benefit plan"),
    ("226", "CARC", "documentation", True, "Requested information was not provided"),
    ("227", "CARC", "documentation", True, "Requested information was insufficient"),
    ("242", "CARC", "other", True, "Rendering provider is outside the network"),
    ("252", "CARC", "documentation", True, "Documentation is required to adjudicate"),
    ("253", "CARC", "contractual", False, "Sequestration reduction"),
    ("256", "CARC", "contractual", False, "Managed-care contract excludes payment"),
    ("272", "CARC", "authorization", True, "Program guideline or authorization requirement was not met"),
    ("M62", "RARC", "authorization", False, "Remark associated with treatment authorization"),
    ("N30", "RARC", "eligibility", False, "Remark associated with eligibility"),
    ("N115", "RARC", "medical_necessity", False, "Remark associated with a coverage policy"),
    ("N95", "RARC", "other", False, "Remark associated with provider specialty billing"),
    ("MA130", "RARC", "documentation", False, "Remark associated with incomplete claim information"),
)

PATIENT_RESPONSIBILITY_CODES = {"1", "2", "3"}
BUNDLED_CODES = {"97"}
MAPPING_VERSION = 1
MAPPING_EFFECTIVE_FROM = date(2000, 1, 1)
