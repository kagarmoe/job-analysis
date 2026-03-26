"""Shared classification utilities for Anthropic job analysis notebooks."""

import html
import re
from dataclasses import dataclass
from typing import Optional

from bs4 import BeautifulSoup

# Approximate exchange rates as of Feb 2026
TO_USD = {
    "USD": 1.0,
    "EUR": 1.05,
    "GBP": 1.27,
    "CAD": 0.72,
    "AUD": 0.64,
}

# Anthropic's actual 16 departments (from anthropic.com/careers/jobs)
# Rules are ordered most-specific-first; first match wins.
DEPARTMENT_RULES = [
    ("Technical Program Management",
     r"technical program manage|TPM\b"),

    ("Safeguards (Trust & Safety)",
     r"threat (investigat|collect)|account abuse|CBRN"
     r"|safeguards analyst|safeguards.{0,15}(infrastructure|data infra)"
     r"|biological safety|red team engineer.{0,10}safeguards"
     r"|product policy manager|policy manager.{0,20}(harm|cyber|frontier)"
     r"|offensive security research.{0,10}safeguards|scaled abuse"),

    ("AI Public Policy & Societal Impacts",
     r"policy|external affairs|geopolitics|national security"
     r"|societal impacts?|research economist"),

    ("Communications",
     r"communications (manager|lead|director)|head of.{0,15}communications"),

    ("Compute",
     r"data center|compute (capacity|efficiency|platform)"
     r"|transaction manager|research compute|capacity.{0,10}(delivery|efficiency)"),

    ("Data Science & Analytics",
     r"analytics data|data (science|analytics)|analytics.{0,5}engineering"),

    ("Finance",
     r"finance|accounti?n?g|(?<!\w)tax(?!onom)|payroll|revenue (account|system)"
     r"|deal desk|order management|corporate (development|finance)"
     r"|FP&A|treasury|SOX|billing|government incentive|transfer pricing"),

    ("Legal",
     r"counsel|(?<!\w)legal|ediscovery|contracts manager"
     r"|compliance (oversight|lead)|trade compliance|IP legal"),

    ("People",
     r"recruit|immigration|administrative business partner"
     r"|internal mobility|people (program|senior)|(?<!\w)HR(?!\w)"
     r"|human resources|onboarding.{0,10}lead"),

    ("Marketing & Brand",
     r"marketing|(?<!\w)brand(?!\w)|video (director|producer)"
     r"|social media|event designer|presentation design"
     r"|copy and content|developer community|community lead|GTM narrative"),

    ("Sales",
     r"account (executive|coordinator)|solutions? architect"
     r"|customer success|business development|(?<!\w)[BS]DR(?!\w)"
     r"|forward deployed|applied AI|partner (sales|solutions|operations)"
     r"|evangelist|incentive compensation|reseller|cosell"
     r"|GTM (strategy|systems|onboarding)|nonprofit account"
     r"|partner.{0,5}(lead|manager).{0,15}(cloud|system|global|reseller)"
     r"|head of.{0,15}(GTM|solution)"),

    ("Security",
     r"application security|IT (support|systems|engineering|audiovisual)"
     r"|platform.{0,10}security|security (engineer|software|GRC|risk|technology)"
     r"|cloud security|detection.{0,5}response|insider risk"
     r"|offensive security(?!.*safeguards)|protective intelligence"
     r"|campus security|access management|customer trust|GRC"
     r"|audiovisual|security development|vulnerability"),

    ("Product Management, Support, & Operations",
     r"product (manager|lead|support|operations|management)"
     r"|developer relations|support operations|research product manager"),

    ("AI Research & Engineering",
     r"research (engineer|scientist|manager)|machine learning|(?<!\w)ML(?!\w)"
     r"|alignment|interpretability|pre-?training|post.?training"
     r"|reinforcement learning|frontier red team|kernel engineer"
     r"|performance engineer|discovery|safety fellow|security fellow"
     r"|reward model|data operations manager|AI observability"
     r"|developer education|education (labs|platform)|certification content"
     r"|training content|human data|encoding librar"),

    ("Software Engineering - Infrastructure",
     r"inference|(?<!\w)systems(?!\w)|sandboxing|networking"
     r"|continuous integration|observability|developer productivity"
     r"|data infrastructure|database|AI reliability|autonomous agent infra"
     r"|accelerator platform"),

    ("Engineering & Design - Product",
     r"software engineer|engineering manager|design engineer"
     r"|prompt engineer|model quality|full.?stack"),
]

SENIORITY_RULES = [
    ("Intern / Fellow",   r"\b(intern|fellow|apprentice)\b"),
    ("Junior",            r"\b(junior|jr\.?|entry[ -]level|associate)\b"),
    ("Senior",            r"\b(senior|sr\.?)\b"),
    ("Staff / Principal", r"\b(staff|principal)\b"),
    ("Lead",              r"\b(lead\b|tech lead)\b"),
    ("Manager",           r"\b(manager|management)\b"),
    ("Director+",         r"\b(director|head of|VP|vice president|chief|president|C-suite)\b"),
]

SENIORITY_ORDER = [
    "Intern / Fellow", "Junior", "Mid-Level", "Senior",
    "Staff / Principal", "Lead", "Manager", "Director+",
]


def classify_department(title: str) -> str:
    if not isinstance(title, str):
        return "Other"
    for dept, pattern in DEPARTMENT_RULES:
        if re.search(pattern, title, re.I):
            return dept
    return "Other"


def classify_seniority(title: str) -> str:
    if not isinstance(title, str):
        return "Mid-Level"
    t = title.lower()
    for level, pattern in SENIORITY_RULES:
        if re.search(pattern, t, re.I):
            return level
    return "Mid-Level"


