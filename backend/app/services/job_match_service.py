from __future__ import annotations

import io
import re
from typing import Any

from app.core.config import settings
from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.services.ai_service import AIService, AIServiceError
from app.services.benchmark_service import BenchmarkService
from app.services.embedding_service import EmbeddingRepository, GeminiEmbeddingProvider
from app.services.storage_service import StorageService

CONTROLLED_EQUIVALENTS = {
    "python": ["python", "py"],
    "fastapi": ["fastapi", "fast api", "api framework"],
    "sqlalchemy": ["sqlalchemy", "orm", "sql alchemy"],
    "postgresql": ["postgresql", "postgres"],
    "docker": ["docker", "containers", "containerization"],
    "rest": ["rest", "rest api", "restful"],
    "api design": ["api design", "api-design", "backend api design"],
    "system design": ["system design", "architecture", "distributed systems"],
    "leadership": ["leadership", "team lead", "people management", "manager"],
    "microservices": ["microservices", "service oriented architecture"],
    "aws": ["aws", "amazon web services"],
    "azure": ["azure", "microsoft cloud"],
    "gcp": ["gcp", "google cloud"],
    "javascript": ["javascript", "js"],
    "typescript": ["typescript", "ts"],
    "react": ["react", "reactjs"],
    "node": ["node", "nodejs", "node.js"],
    "retrieval augmented generation": [
        "retrieval augmented generation",
        "retrieval-augmented generation",
        "rag",
    ],
    "large language model": ["large language model", "large language models", "llm", "llms"],
    "generative ai": ["generative ai", "large language model", "large language models", "llm", "llms"],
    "workflow automation": ["workflow automation", "automated workflows"],
    "communication": ["communication", "communication skills"],
    "collaboration": ["collaboration", "team collaboration", "teamwork"],
    "problem solving": ["problem solving", "problem-solving", "problem solving skills"],
    "analytical thinking": ["analytical thinking", "analytical", "analytical skills"],
    "independent work": ["independent work", "work independently", "works independently", "independently"],
    "ai agents": ["ai agents", "ai agent"],
    "willingness to learn": ["willingness to learn", "quick learner"],
    "attention to detail": ["attention to detail", "attention todetail"],
}

SKILL_SYNONYMS = CONTROLLED_EQUIVALENTS

CATEGORY_WEIGHTS = {
    "Technical Skills": 25,
    "Responsibilities": 25,
    "Relevant Experience": 15,
    "Projects": 10,
    "Keywords": 10,
    "Job Title": 5,
    "Education/Certifications": 5,
    "Soft Skills": 5,
    "ATS Structure": 5,
}

GENERIC_KEYWORDS = {
    "experience", "experienced", "engineer", "engineering", "backend", "frontend", "developer",
    "team", "support", "customer", "business", "systems", "solutions", "projects", "role",
    "responsibilities", "deliver", "focus", "work", "workflows", "strong", "ownership",
    "operational", "excellent", "technical", "quality", "process", "results"
}

STOPWORDS = {
    "the", "a", "an", "and", "or", "with", "for", "of", "to", "in", "on", "at", "by",
    "as", "we", "are", "is", "be", "our", "you", "your", "their", "this", "that", "from",
    "into", "over", "under", "after", "before", "role", "hiring", "team", "job", "resume",
    # Common job-site navigation / accessibility chrome, not job requirements.
    "skip", "main", "content", "home", "teams", "locations", "categories", "account",
    "settings", "sign", "resources", "faq", "apply", "now", "description",
    "career", "careers", "applications", "profile", "menu", "navigation", "cookies",
    "privacy", "terms", "search", "view", "page", "site", "website",
}


