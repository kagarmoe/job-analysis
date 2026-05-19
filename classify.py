import re
from typing import Optional

TO_USD = {
    "USD": 1.0,
    "EUR": 1.05,
    "GBP": 1.27,
    "CAD": 0.72,
    "AUD": 0.64,
}

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

NORMALIZED_DEPARTMENT_RULES = [
    ("Research",              r"\bresearch\b"),
    ("Manufacturing",         r"\bmanufactur"),
    ("Design",                r"\bdesign\b"),
    ("Engineering",           r"\bengineering\b|\bsoftware\b|\bhardware\b|\binfrastructure\b"),
    ("Product",               r"\bproduct\b"),
    ("People",                r"\bpeople\b|\brecruit|\bHR\b|\bhuman resources\b"),
    ("Finance",               r"\bfinance\b|\baccounting\b"),
    ("Legal",                 r"\blegal\b|\bcounsel\b"),
    ("Sales & BD",            r"\bsales\b|\bbusiness development\b|\b[BS]DR\b|\bBD\b|\bGTM\b|\bgo.to.market\b"),
    ("Marketing & Comms",     r"\bmarketing\b|\bbrand\b|\bcommunication"),
    ("Public Policy",         r"\bpolicy\b|\bpublic affairs\b|\bsocietal impacts?\b|\bgeopolitics\b"),
    ("Security & Compliance", r"\bsecurity\b|\bsafeguard|\bcompliance\b"),
    ("IT",                    r"\bIT\b|\binformation technology\b"),
    ("Operations",            r"\boperation|\bcompute\b|\bdata center\b|\bprocurement\b|\breal estate\b|\bsupply chain\b"),
    ("Other",                 r".*"),
]

def normalize_department(department_raw: str) -> str:
    if not isinstance(department_raw, str) or not department_raw:
        return "Other"
    for bucket, pattern in NORMALIZED_DEPARTMENT_RULES:
        if re.search(pattern, department_raw, re.I):
            return bucket
    return "Other"


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
    for level, pattern in SENIORITY_RULES:
        if re.search(pattern, title, re.I):
            return level
    return "Mid-Level"


def classify_work_mode(location: str) -> str:
    if not isinstance(location, str):
        return "Unknown"
    if "remote" in location.lower():
        return "Remote-Friendly"
    return "Office-Only"


def add_classifications(df):
    df["department"] = df["title"].apply(classify_department)
    df["seniority"] = df["title"].apply(classify_seniority)
    df["work_mode"] = df["location"].apply(classify_work_mode)
    return df


def add_usd_salary(df):
    df["rate"] = df["currency"].map(TO_USD)
    df["min_usd"] = df["salary_min"] * df["rate"]
    df["max_usd"] = df["salary_max"] * df["rate"]
    df["mid_usd"] = (df["min_usd"] + df["max_usd"]) / 2
    return df

_YOE_RE = re.compile(
    r"(\d+)\+?\s*(?:\u2013|-|to)\s*(\d+)\s+years?"   # "3-5 years" or "3\u20135 years"
    r"|(\d+)\+\s*years?"                              # "5+ years"
    r"|(\d+)\s+years?\s+of\s+experience",              # "5 years of experience"
    re.I,
)

def extract_yoe(text: str) -> Optional[int]:
    """Return minimum years of experience mentioned in text, or None."""
    if not text:
        return None
    m = _YOE_RE.search(text)
    if not m:
        return None
    groups = [int(g) for g in m.groups() if g is not None]
    return min(groups) if groups else None
