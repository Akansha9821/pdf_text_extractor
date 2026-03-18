import re
from pathlib import Path
import pandas as pd
from pypdf import PdfReader


SECTION_HEADERS = {
    "Contact",
    "Top Skills",
    "Summary",
    "Experience",
    "Education",
    "Certifications",
    "Projects",
    "Honors-Awards",
    "Languages",
    "Publications",
}

MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|November|December"
)
MONTH_YEAR_PATTERN = rf"(?:{MONTHS})\s+\d{{4}}"

NON_NAME_TERMS = {
    "analyst",
    "engineer",
    "developer",
    "specialist",
    "management",
    "training",
    "framework",
    "quality",
    "software",
    "cloud",
    "excel",
    "word",
    "seo",
    "python",
    "java",
    "sql",
    "pharmacy",
    "engagement",
}


def clean_text(raw_text: str) -> str:
    text = raw_text.replace("\u00a0", " ")
    text = re.sub(r"-\s*\n\s*", "", text)  # joins words split across lines
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{2,}", "\n", text)
    return text.strip()


def clean_lines(text: str) -> list[str]:
    lines = [line.strip() for line in text.splitlines()]
    lines = [line for line in lines if line and not line.startswith("Page ")]
    return lines


def extract_email(text: str) -> str:
    match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
    return match.group(0) if match else "NA"


def extract_phone(text: str) -> str:
    mobile_match = re.search(r"(\+?\d[\d\s-]{7,}\d)\s*\(Mobile\)", text, re.IGNORECASE)
    if mobile_match:
        return re.sub(r"\s+", "", mobile_match.group(1))

    generic_match = re.search(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\d{3}[-.\s]?){2}\d{4}\b", text)
    if generic_match:
        return re.sub(r"\s+", "", generic_match.group(0))
    return "NA"


def extract_linkedin(text: str) -> str:
    normalized = text.replace("\n", "")
    match = re.search(
        r"(?:https?://)?(?:www\.)?linkedin\.com/[A-Za-z0-9\-_/]+",
        normalized,
        re.IGNORECASE,
    )
    if not match:
        return "NA"
    link = match.group(0)
    if not link.startswith("http"):
        link = f"https://{link}"
    return link


def is_name_like(line: str) -> bool:
    if any(ch in line for ch in [",", "|", "@", "http", "www", "(", ")"]):
        return False
    words = line.split()
    if len(words) < 2 or len(words) > 5:
        return False
    lower_words = {w.lower() for w in words}
    if lower_words & NON_NAME_TERMS:
        return False
    for word in words:
        if not re.fullmatch(r"[A-Za-z.'-]+", word):
            return False
    return True


def split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current = "HEADER"
    sections[current] = []
    for line in lines:
        if line in SECTION_HEADERS:
            current = line
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def infer_name(lines: list[str], email: str, top_section_name: str) -> str:
    exp_idx = lines.index("Experience") if "Experience" in lines else min(60, len(lines))
    for idx, line in enumerate(lines[:exp_idx]):
        if (
            re.search(r"\b(India|USA|United States|UK|Canada)\b", line, re.IGNORECASE)
            or ("," in line and len(line.split()) >= 2 and len(line) <= 60)
        ):
            for offset in [2, 1, 3]:
                cand_idx = idx - offset
                if cand_idx >= 0 and is_name_like(lines[cand_idx]):
                    return lines[cand_idx]

    if top_section_name != "NA":
        return top_section_name

    for line in lines[:40]:
        if (
            line not in SECTION_HEADERS
            and not re.search(r"linkedin|@|\(Mobile\)|\d", line, re.IGNORECASE)
            and len(line.split()) >= 2
            and len(line) <= 60
            and is_name_like(line)
        ):
            return line

    if email != "NA":
        return email.split("@")[0].replace(".", " ").replace("_", " ").title()
    return "NA"


def infer_location(lines: list[str]) -> str:
    for line in lines[:50]:
        if re.search(r"\b(India|USA|United States|UK|Canada)\b", line, re.IGNORECASE):
            return line
    return "NA"


def extract_top_skills(sections: dict[str, list[str]]) -> tuple[str, str, str, str]:
    raw_lines = sections.get("Top Skills", [])
    raw_lines = [s for s in raw_lines if s not in SECTION_HEADERS]
    skills: list[str] = []
    name_candidate = "NA"

    for line in raw_lines:
        if is_name_like(line) and name_candidate == "NA":
            name_candidate = line
            if skills:
                break
        if re.search(r"\b(india|linkedin|experience|summary|education)\b", line, re.IGNORECASE):
            break
        if "," in line or "|" in line:
            break
        if len(skills) < 3:
            skills.append(line)

    if not skills and raw_lines:
        for line in raw_lines:
            if len(skills) < 3 and len(line) <= 60 and not re.search(r"[@|,]", line):
                skills.append(line)
            if len(skills) == 3:
                break

    if not skills:
        return "NA", "NA", "NA", name_candidate
    primary = skills[0]
    secondary = skills[1] if len(skills) > 1 else "NA"
    return primary, secondary, ", ".join(skills), name_candidate


