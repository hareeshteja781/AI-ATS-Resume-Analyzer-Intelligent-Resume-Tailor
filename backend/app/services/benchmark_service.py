from __future__ import annotations

import re
from collections import Counter
from typing import Any


ROLE_FAMILIES = {
    "backend engineer": "backend engineering",
    "backend developer": "backend engineering",
    "software engineer": "software engineering",
    "software developer": "software engineering",
    "frontend engineer": "frontend engineering",
    "frontend developer": "frontend engineering",
    "data engineer": "data engineering",
    "data scientist": "data science",
    "machine learning engineer": "machine learning engineering",
    "devops engineer": "devops engineering",
    "product manager": "product management",
}

SIGNALS = {
    "technical_skills": ("python", "java", "javascript", "typescript", "fastapi", "django", "react", "node.js", "sql", "postgresql", "mysql", "mongodb", "redis", "docker", "kubernetes", "aws", "azure", "gcp", "terraform", "graphql", "rest api", "microservices", "machine learning", "pandas", "spark"),
    "responsibilities": ("design", "develop", "build", "maintain", "operate", "test", "monitor", "deploy", "lead", "mentor", "analyze", "plan", "scale"),
    "qualifications": ("bachelor", "master", "degree", "certification", "years of experience"),
}


class BenchmarkService:
    """Compare role-labeled historical JDs without presenting them as market statistics."""

    @staticmethod
    def normalize_role(role_name: str | None) -> str | None:
        normalized = re.sub(r"[^a-z0-9]+", " ", (role_name or "").lower()).strip()
        if not normalized:
            return None
        if normalized in ROLE_FAMILIES:
            return ROLE_FAMILIES[normalized]
        if "backend" in normalized and any(word in normalized for word in ("engineer", "developer")):
            return "backend engineering"
        if "frontend" in normalized and any(word in normalized for word in ("engineer", "developer")):
            return "frontend engineering"
        return normalized

    def summarize(self, jd_records: list[dict[str, Any]] | None, *, role_name: str | None = None, current_jd_text: str = "", resume_text: str = "") -> dict[str, Any]:
        requested_family = self.normalize_role(role_name)
        records = [record for record in (jd_records or []) if isinstance(record, dict) and self.normalize_role(str(record.get("role_name") or "")) == requested_family]
        sample_size = len(records)
        sufficiency = "INSUFFICIENT" if sample_size < 2 else "LIMITED" if sample_size < 5 else "SUFFICIENT"
        result = {
            "role": role_name,
            "role_name": role_name,
            "normalized_role_family": requested_family,
            "data_sufficiency": sufficiency,
            "sample_size": sample_size,
            "source_type": "historical_user_job_descriptions",
            "source_count": sample_size,
            "limitations": ["This benchmark uses only stored role-labeled job descriptions available to this account; it is not a market-wide statistic."],
            "common_skills": [], "common_responsibilities": [], "common_qualifications": [],
            "current_jd_comparison": {"signals_in_current_jd": [], "common_but_absent_from_current_jd": []},
            "resume_comparison": {"benchmark_common_and_present": [], "benchmark_common_but_not_evidenced": []},
            "summary": "Insufficient benchmark data: no reliable role-specific sample" if sufficiency == "INSUFFICIENT" else f"{sufficiency.title()} role-specific context from {sample_size} stored JD records.",
            "insufficient_data": sufficiency == "INSUFFICIENT",
        }
        if not requested_family or not records:
            return result
        counters = {category: Counter() for category in SIGNALS}
        for record in records:
            text = str(record.get("text") or record.get("normalized_text") or "")
            for category, signals in SIGNALS.items():
                for signal in signals:
                    if self._contains(text, signal):
                        counters[category][signal] += 1
        common = {category: [{"item": item, "count": count, "frequency": round(count / sample_size, 3)} for item, count in counter.most_common(20) if count >= 2] for category, counter in counters.items()}
        result["common_skills"] = common["technical_skills"]
        result["common_responsibilities"] = common["responsibilities"]
        result["common_qualifications"] = common["qualifications"]
        common_items = [item["item"] for values in common.values() for item in values]
        current_signals = set(self._signals(current_jd_text))
        result["current_jd_comparison"] = {"signals_in_current_jd": sorted(current_signals), "common_but_absent_from_current_jd": sorted(set(common_items) - current_signals)}
        resume_signals = set(self._signals(resume_text))
        result["resume_comparison"] = {"benchmark_common_and_present": sorted(set(common_items) & resume_signals), "benchmark_common_but_not_evidenced": sorted(set(common_items) - resume_signals)}
        return result

    @staticmethod
    def _contains(text: str, signal: str) -> bool:
        pattern = r"(?<![a-z0-9])" + re.escape(signal.lower()).replace(r"\ ", r"\s+") + r"(?![a-z0-9])"
        return bool(re.search(pattern, text.lower()))

    @classmethod
    def _signals(cls, text: str) -> list[str]:
        return [signal for signals in SIGNALS.values() for signal in signals if cls._contains(text, signal)]
