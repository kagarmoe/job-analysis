"""Tests for classify.py department normalization."""
from classify import normalize_department


def test_anthropic_engineering():
    assert normalize_department("Software Engineering - Infrastructure") == "Engineering"
    assert normalize_department("Engineering & Design - Product") == "Engineering"


def test_anthropic_research():
    assert normalize_department("AI Research & Engineering") == "Research"


def test_anthropic_product():
    assert normalize_department("Product Management, Support, & Operations") == "Product & Design"


def test_anthropic_people():
    assert normalize_department("People") == "People"


def test_anthropic_finance_legal():
    assert normalize_department("Finance") == "Finance & Legal"
    assert normalize_department("Legal") == "Finance & Legal"


def test_anthropic_sales():
    assert normalize_department("Sales") == "Sales & BD"


def test_anthropic_marketing():
    assert normalize_department("Marketing & Brand") == "Marketing & Comms"
    assert normalize_department("Communications") == "Marketing & Comms"


def test_anthropic_security():
    assert normalize_department("Security") == "Security & IT"
    assert normalize_department("Safeguards (Trust & Safety)") == "Security & IT"


def test_anthropic_operations():
    assert normalize_department("Technical Program Management") == "Operations & Other"
    assert normalize_department("Compute") == "Operations & Other"
    assert normalize_department("Data Science & Analytics") == "Operations & Other"
    assert normalize_department("AI Public Policy & Societal Impacts") == "Operations & Other"


def test_crusoe_departments():
    assert normalize_department("Software") == "Engineering"
    assert normalize_department("Hardware") == "Engineering"
    assert normalize_department("Product and Design") == "Product & Design"
    assert normalize_department("People") == "People"
    assert normalize_department("Finance and Accounting") == "Finance & Legal"
    assert normalize_department("Sales and BD") == "Sales & BD"
    assert normalize_department("IT, Compliance, and Security") == "Security & IT"
    assert normalize_department("Operations") == "Operations & Other"


def test_unknown_department():
    assert normalize_department("Something Totally New") == "Operations & Other"
    assert normalize_department("") == "Operations & Other"
    assert normalize_department(None) == "Operations & Other"
    assert normalize_department(42) == "Operations & Other"


def test_other_passthrough():
    assert normalize_department("Other") == "Operations & Other"