def classify_work_mode(location: str) -> str:
    if not isinstance(location, str):
        return "Unknown"
    if "remote" in location.lower():
        return "Remote-Friendly"
    return "Office-Only"


def add_classifications(df):
    """Add department, seniority, work_mode columns to a dataframe with title/location."""
    df["department"] = df["title"].apply(classify_department)
    df["seniority"] = df["title"].apply(classify_seniority)
    df["work_mode"] = df["location"].apply(classify_work_mode)
    return df


def add_usd_salary(df):
    """Add rate, min_usd, max_usd, mid_usd columns to a dataframe with currency/salary_min/salary_max."""
    df["rate"] = df["currency"].map(TO_USD)
    df["min_usd"] = df["salary_min"] * df["rate"]
    df["max_usd"] = df["salary_max"] * df["rate"]
    df["mid_usd"] = (df["min_usd"] + df["max_usd"]) / 2
    return df


# ---------------------------------------------------------------------------
# Salary parsing (moved from scrape_anthropic.py for reuse across scrapers)
# ---------------------------------------------------------------------------

# Compile once at import time.
DASH_PATTERN = r"(?:\u2013|\u2014|-|–|—|\s+to\s+)"
CURRENCY_SYM_1 = r"(?P<sym1>\$|£|€)"
CURRENCY_SYM_2 = r"(?P<sym2>\$|£|€)"
NUMBER = r"(?:\d{1,3}(?:,\d{3})+|\d+)"

SALARY_RANGE_RE = re.compile(
    rf"{CURRENCY_SYM_1}\s*(?P<min>{NUMBER})\s*{DASH_PATTERN}\s*"
    rf"(?:{CURRENCY_SYM_2}\s*)?(?P<max>{NUMBER})"
)


@dataclass
class SalaryParseResult:
    salary_text: str
    currency: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    salary_unit: Optional[str]  # annual, hourly, monthly, etc.


def normalize_whitespace(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def looks_like_salary_text(text: str) -> bool:
    if not text:
        return False
    if SALARY_RANGE_RE.search(text):
        return True
    # Some posts mention currency code even if the range is formatted differently
    return bool(re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", text))


def extract_salary_block_from_html(content_html: str) -> Optional[str]:
    """
    Find a salary-ish block from the job HTML content. Returns normalized text or None.
    """
    if not content_html:
        return None

    soup = BeautifulSoup(html.unescape(content_html), "html.parser")

    heading_patterns = [
        re.compile(r"\bAnnual Salary\b", re.I),
        re.compile(r"\bSalary\b", re.I),
        re.compile(r"\bCompensation\b", re.I),
        re.compile(r"\bPay\b", re.I),
    ]

    candidates = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "strong", "b", "p", "span", "div", "li"]):
        txt = normalize_whitespace(tag.get_text(" ", strip=True))
        if not txt:
            continue
        if any(p.search(txt) for p in heading_patterns):
            candidates.append(tag)

    for tag in candidates:
        parent = tag.parent if tag.parent else tag
        parent_txt = normalize_whitespace(parent.get_text(" ", strip=True)) if parent else ""
        if looks_like_salary_text(parent_txt):
            return parent_txt

        # look at a few next siblings
        collected = []
        sib = parent
        for _ in range(8):
            sib = sib.find_next_sibling()
            if sib is None:
                break
            t = normalize_whitespace(sib.get_text(" ", strip=True))
            if t:
                collected.append(t)
                joined = " ".join(collected)
                if looks_like_salary_text(joined):
                    return joined

    # fallback: scan whole text
    all_text = normalize_whitespace(soup.get_text(" ", strip=True))
    m = re.search(r"(Annual Salary|Salary|Compensation).{0,400}", all_text, flags=re.I)
    if m:
        window = all_text[m.start() : min(len(all_text), m.start() + 500)]
        if looks_like_salary_text(window):
            return window

    mm = SALARY_RANGE_RE.search(all_text)
    if mm:
        s = max(0, mm.start() - 80)
        e = min(len(all_text), mm.end() + 80)
        return all_text[s:e]

    return None


def parse_salary_text(block: str) -> SalaryParseResult:
    block = normalize_whitespace(html.unescape(block))

    # unit
    unit = None
    if re.search(r"\bAnnual\b|\bper year\b|\byearly\b", block, re.I):
        unit = "annual"
    elif re.search(r"\bhour\b|\bhourly\b|\bper hour\b", block, re.I):
        unit = "hourly"
    elif re.search(r"\bmonth\b|\bmonthly\b|\bper month\b", block, re.I):
        unit = "monthly"

    # currency code
    currency = None
    m_code = re.search(r"\b(USD|EUR|GBP|CAD|AUD)\b", block)
    if m_code:
        currency = m_code.group(1)

    # numeric range
    m = SALARY_RANGE_RE.search(block)
    if m:
        sym = m.group("sym1")
        min_val = int(m.group("min").replace(",", ""))
        max_val = int(m.group("max").replace(",", ""))
        if not currency:
            currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(sym)
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    # secondary pattern: "131,040–165,000 USD"
    m2 = re.search(rf"(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*{DASH_PATTERN}\s*(\d{{1,3}}(?:,\d{{3}})+|\d+)\s*(USD|EUR|GBP|CAD|AUD)?",
                   block)
    if m2:
        min_val = int(m2.group(1).replace(",", ""))
        max_val = int(m2.group(2).replace(",", ""))
        if not currency and m2.group(3):
            currency = m2.group(3)
        return SalaryParseResult(block, currency, min_val, max_val, unit)

    return SalaryParseResult(block, currency, None, None, unit)
