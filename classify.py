"""Shared classification utilities for Anthropic job analysis notebooks."""

import re

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