def extract_current_role(sections: dict[str, list[str]]) -> tuple[str, str, str, str, int, int]:
    experience_lines = sections.get("Experience", [])
    if not experience_lines:
        return "NA", "NA", "NA", "NA", 0, 0

    company = experience_lines[0] if len(experience_lines) >= 1 else "NA"
    role = experience_lines[1] if len(experience_lines) >= 2 else "NA"

    date_pattern = re.compile(
        rf"({MONTH_YEAR_PATTERN})\s*[-–—]\s*(Present|{MONTH_YEAR_PATTERN})\s*(?:\(([^)]*)\))?",
        re.IGNORECASE,
    )
    joined = "\n".join(experience_lines)
    match = date_pattern.search(joined)

    start_date, end_date, duration = "NA", "NA", ""
    if match:
        start_date = match.group(1)
        end_date = match.group(2)
        duration = match.group(3) or ""

    years = 0
    months = 0
    if duration:
        year_match = re.search(r"(\d+)\s+year", duration, re.IGNORECASE)
        month_match = re.search(r"(\d+)\s+month", duration, re.IGNORECASE)
        if year_match:
            years = int(year_match.group(1))
        if month_match:
            months = int(month_match.group(1))

    return company, role, start_date, end_date, years, months


def extract_summary(sections: dict[str, list[str]]) -> str:
    summary_lines = sections.get("Summary", [])
    if not summary_lines:
        return "NA"
    return " ".join(summary_lines)[:2000]


def extract_education(sections: dict[str, list[str]]) -> str:
    education_lines = sections.get("Education", [])
    if not education_lines:
        return "NA"
    return " | ".join(education_lines[:12])


def extract_profile(pdf_path: Path) -> dict[str, str | int]:
    reader = PdfReader(str(pdf_path))
    raw_text = "\n".join((page.extract_text() or "") for page in reader.pages)
    text = clean_text(raw_text)
    lines = clean_lines(text)
    sections = split_sections(lines)

    email = extract_email(text)
    phone = extract_phone(text)
    linkedin = extract_linkedin(text)
    primary_skill, secondary_skill, top_skills, top_section_name = extract_top_skills(
        sections
    )
    name = infer_name(lines, email, top_section_name)
    location = infer_location(lines)
    company, role, start_date, end_date, exp_years, exp_months = extract_current_role(
        sections
    )
    return {
        "Name": name,
        "Email": email,
        "Mobile": phone,
        "Location": location,
        "Profession": role,
        "Organisation Detail": company,
        "Primary Skill": primary_skill,
        "Secondary Skill": secondary_skill,
        "Top Skills": top_skills,
        "Experience_Years": exp_years,
        "Experience_Month": exp_months,
        "Start Date": start_date,
        "End Date": end_date,
        "Status": "NA",
        "Bench Days": 0,
        "Bench Reason": "NA",
        "Linked In Profile": linkedin,
    }


def main() -> None:
    pdf_dir = Path("candidate_profile")
    output_csv = Path("data/employee_extracted.csv")

    pdf_files = sorted(pdf_dir.glob("Profile*.pdf"))
    if not pdf_files:
        raise FileNotFoundError(f"No PDF files found in {pdf_dir}")

    rows = []
    for pdf_file in pdf_files:
        try:
            rows.append(extract_profile(pdf_file))
        except Exception as exc:
            rows.append(
                {
                    "Name": "NA",
                    "Email": "NA",
                    "Mobile": "NA",
                    "Location": "NA",
                    "Profession": "NA",
                    "Organisation Detail": "NA",
                    "Primary Skill": "NA",
                    "Secondary Skill": "NA",
                    "Top Skills": "NA",
                    "Experience_Years": 0,
                    "Experience_Month": 0,
                    "Start Date": "NA",
                    "End Date": "NA",
                    "Status": "NA",
                    "Bench Days": 0,
                    "Bench Reason": f"Parsing failed: {exc}",
                    "Linked In Profile": "NA",
                }
            )

    df = pd.DataFrame(rows)
    df.insert(0, "Employee_id", [f"E{i:03d}" for i in range(1, len(df) + 1)])
    required_columns = [
        "Employee_id",
        "Name",
        "Email",
        "Mobile",
        "Location",
        "Profession",
        "Organisation Detail",
        "Primary Skill",
        "Secondary Skill",
        "Experience_Years",
        "Experience_Month",
        "Start Date",
        "End Date",
        "Status",
        "Bench Days",
        "Bench Reason",
        "Linked In Profile",
    ]
    df = df[required_columns]
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_csv, index=False)

    print(f"Parsed {len(df)} profiles")
    print(f"Saved structured output to: {output_csv}")
    print(df.head(5).to_string(index=False))


if __name__ == "__main__":
    main()