class JobMatchService:
    REQUIREMENT_SNAPSHOT_VERSION = 1

    def __init__(self, db, repository):
        self.db = db
        self.repository = repository

    def _semantic_enabled(self) -> bool:
        return bool(
            self.db is not None
            and settings.GEMINI_API_KEY
            and getattr(getattr(self.db, "bind", None), "dialect", None) is not None
            and self.db.bind.dialect.name == "postgresql"
        )

    def analyze(self, resume: Resume, job: JobDescription, user_id: int) -> dict:
        resume_text = self._normalize_text(resume.text_content or "")
        jd_text = self._normalize_text(job.normalized_text or job.text_content or "")

        snapshot = getattr(job, "requirement_snapshot", None)
        if (
            isinstance(snapshot, dict)
            and snapshot.get("version") == self.REQUIREMENT_SNAPSHOT_VERSION
            and isinstance(snapshot.get("sets"), dict)
        ):
            requirement_sets = snapshot["sets"]
        else:
            requirement_sets = self._extract_requirement_sets(
                jd_text,
                role_name=getattr(job, "role_name", None),
                company_name=getattr(job, "company_name", None),
            )
            if self.db is not None and getattr(job, "id", None) is not None:
                job.requirement_snapshot = {
                    "version": self.REQUIREMENT_SNAPSHOT_VERSION,
                    "sets": requirement_sets,
                }
        technical_terms = requirement_sets["technical"]
        responsibility_terms = requirement_sets["responsibilities"]
        experience_terms = requirement_sets["experience"]
        project_terms = requirement_sets["projects"]
        keyword_terms = requirement_sets["keywords"]
        title_terms = requirement_sets["title"]
        education_terms = requirement_sets["education"]
        certification_terms = requirement_sets["certifications"]
        soft_skill_terms = requirement_sets["soft_skills"]

        requirement_catalog = self._build_requirement_catalog(
            requirement_sets,
            job.normalized_text or job.text_content or jd_text,
        )
        requirement_matches = self._evaluate_requirement_catalog(
            requirement_catalog,
            resume_text,
            user_id=user_id,
            resume_id=resume.id,
        )
        technical_matches = [item for item in requirement_matches if item["category"] == "Technical Skills"]
        matched_skills = [item["requirement"] for item in technical_matches if item["status"] == "MATCHED"]
        partially = [item["requirement"] for item in technical_matches if item["status"] == "PARTIALLY_MATCHED"]
        missing_skills = [item["requirement"] for item in technical_matches if item["status"] == "MISSING"]

        responsibilities_matched = [
            item["requirement"] for item in requirement_matches
            if item["category"] == "Responsibilities"
            and item["status"] in {"MATCHED", "PARTIALLY_MATCHED"}
        ]

        category_scores, category_statuses = self._score_requirement_categories(requirement_matches)
        score_breakdown = {
            category: category_scores.get(category, 0.0)
            for category in CATEGORY_WEIGHTS
        }
        applicable_categories = [
            category for category, status in category_statuses.items()
            if status != "NOT_EVALUATED"
        ]
        applicable_weight = sum(CATEGORY_WEIGHTS[category] for category in applicable_categories)
        earned_points = sum(score_breakdown[category] for category in applicable_categories)
        job_match_score = (
            min(100.0, round((earned_points / applicable_weight) * 100.0, 2))
            if applicable_weight
            else 0.0
        )

        section_analysis = self._build_section_analysis(
            resume.text_content or "",
            job.normalized_text or job.text_content or "",
            requirement_sets,
            requirement_matches=requirement_matches,
            layout_preserved=bool(getattr(resume, "docx_layout_preserved", False)),
            resume=resume,
        )
        ats_compatibility_score = round(section_analysis["section_scores"].get("ATS Structure", 0.0), 2)
        layout_preservation_score = round(section_analysis["layout_analysis"]["score"], 2)
        truthfulness_status = self._determine_truthfulness_status(requirement_matches=requirement_matches)
        evidence_found = self._build_evidence(technical_terms, resume_text)
        missing_by_priority = sorted(
            technical_matches,
            key=lambda item: (item["status"] != "MISSING", item["importance"] != "high", item["requirement"]),
        )
        important_gaps = [
            item["requirement"] for item in missing_by_priority
            if item["status"] == "MISSING"
        ][:5]
        ats_structure_issues = section_analysis["layout_analysis"]["issues"] + self._build_structure_issues(resume_text)
        recommendations = self._build_recommendations(missing_skills, important_gaps, score_breakdown)
        recommendations.extend(section_analysis["layout_analysis"]["recommendations"])
        benchmark_records = []
        if self.db is not None:
            benchmark_query = self.db.query(JobDescription).filter(JobDescription.user_id == user_id)
            if getattr(job, "id", None) is not None:
                benchmark_query = benchmark_query.filter(JobDescription.id != job.id)
            benchmark_records = [
                {
                    "text": item.normalized_text or item.text_content,
                    "role_name": item.role_name,
                }
                for item in (
                    benchmark_query
                    .order_by(JobDescription.created_at.desc())
                    .limit(20)
                    .all()
                )
            ]
        benchmark = BenchmarkService().summarize(
            benchmark_records,
            role_name=getattr(job, "role_name", None) or self._extract_job_title(jd_text),
            current_jd_text=jd_text,
            resume_text=resume_text,
        )

        payload = {
            "id": 0,
            "user_id": user_id,
            "resume_id": getattr(resume, "id", 0),
            "job_description_id": getattr(job, "id", 0),
            "job_match_score": job_match_score,
            "ats_compatibility_score": ats_compatibility_score,
            "layout_preservation_score": layout_preservation_score,
            "truthfulness_status": truthfulness_status,
            "matched_skills": matched_skills,
            "missing_skills": missing_skills,
            "partially_matched_skills": partially,
            "responsibilities_matched": responsibilities_matched,
            "evidence_found": evidence_found,
            "important_gaps": important_gaps,
            "ats_structure_issues": ats_structure_issues,
            "recommendations": recommendations,
            "score_breakdown": score_breakdown,
            "benchmark": benchmark,
            "requirement_matches": requirement_matches,
            "category_scores": category_scores,
            "category_statuses": category_statuses,
            "section_scores": section_analysis["section_scores"],
            "section_details": section_analysis["section_details"],
            "present_sections": section_analysis["present_sections"],
            "project_matches": section_analysis["project_matches"],
            "layout_analysis": section_analysis["layout_analysis"],
        }

        if self.repository is not None:
            saved = self.repository.create(
                user_id=user_id,
                resume_id=resume.id,
                job_description_id=job.id,
                payload=payload,
            )
            payload["id"] = saved.id

        return payload

    @staticmethod
    def _build_section_analysis(
        resume_text: str,
        jd_text: str,
        requirement_sets: dict[str, list[str]],
        *,
        requirement_matches: list[dict[str, Any]] | None = None,
        layout_preserved: bool,
        resume: Resume | None = None,
    ) -> dict[str, Any]:
        sections = JobMatchService._extract_resume_sections(resume_text)
        jd_signals = JobMatchService._build_jd_signal_terms(jd_text, requirement_sets)

        section_order = [
            "Summary",
            "Skills",
            "Experience",
            "Projects",
            "Education",
            "Certifications",
            "Achievements",
            "Soft Skills",
            "Keywords",
            "ATS Structure",
        ]
        section_scores: dict[str, float] = {}
        section_details: dict[str, list[str]] = {}

        section_categories = {
            "Summary": ("Job Title", "Responsibilities", "Keywords"),
            "Skills": ("Technical Skills",),
            "Experience": ("Responsibilities", "Relevant Experience", "Keywords"),
            "Projects": ("Projects",),
            "Education": ("Education",),
            "Certifications": ("Certifications",),
            "Achievements": (),
            "Soft Skills": ("Soft Skills",),
            "Keywords": tuple(CATEGORY_WEIGHTS),
        }

        source_map = {
            "Summary": sections.get("summary", ""),
            "Skills": sections.get("technical skills", ""),
            "Experience": sections.get("experience", ""),
            "Projects": sections.get("projects", ""),
            "Education": sections.get("education", ""),
            "Certifications": sections.get("certifications", ""),
            "Achievements": sections.get("achievements", ""),
            "Soft Skills": sections.get("soft skills", ""),
            "Keywords": resume_text,
        }

        for section in section_order[:-1]:
            content = source_map.get(section, "")
            section_items = [
                item for item in (requirement_matches or [])
                if any(
                    category in section_categories.get(section, ())
                    for category in item.get("source_categories", [item["category"]])
                )
            ]
            if not content.strip() and not section_items:
                continue
            if not section_items:
                # A section with no corresponding JD requirement is neutral:
                # it must never be treated as a failure or reduce the score.
                section_scores[section] = 100.0
                section_details[section] = [
                    "Not mentioned in the selected JD — this section is not evaluated and does not reduce the match score."
                ]
                continue
            score, matched, missing = JobMatchService._score_local_requirement_items(content, section_items)
            section_scores[section] = score
            details = []
            if content:
                details.append(f"{len(matched)} of {max(1, len(section_items))} section signals found.")
                if matched:
                    details.append("Matched: " + ", ".join(matched[:8]))
                if missing:
                    details.append("Gaps: " + ", ".join(missing[:6]))
            else:
                details.append("This section was not detected in the resume.")
                missing_preview = missing[:6]
                if missing_preview:
                    details.append("Relevant signals not evidenced here: " + ", ".join(missing_preview))
            section_details[section] = details

        ats_score, ats_details = JobMatchService._score_ats_structure(sections, resume_text)
        section_scores["ATS Structure"] = ats_score
        section_details["ATS Structure"] = ats_details

        project_signals = JobMatchService._section_signal_terms(requirement_sets.get("projects", []))
        project_matches = JobMatchService._build_project_matches(
            sections.get("projects", ""),
            project_signals,
            full_resume_text=resume_text,
            requirement_items=[
                item for item in (requirement_matches or [])
                if "Projects" in item.get("source_categories", [item["category"]])
            ],
        )
        layout_analysis = JobMatchService._build_layout_analysis(
            resume_text,
            sections,
            layout_preserved=layout_preserved,
            resume=resume,
        )

        section_label_by_source = {
            "summary": "Summary",
            "technical skills": "Skills",
            "skills": "Skills",
            "experience": "Experience",
            "projects": "Projects",
            "education": "Education",
            "certifications": "Certifications",
            "achievements": "Achievements",
            "soft skills": "Soft Skills",
        }
        present_sections = []
        for source_name, content in sections.items():
            label = section_label_by_source.get(source_name)
            if label and content.strip() and label not in present_sections:
                present_sections.append(label)

        return {
            "section_scores": {key: round(value, 2) for key, value in section_scores.items()},
            "section_details": section_details,
            "present_sections": present_sections,
            "project_matches": project_matches,
            "layout_analysis": layout_analysis,
        }

    @staticmethod
    def _extract_resume_sections(text: str) -> dict[str, str]:
        # Use line/block boundaries instead of searching for headings anywhere
        # in flattened text. This prevents ordinary phrases such as "projects"
        # inside a bullet from becoming false section boundaries.
        aliases = {
            "professional summary": "summary", "summary": "summary", "profile": "summary", "objective": "summary",
            "experience": "experience", "work experience": "experience", "professional experience": "experience",
            "employment": "experience", "work history": "experience", "employment history": "experience",
            "projects": "projects", "selected projects": "projects", "personal projects": "projects",
            "education": "education", "academic background": "education", "qualifications": "education",
            "certifications": "certifications", "certificates": "certifications", "licenses": "certifications",
            "training": "certifications", "achievements": "achievements", "awards": "achievements", "honors": "achievements",
            "soft skills": "soft skills", "core competencies": "technical skills", "key skills": "technical skills",
            "skills": "technical skills", "technical skills": "technical skills", "technologies": "technical skills",
        }
        sections: dict[str, list[str]] = {}
        current: str | None = None
        lines = [line.strip() for line in (text or "").replace("\r", "").split("\n")]

        def normalize_heading(line: str) -> str:
            value = re.sub(r"^[•*#\-\s]+|[:|\-\s]+$", "", line.lower())
            return re.sub(r"\s+", " ", value).strip()

        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            heading = normalize_heading(line)
            inline_match = re.match(r"^(.{2,40}?)[\s:|\-]+(.+)$", line)
            if heading in aliases:
                current = aliases[heading]
                sections.setdefault(current, [])
                continue
            if inline_match:
                inline_heading = normalize_heading(inline_match.group(1))
                if inline_heading in aliases:
                    current = aliases[inline_heading]
                    sections.setdefault(current, []).append(inline_match.group(2).strip())
                    continue
            if current is not None:
                sections.setdefault(current, []).append(line)

        result = {key: re.sub(r"\s+", " ", " ".join(values)).strip() for key, values in sections.items() if values}

        # Uploaded resume extraction can flatten paragraph breaks while keeping
        # conventional uppercase headings. Recover those boundaries without
        # treating ordinary lowercase prose as a heading.
        if len(result) < 2 and text:
            flat_aliases = sorted(
                {alias for alias in aliases if alias.replace(" ", "").isalpha()},
                key=len,
                reverse=True,
            )
            flat_pattern = re.compile(
                r"(?<![A-Za-z])(" + "|".join(re.escape(alias.upper()) for alias in flat_aliases) + r")(?![A-Za-z])"
            )
            flat_matches = list(flat_pattern.finditer(text))
            flat_sections: dict[str, str] = {}
            for index, match in enumerate(flat_matches):
                heading = match.group(1).lower()
                canonical = aliases.get(heading)
                if canonical is None:
                    continue
                start = match.end()
                end = flat_matches[index + 1].start() if index + 1 < len(flat_matches) else len(text)
                body = re.sub(r"\s+", " ", text[start:end]).strip(" :|-|")
                if body:
                    flat_sections[canonical] = body
            if flat_sections:
                result = flat_sections

        return result


    @staticmethod
    def _build_jd_signal_terms(
        jd_text: str,
        requirement_sets: dict[str, list[str]],
    ) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        allowed_categories = (
            "technical",
            "responsibilities",
            "experience",
            "projects",
            "keywords",
            "certifications",
            "education",
            "soft_skills",
        )
        for category in allowed_categories:
            values = requirement_sets.get(category, [])
            for value in values:
                normalized = JobMatchService._normalize_text(value)
                if (
                    normalized
                    and normalized not in STOPWORDS
                    and normalized not in GENERIC_KEYWORDS
                    and normalized not in seen
                    and len(normalized) > 2
                    and len(normalized.split()) <= 5
                ):
                    terms.append(normalized)
                    seen.add(normalized)

        # Do not infer skills from arbitrary page phrases. Role/company/job-id text
        # must never become a technical requirement or gap.
        return terms[:40]

    @staticmethod
    def _section_signal_terms(values: list[str]) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = JobMatchService._normalize_text(value)
            if not normalized or normalized in STOPWORDS or normalized in GENERIC_KEYWORDS:
                continue
            tokens = normalized.split()
            # Each extracted requirement is one signal. Do not split
            # long phrases into artificial bigrams because that inflates the
            # denominator and makes a correctly matched requirement look weak.
            candidates = [normalized]
            for candidate in candidates:
                candidate = candidate.strip()
                if (
                    candidate
                    and candidate not in STOPWORDS
                    and candidate not in GENERIC_KEYWORDS
                    and len(candidate) > 2
                    and candidate not in seen
                ):
                    terms.append(candidate)
                    seen.add(candidate)
        return terms[:30]

    @staticmethod
    def _score_section_content(content: str, jd_signals: list[str]) -> tuple[float, list[str], list[str]]:
        normalized = JobMatchService._normalize_text(content)
        if not jd_signals:
            return 0.0, [], []

        matched = []
        missing = []
        for term in jd_signals:
            if JobMatchService._section_term_matches(term, normalized):
                matched.append(term)
            else:
                missing.append(term)
        score = (len(matched) / len(jd_signals)) * 100.0
        return min(100.0, score), matched, missing

    @staticmethod
    def _score_local_requirement_items(
        content: str,
        requirement_items: list[dict[str, Any]],
    ) -> tuple[float, list[str], list[str]]:
        if not requirement_items:
            return 0.0, [], []

        matched: list[str] = []
        missing: list[str] = []
        earned = 0.0
        possible = 0.0
        for item in requirement_items:
            requirement = item["requirement"]
            importance_weight = 2.0 if item.get("importance") == "high" else 1.0
            possible += importance_weight
            status, _ = JobMatchService._evaluate_requirement_with_method(requirement, content)
            if status == "MATCHED":
                earned += importance_weight
                matched.append(requirement)
            elif status == "PARTIALLY_MATCHED":
                earned += importance_weight * 0.5
                matched.append(requirement)
            else:
                missing.append(requirement)

        return min(100.0, (earned / possible) * 100.0), matched, missing

    @staticmethod
    def _section_term_matches(term: str, normalized_content: str) -> bool:
        if JobMatchService._contains_phrase(normalized_content, term):
            return True

        if any(
            JobMatchService._contains_phrase(normalized_content, candidate)
            for candidate in JobMatchService._equivalent_terms(term)
            if candidate != JobMatchService._normalize_text(term)
        ):
            return True

        if "programming language" in term:
            return bool(re.search(r"(?<![a-z0-9])(python|java|javascript|typescript|c\+\+|c#|go|ruby|kotlin|swift|sql)(?![a-z0-9])", normalized_content))

        if "degree" in term and ("bachelor" in term or "master" in term):
            has_degree = bool(
                re.search(
                    r"\b(?:bachelor|master)(?:\s+s)?(?:\s+of)?\s+(?:technology|engineering|science)?\b"
                    r"|\bb\s*tech\b|\bbtech\b|\bb\s*e\b|\bbe\b",
                    normalized_content,
                )
            )
            if "computer science" in term:
                return has_degree and JobMatchService._contains_phrase(normalized_content, "computer science")
            if "related field" in term:
                return has_degree and any(
                    field in normalized_content
                    for field in (
                        "computer science",
                        "information technology",
                        "data science",
                        "engineering",
                    )
                )
            return has_degree

        if term == "web applications":
            return JobMatchService._contains_phrase(normalized_content, "web application") or any(
                JobMatchService._contains_phrase(normalized_content, item) for item in ("react", "html", "css")
            )

        if term == "data mining":
            return JobMatchService._contains_phrase(normalized_content, "data mining")

        if term in {"large-scale computing", "large scale computing"}:
            return (
                JobMatchService._contains_phrase(normalized_content, "large-scale computing")
                or JobMatchService._contains_phrase(normalized_content, "large scale computing")
                or (JobMatchService._contains_phrase(normalized_content, "large scale") and JobMatchService._contains_phrase(normalized_content, "computing"))
            )

        if term == "information extraction":
            return (
                JobMatchService._contains_phrase(normalized_content, "information extraction")
                or JobMatchService._contains_phrase(normalized_content, "extract information")
            )

        if term == "distributed systems":
            return JobMatchService._contains_phrase(normalized_content, "distributed systems")

        if term == "software development":
            return JobMatchService._contains_phrase(normalized_content, "software development")

        if term == "testing":
            return any(JobMatchService._contains_phrase(normalized_content, item) for item in (
                "testing", "test", "api testing", "software testing"
            ))

        if term == "security":
            return any(JobMatchService._contains_phrase(normalized_content, item) for item in (
                "jwt", "authentication", "authorization", "security"
            ))

        if term == "algorithms":
            return any(JobMatchService._contains_phrase(normalized_content, item) for item in (
                "algorithms", "algorithm", "data structures and algorithms", "dsa"
            ))

        if term == "scalability":
            return any(item in normalized_content for item in (
                "scalability", "scale", "scalable"
            ))

        return False

    @staticmethod
    def _score_ats_structure(sections: dict[str, str], resume_text: str) -> tuple[float, list[str]]:
        # Summary and formal Experience are optional for an entry-level resume.
        checks = {
            "technical skills": bool(sections.get("technical skills")),
            "projects or experience": bool(sections.get("projects") or sections.get("experience")),
            "education": bool(sections.get("education")),
            "email": bool(re.search(r"\b[\w.+-]+@[\w.-]+\.[a-zA-Z]{2,}\b", resume_text)),
            "profile_link": bool(re.search(r"\b(?:github|linkedin|leetcode)\b", resume_text, flags=re.IGNORECASE)),
        }
        score = (sum(checks.values()) / len(checks)) * 100.0
        details = [
            ("Present" if value else "Missing") + f": {key.replace('technical skills', 'skills').replace('_', ' ')}"
            for key, value in checks.items()
        ]
        return min(100.0, score), details

    @staticmethod
    def _extract_project_entries(projects_text: str) -> list[dict[str, str]]:
        if not projects_text:
            return []

        entry_pattern = re.compile(
            r"(?P<name>[A-Z][^|]{2,100}?)\s*\|\s*"
            r"(?P<stack>[^|]{2,180}?)\s*\(Git\s*Hub\)\s*"
        )
        matches = list(entry_pattern.finditer(projects_text))
        entries: list[dict[str, str]] = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(projects_text)
            content = projects_text[start:end].strip(" �•-")
            entries.append({
                "name": re.sub(r"\s+", " ", match.group("name")).strip(),
                "stack": re.sub(r"\s+", " ", match.group("stack")).strip(),
                "content": content,
            })

        if entries:
            return entries

        return [{
            "name": "Projects section",
            "stack": "",
            "content": projects_text,
        }]

    @staticmethod
    def _build_project_matches(
        projects_text: str,
        jd_signals: list[str],
        *,
        full_resume_text: str = "",
        requirement_items: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        entries = JobMatchService._extract_project_entries(projects_text)
        full_resume_normalized = JobMatchService._normalize_text(full_resume_text)
        results = []
        for project in entries:
            project_text = f"{project['name']} {project['stack']} {project['content']}"
            if requirement_items is not None:
                score, matched, missing = JobMatchService._score_local_requirement_items(
                    project_text,
                    requirement_items,
                )
            else:
                score, matched, missing = JobMatchService._score_section_content(project_text, jd_signals)

            # A project-level gap is only a true resume gap when the requirement
            # is absent from the entire resume. If it exists elsewhere, report
            # that fact rather than calling it missing.
            missing_entire_resume = [
                term for term in missing
                if JobMatchService._evaluate_requirement(term, full_resume_normalized) == "MISSING"
            ]
            present_elsewhere = [
                term for term in missing
                if JobMatchService._evaluate_requirement(term, full_resume_normalized) in {
                    "MATCHED",
                    "PARTIALLY_MATCHED",
                }
            ]

            results.append({
                "name": project["name"],
                "stack": project["stack"],
                "score": round(score, 2),
                "matched_signals": matched[:10],
                "missing_signals": missing_entire_resume[:10],
                "present_elsewhere": present_elsewhere[:10],
                "evidence": [project["content"][:900]] if project["content"] else [],
            })
        return results

    @staticmethod
    def _build_layout_analysis(
        resume_text: str,
        sections: dict[str, str],
        *,
        layout_preserved: bool,
        resume: Resume | None = None,
    ) -> dict[str, Any]:
        issues: list[str] = []
        recommendations: list[str] = []
        diagnostics: list[str] = []
        score = 100.0

        if resume is not None and resume.storage_path:
            try:
                source_bytes = StorageService().get_bytes(resume.storage_path)
                if resume.content_type == "application/pdf":
                    from pypdf import PdfReader

                    reader = PdfReader(io.BytesIO(source_bytes))
                    page_count = len(reader.pages)
                    diagnostics.append(f"Pages: {page_count}")
                    if page_count == 0:
                        issues.append("No readable pages were detected.")
                        score -= 30
                    elif page_count > 2:
                        recommendations.append("Keep the resume to 1–2 pages unless the role genuinely requires more.")
                        score -= 5

                    sizes = set()
                    font_names: set[str] = set()
                    for page in reader.pages:
                        box = page.mediabox
                        sizes.add((round(float(box.width), 1), round(float(box.height), 1)))
                        resources = page.get("/Resources") or {}
                        if hasattr(resources, "get_object"):
                            resources = resources.get_object()
                        fonts = resources.get("/Font") or {}
                        if hasattr(fonts, "get_object"):
                            fonts = fonts.get_object()
                        for font_ref in fonts.values():
                            font = font_ref.get_object() if hasattr(font_ref, "get_object") else font_ref
                            base_font = str(font.get("/BaseFont") or "").lstrip("/")
                            if "+" in base_font:
                                base_font = base_font.split("+", 1)[1]
                            if base_font and not base_font.lower().startswith("symbol"):
                                font_names.add(re.sub(r"-(Bold|Italic|BoldItalic)$", "", base_font))

                    if sizes == {(595.3, 841.9)}:
                        diagnostics.append("Page size: A4")
                    else:
                        diagnostics.append("Page size: custom/non-A4")

                    diagnostics.append(
                        "Fonts detected: " + (", ".join(sorted(font_names)) if font_names else "not available")
                    )
                    if len(font_names) <= 1:
                        diagnostics.append("Font consistency: single family")
                    else:
                        diagnostics.append(f"Font families detected: {len(font_names)}")

                    if not resume_text.strip():
                        issues.append("Resume text could not be extracted reliably.")
                        score -= 25
                else:
                    diagnostics.append("Source format: DOCX")
                    if not layout_preserved:
                        recommendations.append("Keep the original DOCX as the editable source so its formatting can be preserved exactly.")
            except Exception as exc:
                diagnostics.append("Layout metadata could not be read from the source file.")
                recommendations.append("Open the original source once in Word/Adobe and keep fonts and spacing consistent.")

        # Optional profile links are content suggestions, not layout failures.
        status = "NEEDS_ATTENTION" if issues else "GOOD"

        return {
            "score": max(0.0, round(score, 2)),
            "status": status,
            "issues": issues,
            "diagnostics": diagnostics,
            "recommendations": recommendations,
        }

    @staticmethod
    def _extract_requirement_sets(
        jd_text: str,
        *,
        role_name: str | None = None,
        company_name: str | None = None,
    ) -> dict[str, list[str]]:
        normalized = JobMatchService._normalize_text(jd_text)
        excluded_metadata = {
            *JobMatchService._tokenize_metadata(role_name),
            *JobMatchService._tokenize_metadata(company_name),
            "job", "jobs", "jobcode", "id",
        }

        # Keep the analysis corpus focused on the actual posting and remove
        # boilerplate that can never be a resume requirement.
        boilerplate_markers = (
            "workplace accommodation",
            "equal opportunity",
            "download our app",
            "find careers",
            "my career",
            "resources",
            "privacy and data",
        )
        analysis_text = normalized
        cut_positions = [
            analysis_text.find(marker)
            for marker in boilerplate_markers
            if analysis_text.find(marker) >= 0
        ]
        if cut_positions:
            analysis_text = analysis_text[:min(cut_positions)].strip()

        fallback = {
            "technical": JobMatchService._terms_present_in_text(
                [
                    "python", "fastapi", "sql", "sqlalchemy", "postgresql", "docker", "kubernetes", "rest",
                    "api design", "system design", "aws", "microservices", "javascript",
                    "typescript", "react", "node", "java", "c++", "c#", "git",
                    "information extraction", "large-scale computing", "large scale computing",
                    "distributed systems", "web applications", "data mining", "scalability",
                    "security", "algorithms", "software programming language",
                    "software development", "testing", "generative ai", "prompt engineering",
                    "retrieval augmented generation", "rag", "ai agents", "workflow automation",
                    "ai automation", "cloud",
                ],
                analysis_text,
            ),
            "responsibilities": JobMatchService._terms_present_in_text(
                [
                    "design and develop",
                    "solve complex problems",
                    "audit",
                    "metric monitoring",
                    "build and testing process",
                    "design",
                    "develop",
                    "build",
                    "operate",
                    "maintain",
                    "test",
                ],
                analysis_text,
            ),
            "experience": [],
            "projects": JobMatchService._terms_present_in_text(
                [
                    "information extraction",
                    "large-scale computing",
                    "large scale computing",
                    "distributed systems",
                    "web applications",
                    "data mining",
                    "scalability",
                    "security",
                    "algorithms",
                    "software systems",
                    "generative ai",
                    "prompt engineering",
                    "retrieval-augmented generation",
                    "retrieval augmented generation",
                    "ai agents",
                    "workflow automation",
                    "automation",
                ],
                analysis_text,
            ),
            "keywords": [],
            # The job title is valid matching evidence; do not remove it as metadata.
            "title": [JobMatchService._normalize_text(role_name)] if role_name else [],
            "education": [],
            "certifications": [],
            "soft_skills": JobMatchService._terms_present_in_text(
                [
                    "communication",
                    "collaboration",
                    "teamwork",
                    "leadership",
                    "problem solving",
                    "problem-solving",
                    "analytical thinking",
                    "analytical",
                    "attention to detail",
                    "work independently",
                    "independently",
                    "curiosity",
                    "willingness to learn",
                    "creativity",
                    "judgment",
                ],
                analysis_text,
            ),
            "achievements": [],
        }

        years_match = re.search(
            r"\b\d+\+?\s+years?\b[^.]{0,100}\bprofessional\b[^.]{0,120}\bexperience\b",
            analysis_text,
        )
        if years_match:
            fallback["experience"].append(years_match.group(0).strip())
        if "programming with at least one software programming language" in analysis_text:
            fallback["experience"].append(
                "programming with at least one software programming language"
            )

        fallback["technical"] = JobMatchService._prioritize_requirements(
            fallback["technical"], analysis_text
        )

        degree_match = re.search(
            r"\b(?:bachelor|master)(?:\s+s)?\s+degree\b[^.]{0,220}",
            analysis_text,
        )
        if degree_match:
            field_match = re.search(
                r"\bin\s+(computer science|information technology|data science|engineering)\b",
                degree_match.group(0),
            )
            if field_match:
                fallback["education"] = [
                    "bachelor or master degree in computer science or related field"
                ]
            else:
                fallback["education"] = ["bachelor or master degree"]

        if not settings.GEMINI_API_KEY:
            return fallback

        try:
            analysis = AIService().analyze_job_description(analysis_text)
        except (AIServiceError, ValueError):
            return fallback

        ai_technical = JobMatchService._filter_metadata_terms(
            JobMatchService._extract_requirements(analysis.technical_skills),
            excluded_metadata,
        )
        ai_responsibilities = JobMatchService._filter_metadata_terms(
            JobMatchService._extract_requirements(analysis.responsibilities),
            excluded_metadata,
        )
        ai_experience = JobMatchService._filter_metadata_terms(
            JobMatchService._extract_requirements(analysis.experience_requirements),
            excluded_metadata,
        )
        ai_keywords = JobMatchService._filter_metadata_terms(
            JobMatchService._extract_requirements(analysis.important_keywords),
            excluded_metadata,
        )

        ai_technical = [
            item for item in ai_technical
            if JobMatchService._looks_like_technical_requirement(item)
        ]
        responsibility_allowed = (
            "design", "develop", "audit", "monitor", "test", "build",
            "solve", "operate", "maintain", "scale", "implement", "code",
        )
        ai_responsibilities = [
            item for item in ai_responsibilities
            if len(item.split()) >= 2
            and any(marker in item for marker in responsibility_allowed)
        ]
        ai_experience = [
            item for item in ai_experience
            if any(marker in item for marker in (
                "year", "years", "intern", "experience",
                "programming language", "professional",
            ))
        ]

        education = fallback["education"]
        certification = JobMatchService._filter_metadata_terms(
            JobMatchService._extract_requirements(analysis.certifications),
            excluded_metadata,
        )
        soft_skills = JobMatchService._filter_metadata_terms(
            JobMatchService._extract_requirements(analysis.soft_skills),
            excluded_metadata,
        )
        soft_skills = [
            item for item in soft_skills
            if JobMatchService._looks_like_soft_skill(item)
        ]
        soft_skills = [
            JobMatchService._canonical_requirement(item)
            for item in (soft_skills + fallback["soft_skills"])
            if JobMatchService._canonical_requirement(item)
        ]
        soft_skills = list(dict.fromkeys(soft_skills))
        if "high judgment" in soft_skills:
            soft_skills = [item for item in soft_skills if item != "judgment"]

        # Keep education as one qualification requirement instead of
        # turning "bachelor", "degree", and the subject into separate signals.
        degree_match = re.search(
            r"\b(?:bachelor|master)(?:\s+s)?\s+degree\b[^.]{0,220}",
            analysis_text,
        )
        if degree_match:
            field_match = re.search(
                r"\bin\s+(computer science|information technology|data science|engineering)\b",
                degree_match.group(0),
            )
            education = [
                "bachelor or master degree in computer science or related field"
                if field_match
                else "bachelor or master degree"
            ]

        return {
            "technical": list(dict.fromkeys(ai_technical + fallback["technical"])),
            "responsibilities": list(dict.fromkeys(ai_responsibilities + fallback["responsibilities"])),
            "experience": list(dict.fromkeys(ai_experience + fallback["experience"])),
            "projects": fallback["projects"],
            "keywords": list(dict.fromkeys(ai_keywords)),
            "title": fallback["title"],
            "education": education,
            "certifications": certification,
            "soft_skills": soft_skills,
            "achievements": [],
        }

    @staticmethod
    def _tokenize_metadata(value: str | None) -> set[str]:
        normalized = JobMatchService._normalize_text(value or "")
        return {token for token in normalized.split() if token}

    @staticmethod
    def _terms_present_in_text(candidates: list[str], text: str) -> list[str]:
        normalized = JobMatchService._normalize_text(text)
        return [
            candidate
            for candidate in candidates
            if JobMatchService._contains_phrase(normalized, candidate)
        ]

    @staticmethod
    def _filter_metadata_terms(terms: list[str], excluded: set[str]) -> list[str]:
        cleaned: list[str] = []
        for term in terms:
            normalized = JobMatchService._normalize_text(term)
            if not normalized:
                continue
            # Remove exact role, source, and job-ID metadata without removing
            # legitimate compound technology names.
            if normalized in excluded:
                continue
            if normalized in {
                "cross", "border", "tech", "description", "software", "data", "web",
                "workflow", "automation", "accommodations", "benefits", "inclusive", "experiences",
                "how", "times", "out", "support",
            }:
                continue
            if re.fullmatch(r"\d+", normalized):
                continue
            if re.fullmatch(r"(?:job\s*)?id\s*[a-z0-9-]+", normalized):
                continue
            cleaned.append(normalized)
        return list(dict.fromkeys(cleaned))

    @staticmethod
    def _looks_like_technical_requirement(value: str) -> bool:
        markers = (
            "python", "java", "javascript", "typescript", "fastapi", "django", "react",
            "node", "sql", "postgres", "mysql", "docker", "kubernetes", "aws", "azure",
            "gcp", "git", "api", "database", "programming", "algorithm", "distributed systems",
            "scalability", "security", "testing", "cloud", "automation", "generative ai",
            "software development", "retrieval augmented",
            "rag", "ai agent", "workflow automation", "llm", "large language model",
        )
        normalized = JobMatchService._normalize_text(value)
        return any(JobMatchService._contains_phrase(normalized, marker) for marker in markers)

    @staticmethod
    def _looks_like_soft_skill(value: str) -> bool:
        markers = (
            "communication", "teamwork", "collaboration", "leadership", "adaptability",
            "problem solving", "analytical", "time management", "attention to detail",
            "creativity", "judgment", "curiosity", "independently", "willingness to learn",
            "quick learner",
        )
        normalized = JobMatchService._normalize_text(value)
        return any(JobMatchService._contains_phrase(normalized, marker) for marker in markers)

    @staticmethod
    def _normalize_text(text: str) -> str:
        lower = (text or "").lower()
        lower = lower.replace("&", " and ")
        lower = lower.replace("-", " ")
        lower = re.sub(r"[^a-z0-9\s/]", " ", lower)
        lower = re.sub(r"\s+", " ", lower).strip()
        lower = re.sub(r"\battention\s+todetail\b", "attention to detail", lower)
        return lower

    @staticmethod
    def _equivalent_terms(requirement: str) -> list[str]:
        normalized = JobMatchService._normalize_text(requirement)
        for canonical, values in CONTROLLED_EQUIVALENTS.items():
            normalized_values = [JobMatchService._normalize_text(value) for value in values]
            if normalized == JobMatchService._normalize_text(canonical) or normalized in normalized_values:
                return list(dict.fromkeys([JobMatchService._normalize_text(canonical), *normalized_values]))
        return [normalized]

    @staticmethod
    def _extract_requirements(items: list[str]) -> list[str]:
        terms: list[str] = []
        seen: set[str] = set()
        for item in items:
            value = item.strip().lower()
            if not value or value in STOPWORDS or value in GENERIC_KEYWORDS:
                continue
            if value not in seen:
                terms.append(value)
                seen.add(value)
        return terms

    @staticmethod
    def _prioritize_requirements(requirements: list[str], jd_text: str) -> list[str]:
        if not requirements:
            return []
        priority = []
        for requirement in requirements:
            if JobMatchService._contains_phrase(jd_text, requirement):
                priority.append(requirement)
        if priority:
            return priority
        return requirements[:6]

    @staticmethod
    def _extract_keywords(text: str) -> list[str]:
        tokens = [token for token in text.split() if token and token not in STOPWORDS and token not in GENERIC_KEYWORDS]
        unique: list[str] = []
        for token in tokens:
            if token not in unique:
                unique.append(token)
        return unique[:20]

    @staticmethod
    def _extract_title_tokens(text: str) -> list[str]:
        title = text.split(" ")[:8]
        return [token for token in title if token and token not in STOPWORDS and token not in GENERIC_KEYWORDS]

    def _evaluate_requirements(
        self,
        requirements: list[str],
        resume_text: str,
        *,
        user_id: int,
        resume_id: int | None = None,
        category_by_requirement: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        semantic_results: dict[str, dict[str, Any]] = {}

        if self._semantic_enabled() and requirements:
            try:
                embedding_repo = EmbeddingRepository(self.db)
                vectors = GeminiEmbeddingProvider().embed_queries(requirements)
                for requirement, vector in zip(requirements, vectors, strict=True):
                    matches = embedding_repo.search_similar(
                        query_vector=vector,
                        user_id=user_id,
                        source_types=["resume_chunk"],
                        limit=1,
                        resume_id=resume_id,
                    )
                    if matches:
                        semantic_results[requirement] = matches[0]
            except Exception:
                # pgvector may be unavailable/blocked on a local Windows
                # installation. Semantic matching is an enhancement, not a
                # hard dependency for deterministic ATS analysis.
                semantic_results = {}

        for requirement in requirements:
            if category_by_requirement and category_by_requirement.get(requirement) == "Job Title":
                status, lexical_method = self._evaluate_title_requirement(requirement, resume_text)
            else:
                status, lexical_method = self._evaluate_requirement_with_method(requirement, resume_text)
            evidence = self._build_requirement_evidence(requirement, resume_text)
            semantic = semantic_results.get(requirement)

            if status == "MISSING" and semantic is not None:
                similarity = float(semantic["similarity"])
                if similarity >= 0.75:
                    status = "PARTIALLY_MATCHED"
                    lexical_method = "semantic_similarity"
                    evidence = (
                        f"Semantic evidence found in resume chunk {semantic['chunk_id']} "
                        f"with similarity {similarity:.3f}: {semantic['text']}"
                    )

            results.append(
                {
                    "requirement": requirement,
                    "status": status,
                    "evidence": evidence,
                    "match_method": lexical_method,
                    "semantic_similarity": (
                        float(semantic["similarity"]) if semantic is not None else None
                    ),
                    "semantic_chunk_id": (
                        semantic["chunk_id"] if semantic is not None else None
                    ),
                }
            )
        return results

    @staticmethod
    def _build_requirement_catalog(
        requirement_sets: dict[str, list[str]],
        jd_text: str,
    ) -> list[dict[str, Any]]:
        category_names = {
            "technical": "Technical Skills",
            "responsibilities": "Responsibilities",
            "experience": "Relevant Experience",
            "projects": "Projects",
            "keywords": "Keywords",
            "title": "Job Title",
            "education": "Education/Certifications",
            "certifications": "Education/Certifications",
            "soft_skills": "Soft Skills",
        }
        source_section_names = {
            "technical": "Technical Skills",
            "responsibilities": "Responsibilities",
            "experience": "Relevant Experience",
            "projects": "Projects",
            "keywords": "Keywords",
            "title": "Job Title",
            "education": "Education",
            "certifications": "Certifications",
            "soft_skills": "Soft Skills",
        }
        catalog = []
        by_requirement: dict[str, dict[str, Any]] = {}
        for source_category, requirements in requirement_sets.items():
            category = category_names.get(source_category)
            source_section = source_section_names.get(source_category)
            if not category or not source_section:
                continue
            for requirement in requirements:
                normalized = JobMatchService._canonical_requirement(requirement)
                if not normalized:
                    continue
                existing = by_requirement.get(normalized)
                if existing is not None:
                    if source_section not in existing["source_categories"]:
                        existing["source_categories"].append(source_section)
                    continue
                item = {
                    "requirement": normalized,
                    "category": category,
                    "source_categories": [source_section],
                    "importance": JobMatchService._requirement_importance(normalized, jd_text),
                }
                by_requirement[normalized] = item
                catalog.append(item)
        return catalog

    @staticmethod
    def _canonical_requirement(requirement: str) -> str:
        normalized = JobMatchService._normalize_text(requirement)
        if not normalized:
            return ""
        # Canonicalize safe lexical variants before deduplication so the same
        # requirement cannot appear as multiple gaps (for example
        # "work independently" and "independently").
        aliases = {
            "work independently": "independent work",
            "works independently": "independent work",
            "independently": "independent work",
            "independent work": "independent work",
            "problem solving skills": "problem solving",
            "problem solving": "problem solving",
            "problem-solving": "problem solving",
            "analytical": "analytical thinking",
            "analytical skills": "analytical thinking",
            "analytical thinking": "analytical thinking",
            "ai agent": "ai agents",
            "ai agents": "ai agents",
        }
        normalized = aliases.get(normalized, normalized)
        equivalents = JobMatchService._equivalent_terms(normalized)
        return equivalents[0] if equivalents else normalized

    def _evaluate_requirement_catalog(
        self,
        requirements: list[dict[str, Any]],
        resume_text: str,
        *,
        user_id: int,
        resume_id: int | None = None,
    ) -> list[dict[str, Any]]:
        evaluated = {
            item["requirement"]: item
            for item in self._evaluate_requirements(
                [item["requirement"] for item in requirements],
                resume_text,
                user_id=user_id,
                resume_id=resume_id,
                category_by_requirement={item["requirement"]: item["category"] for item in requirements},
            )
        }
        results = []
        sections = self._extract_resume_sections(resume_text)
        for item in requirements:
            requirement = item["requirement"]
            base = evaluated[requirement]
            results.append({
                **item,
                "status": base["status"],
                "evidence": base["evidence"],
                "evidence_reference": self._evidence_reference(
                    requirement,
                    sections,
                    resume_text,
                    semantic_chunk_id=base.get("semantic_chunk_id"),
                ),
                "match_method": base["match_method"],
                "reason": self._match_reason(requirement, base["status"], base["evidence"]),
                "semantic_similarity": base.get("semantic_similarity"),
                "semantic_chunk_id": base.get("semantic_chunk_id"),
            })
        return results

    @staticmethod
    def _score_requirement_categories(
        requirement_matches: list[dict[str, Any]],
    ) -> tuple[dict[str, float], dict[str, str]]:
        scores: dict[str, float] = {}
        statuses: dict[str, str] = {}
        for category, weight in CATEGORY_WEIGHTS.items():
            if category == "ATS Structure":
                statuses[category] = "NOT_EVALUATED"
                scores[category] = 0.0
                continue
            items = [item for item in requirement_matches if item["category"] == category]
            if not items:
                statuses[category] = "NOT_EVALUATED"
                scores[category] = 0.0
                continue
            points = {"MATCHED": 1.0, "PARTIALLY_MATCHED": 0.5, "MISSING": 0.0, "NOT_EVALUATED": 0.0}
            earned = sum(points.get(item["status"], 0.0) * (2.0 if item["importance"] == "high" else 1.0) for item in items)
            possible = sum(2.0 if item["importance"] == "high" else 1.0 for item in items)
            scores[category] = round(weight * earned / possible, 2)
            statuses[category] = "EVALUATED"
        return scores, statuses

    @staticmethod
    def _requirement_importance(requirement: str, jd_text: str) -> str:
        candidates = JobMatchService._equivalent_terms(requirement)
        priority_markers = {"required", "must", "critical", "essential", "key", "mandatory"}
        # Evaluate priority inside the same JD sentence so a nearby requirement
        # such as "FastAPI is required. Docker is useful." does not make Docker
        # high priority merely because it follows a required FastAPI sentence.
        sentences = re.split(r"[.!?;:\n]+", jd_text or "")
        for raw_sentence in sentences:
            sentence = JobMatchService._normalize_text(raw_sentence)
            if not sentence:
                continue
            sentence_tokens = sentence.split()
            for candidate in candidates:
                candidate_tokens = candidate.split()
                width = len(candidate_tokens)
                for index in range(len(sentence_tokens) - width + 1):
                    if sentence_tokens[index:index + width] != candidate_tokens:
                        continue
                    context = sentence_tokens[max(0, index - 8):index] + sentence_tokens[index + width:index + width + 8]
                    if any(token in priority_markers for token in context):
                        return "high"
        return "normal"

    @staticmethod
    def _evaluate_requirement_with_method(requirement: str, resume_text: str) -> tuple[str, str]:
        normalized_requirement = JobMatchService._normalize_text(requirement)
        normalized_resume = JobMatchService._normalize_text(resume_text)
        if JobMatchService._contains_phrase(normalized_resume, normalized_requirement):
            return "MATCHED", "exact_normalized"
        if JobMatchService._section_term_matches(normalized_requirement, normalized_resume):
            if any(token in normalized_requirement for token in ("degree", "certification", "certificate")):
                return "MATCHED", "normalized_qualification"
            return "PARTIALLY_MATCHED", "safe_phrase_or_synonym"
        if JobMatchService._has_related_match(normalized_requirement, normalized_resume):
            return "PARTIALLY_MATCHED", "explicit_synonym"
        return "MISSING", "not_found"

    @staticmethod
    def _evaluate_title_requirement(requirement: str, resume_text: str) -> tuple[str, str]:
        if JobMatchService._contains_phrase(resume_text, requirement):
            return "MATCHED", "exact_normalized"
        required_tokens = set(JobMatchService._normalize_text(requirement).split()) - STOPWORDS
        resume_tokens = set(JobMatchService._normalize_text(resume_text).split())
        overlap = required_tokens & resume_tokens
        if required_tokens and len(overlap) / len(required_tokens) >= 0.5:
            return "PARTIALLY_MATCHED", "title_token_overlap"
        return "MISSING", "not_found"

    @staticmethod
    def _contains_phrase(text: str, phrase: str) -> bool:
        normalized_text = JobMatchService._normalize_text(text)
        normalized_phrase = JobMatchService._normalize_text(phrase)
        if not normalized_phrase:
            return False
        if normalized_phrase == "react" and re.search(r"(?<![a-z0-9])react\s+native(?![a-z0-9])", normalized_text):
            return False
        pattern = r"(?<![a-z0-9])" + re.escape(normalized_phrase).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        return bool(re.search(pattern, normalized_text))

    @staticmethod
    def _evidence_reference(
        requirement: str,
        sections: dict[str, str],
        resume_text: str,
        *,
        semantic_chunk_id: int | None = None,
    ) -> str | None:
        for section, content in sections.items():
            if JobMatchService._contains_phrase(content, requirement) or JobMatchService._section_term_matches(requirement, content):
                return section.title()
        if JobMatchService._contains_phrase(resume_text, requirement):
            return "Resume text"
        if semantic_chunk_id is not None:
            return f"Resume chunk {semantic_chunk_id}"
        return None

    @staticmethod
    def _match_reason(requirement: str, status: str, evidence: str) -> str:
        if status == "MATCHED":
            return f"Resume contains {requirement} in the selected resume."
        if status == "PARTIALLY_MATCHED":
            return f"Resume contains related evidence for {requirement}, but not an exact requirement match."
        if status == "MISSING":
            return f"No reliable {requirement} evidence was found in the selected resume."
        return "This requirement was not evaluated."

    @staticmethod
    def _evaluate_requirement(requirement: str, resume_text: str) -> str:
        if not requirement:
            return "MISSING"
        if JobMatchService._contains_phrase(resume_text, requirement):
            return "MATCHED"

        # Reuse the same controlled equivalence rules used by section scoring.
        # Equivalent wording is a partial match, not a direct match.
        if JobMatchService._section_term_matches(requirement, resume_text):
            return "PARTIALLY_MATCHED"

        if JobMatchService._has_related_match(requirement, resume_text):
            return "PARTIALLY_MATCHED"
        return "MISSING"

    @staticmethod
    def _has_related_match(requirement: str, resume_text: str) -> bool:
        if any(
            JobMatchService._contains_phrase(resume_text, term)
            for term in JobMatchService._equivalent_terms(requirement)
            if term != JobMatchService._normalize_text(requirement)
        ):
            return True
        if requirement == "system design" and (JobMatchService._contains_phrase(resume_text, "system") or JobMatchService._contains_phrase(resume_text, "architecture")):
            return True
        if requirement == "api design" and "api design" in resume_text:
            return True
        return False

    @staticmethod
    def _build_requirement_evidence(requirement: str, resume_text: str) -> str:
        normalized_requirement = JobMatchService._normalize_text(requirement)
        normalized_resume = JobMatchService._normalize_text(resume_text)
        if JobMatchService._contains_phrase(normalized_resume, normalized_requirement):
            return f"Direct evidence for {requirement} found in resume text."
        if JobMatchService._section_term_matches(normalized_requirement, normalized_resume) and any(
            token in normalized_requirement for token in ("degree", "certification", "certificate")
        ):
            return f"Qualification evidence for {requirement} found in resume text."
        for candidate in SKILL_SYNONYMS.get(normalized_requirement, [normalized_requirement]):
            candidate = JobMatchService._normalize_text(candidate)
            if JobMatchService._contains_phrase(normalized_resume, candidate):
                return f"Related evidence for {requirement} found via '{candidate}'."
        if normalized_requirement == "system design" and "architecture" in normalized_resume:
            return "Related system-design evidence found via architecture wording."
        return "No direct evidence found for this requirement."

    @staticmethod
    def _find_matches(requirements: list[str], resume_text: str) -> list[str]:
        matched: list[str] = []
        for requirement in requirements:
            if JobMatchService._evaluate_requirement(requirement, resume_text) in {"MATCHED", "PARTIALLY_MATCHED"}:
                matched.append(requirement)
        return matched

    @staticmethod
    def _score_category(requirements: list[str], resume_text: str, weight: float) -> float:
        if not requirements:
            return 0.0
        matched = len(JobMatchService._find_matches(requirements, resume_text))
        coverage = matched / len(requirements)
        return min(weight, weight * coverage)

    @staticmethod
    def _score_requirement_matches(
        requirement_matches: list[dict[str, Any]],
        weight: float,
    ) -> float:
        if not requirement_matches:
            return 0.0

        points = {
            "MATCHED": 1.0,
            "PARTIALLY_MATCHED": 0.5,
            "MISSING": 0.0,
        }
        earned = sum(points.get(item.get("status"), 0.0) for item in requirement_matches)
        return min(weight, weight * earned / len(requirement_matches))

    @staticmethod
    def _build_evidence(requirements: list[str], resume_text: str) -> list[str]:
        evidence: list[str] = []
        for requirement in requirements:
            if JobMatchService._evaluate_requirement(requirement, resume_text) in {
                "MATCHED",
                "PARTIALLY_MATCHED",
            }:
                evidence.append(f"Resume directly references '{requirement}'")
        return evidence[:6]

    @staticmethod
    def _build_structure_issues(resume_text: str) -> list[str]:
        issues: list[str] = []
        normalized = resume_text.lower()
        if "skills" not in normalized and "technical skills" not in normalized:
            issues.append("Skills section is weak or missing.")
        if "projects" not in normalized and "experience" not in normalized:
            issues.append("A Projects or Experience section should be present.")
        if "education" not in normalized:
            issues.append("Education section is missing.")
        return issues

    @staticmethod
    def _build_recommendations(missing_skills: list[str], important_gaps: list[str], score_breakdown: dict[str, float]) -> list[str]:
        recommendations: list[str] = []
        if missing_skills:
            recommendations.append(f"Add missing technical evidence for: {', '.join(missing_skills[:3])}.")
        if important_gaps:
            recommendations.append("Emphasize role-critical items with direct examples and outcomes.")
        if score_breakdown.get("Responsibilities", 0) < 15:
            recommendations.append("Add clearer responsibility and impact statements tied to the target role.")
        if not recommendations:
            recommendations.append("Keep the current resume structure and strengthen examples for leadership and system-design impact.")
        return recommendations

    @staticmethod
    def _determine_truthfulness_status(
        matched_skills: list[str] | None = None,
        partially: list[str] | None = None,
        keyword_matches: list[str] | None = None,
        resume_text: str | None = None,
        requirement_matches: list[dict[str, Any]] | None = None,
    ) -> str:
        # Job Match evaluates JD coverage; it does not make a truthfulness
        # claim about the resume. Missing JD requirements therefore must not
        # produce an "UNSUPPORTED" truthfulness status. That status belongs
        # to evidence/tailoring validation, not match coverage.
        if requirement_matches is not None:
            return "SUPPORTED"
        matched_skills = matched_skills or []
        partially = partially or []
        keyword_matches = keyword_matches or []
        resume_text = resume_text or ""
        direct_evidence = [keyword for keyword in keyword_matches if keyword and keyword not in GENERIC_KEYWORDS]
        if matched_skills:
            return "SUPPORTED"
        if direct_evidence or partially:
            return "REQUIRES_REVIEW"
        if any(token in resume_text.lower() for token in ("certified", "verified", "licensed", "credentialed")):
            return "USER_VERIFIED"
        return "UNSUPPORTED"


    @staticmethod
    def _extract_job_title(text: str) -> str:
        tokens = [token for token in text.split() if token and token not in STOPWORDS and token not in GENERIC_KEYWORDS]
        if not tokens:
            return "Role-specific benchmark"
        return " ".join(tokens[:4]).title()


def self_match(requirement: str, resume_text: str) -> bool:
    if not requirement:
        return False
    if JobMatchService._contains_phrase(resume_text, requirement):
        return True
    for values in SKILL_SYNONYMS.values():
        if requirement in values:
            return any(JobMatchService._contains_phrase(resume_text, value) for value in values)
    return False
