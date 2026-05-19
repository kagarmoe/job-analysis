"""Tests for department normalization and YOE extraction (now in db.py)."""
from db import normalize_department


def test_anthropic_engineering():
    assert normalize_department("Software Engineering - Infrastructure") == "Engineering"


def test_anthropic_engineering_design():
    # "Engineering & Design - Product" has both "design" and "engineering"
    # Design is higher priority in rules, so it matches Design
    assert normalize_department("Engineering & Design - Product") == "Design"


def test_anthropic_research():
    assert normalize_department("AI Research & Engineering") == "Research"


def test_anthropic_product():
    assert normalize_department("Product Management, Support, & Operations") == "Product"


def test_anthropic_people():
    assert normalize_department("People") == "People"


def test_anthropic_finance():
    assert normalize_department("Finance") == "Finance"


def test_anthropic_legal():
    assert normalize_department("Legal") == "Legal"


def test_anthropic_sales():
    assert normalize_department("Sales") == "Sales & BD"


def test_anthropic_marketing():
    assert normalize_department("Marketing & Brand") == "Marketing & Comms"
    assert normalize_department("Communications") == "Marketing & Comms"


def test_anthropic_security():
    assert normalize_department("Security") == "Security & Compliance"
    assert normalize_department("Safeguards (Trust & Safety)") == "Security & Compliance"


def test_anthropic_public_policy():
    assert normalize_department("AI Public Policy & Societal Impacts") == "Public Policy"


def test_anthropic_operations():
    assert normalize_department("Technical Program Management") == "Other"
    assert normalize_department("Compute") == "Operations"
    assert normalize_department("Data Science & Analytics") == "Other"


def test_crusoe_departments():
    assert normalize_department("Cloud Engineering") == "Engineering"
    assert normalize_department("Digital Infrastructure Group (DIG)") == "Engineering"
    assert normalize_department("Power Infrastructure") == "Engineering"
    assert normalize_department("Software") == "Engineering"
    assert normalize_department("Hardware") == "Engineering"
    assert normalize_department("Product and Design") == "Design"
    assert normalize_department("People") == "People"
    assert normalize_department("Accounting and Finance") == "Finance"
    assert normalize_department("Strategic Finance and Corporate Development") == "Finance"
    assert normalize_department("Legal") == "Legal"
    assert normalize_department("Sales and BD") == "Sales & BD"
    assert normalize_department("Cloud Go-To-Market (GTM)") == "Sales & BD"
    assert normalize_department("Marketing") == "Marketing & Comms"
    assert normalize_department("Public Affairs and Sustainability") == "Public Policy"
    assert normalize_department("IT, Compliance, and Security") == "Security & Compliance"
    assert normalize_department("Manufacturing (MFG)") == "Manufacturing"
    assert normalize_department("Data Center Operations (DIG)") == "Operations"
    assert normalize_department("Business Operations") == "Operations"
    assert normalize_department("Procurement and Sourcing") == "Operations"
    assert normalize_department("Real Estate (DIG)") == "Operations"
    assert normalize_department("Energy Innovation and Commercialization") == "Other"
    assert normalize_department("Environmental, Health and Safety (EHS)") == "Other"


def test_unknown_department():
    assert normalize_department("Something Totally New") == "Other"
    assert normalize_department("") == "Other"
    assert normalize_department(None) == "Other"
    assert normalize_department(42) == "Other"


def test_other_passthrough():
    assert normalize_department("Other") == "Other"


from db import extract_yoe


def test_extract_yoe_plus_pattern():
    assert extract_yoe("requires 5+ years of experience") == 5


def test_extract_yoe_range_hyphen():
    assert extract_yoe("3-5 years experience preferred") == 3


def test_extract_yoe_range_endash():
    assert extract_yoe("3–5 years of experience") == 3


def test_extract_yoe_explicit():
    assert extract_yoe("5 years of experience required") == 5


def test_extract_yoe_no_match():
    assert extract_yoe("no experience requirement") is None


def test_extract_yoe_none_input():
    assert extract_yoe(None) is None
