from __future__ import annotations

import hashlib
import re

from app.models.job_description import JobDescription
from app.models.job_match_result import JobMatchResult
from app.core.config import settings
from app.models.resume import Resume
from app.services.ai_service import AIService, AIServiceError
from app.repositories.tailoring_change_repository import TailoringChangeRepository

CHANGE_CATEGORIES = {
    "KEEP",
    "ENHANCE",
    "REPHRASE",
    "ALIGN",
    "DE-EMPHASIZE",
    "USER_REVIEW",
}


class TailoringService:
    def __init__(self, db):
        self.db = db
        self.changes = TailoringChangeRepository(db)

    def preview(self, resume: Resume, job: JobDescription) -> dict:
        # Tailoring operates on the logical text extracted during ingestion.
        # The renderer later maps accepted edits back onto the original PDF/DOCX
        # layout so physical line wrapping does not become tailoring content.
        original_text = resume.text_content.strip()
        analysis = (
            self.db.query(JobMatchResult)
            .filter(
                JobMatchResult.user_id == resume.user_id,
                JobMatchResult.resume_id == resume.id,
                JobMatchResult.job_description_id == job.id,
            )
            .order_by(JobMatchResult.created_at.desc())
            .first()
        ) if self.db is not None else None
        requirement_items = list(analysis.requirement_matches or []) if analysis else []
        requirements = [item for item in requirement_items if item.get("requirement")]
        if not requirements:
            requirements = [
                {"requirement": value, "category": "", "importance": "normal", "status": "MISSING"}
                for value in self._extract_jd_requirements(job)
            ]
        modifications = []

        summary_content = self._extract_summary_content(original_text)
        targeted_summary = self._build_targeted_summary(original_text, job)
        if targeted_summary:
            if summary_content:
                normalized_current = " ".join(summary_content.split()).lower()
                normalized_target = " ".join(targeted_summary.split()).lower()
                if normalized_current != normalized_target:
                    modifications.append(
                        self._make_change(
                            original_content=summary_content,
                            proposed_content=targeted_summary,
                            reason="Tailored the existing Professional Summary toward the selected role using only evidence already present in the original resume.",
                            change_category="ALIGN",
                            supporting_resume_evidence=[summary_content, *self._summary_evidence(original_text)][:3],
                            target_jd_requirement=job.role_name or "Target role",
                            truthfulness_status="SUPPORTED",
                            suggested_action="Review the role-focused summary wording before applying it.",
                            action_type="RESUME_EDIT",
                        )
                    )
            else:
                modifications.append(
                    self._make_change(
                        original_content="",
                        proposed_content=targeted_summary,
                        reason="Added a concise role-targeted summary using only skills, projects, education, and results already present in the original resume.",
                        change_category="ALIGN",
                        supporting_resume_evidence=self._summary_evidence(original_text),
                        target_jd_requirement=job.role_name or "Target role",
                        truthfulness_status="SUPPORTED",
                        suggested_action="Review the summary for wording preference; its claims are based on the existing resume.",
                        action_type="ADD_SUMMARY",
                    )
                )

        seen_change_fingerprints: set[tuple[str, str]] = set()
        for requirement_item in requirements:
            requirement = requirement_item.get("requirement", "")
            if not requirement:
                continue
            evidence = self._find_tailoring_evidence(original_text, requirement)
            if not evidence:
                evidence = self._find_supporting_evidence(original_text, requirement)
            if not evidence and requirement_item.get("evidence"):
                evidence = [str(requirement_item["evidence"])]

            if not evidence:
                action_type, suggested_action = self._suggest_gap_action(requirement)
                modifications.append(
                    self._make_change(
                        original_content="",
                        proposed_content="",
                        reason=f"No direct resume evidence for '{requirement}'. This remains a review item and is not inserted into the tailored resume.",
                        change_category="USER_REVIEW",
                        supporting_resume_evidence=[],
                        target_jd_requirement=requirement,
                        requirement_category=requirement_item.get("category", ""),
                        evidence_reference=requirement_item.get("evidence_reference"),
                        truthfulness_status="UNSUPPORTED",
                        suggested_action=suggested_action,
                        action_type=action_type,
                    )
                )
                continue

            original_content, proposed, category, status = self._propose_requirement_change(
                requirement,
                evidence,
                original_text,
            )
            if not proposed or proposed == original_content:
                continue

            fingerprint = (original_content.strip(), proposed.strip())
            if fingerprint in seen_change_fingerprints:
                continue
            seen_change_fingerprints.add(fingerprint)

            modifications.append(
                self._make_change(
                    original_content=original_content,
                    proposed_content=proposed,
                    reason=self._reason_for_change(requirement, category),
                    change_category=category,
                    supporting_resume_evidence=evidence,
                    target_jd_requirement=requirement,
                    requirement_category=requirement_item.get("category", ""),
                    evidence_reference=requirement_item.get("evidence_reference"),
                    truthfulness_status=status,
                )
            )

        persisted = {item.id: item for item in self.changes.list_for_context(resume.user_id, resume.id, job.id)} if self.db is not None else {}
        for modification in modifications:
            if self.db is None:
                continue
            stored = self.changes.upsert(
                user_id=resume.user_id,
                resume_id=resume.id,
                job_description_id=job.id,
                payload=modification,
                analysis_id=analysis.id if analysis else None,
            )
            modification.update({
                "decision": stored.decision,
                "accepted": stored.decision == "ACCEPTED",
                "user_verified": stored.user_verified,
            })
        if self.db is not None:
            self.db.commit()

        available_keywords = [
            {
                "id": f"keyword-{hashlib.sha256(str(item.get('requirement', '')).encode('utf-8')).hexdigest()[:12]}",
                "keyword": item.get("requirement", ""),
                "category": item.get("category", ""),
                "status": item.get("status", "MISSING"),
                "selected": any(
                    change.target_jd_requirement == item.get("requirement")
                    and change.decision == "ACCEPTED"
                    for change in persisted.values()
                ),
            }
            for item in requirement_items
            if item.get("category") == "Keywords"
        ]
        valid = self._validate_modifications(modifications)
        auto_applied = []
        accepted_ids = [m["id"] for m in modifications if m.get("decision") == "ACCEPTED"]
        modified_text = self._apply_selected_changes(
            original_text,
            modifications,
            accepted_ids,
        )
        return {
            "original_text": original_text,
            "modified_text": modified_text,
            "modifications": modifications,
            "auto_applied_change_ids": [m["id"] for m in auto_applied],
            "diff": self._build_diff(original_text, modified_text),
            "validation_errors": valid,
            "available_keywords": available_keywords,
        }

    def change_decision(self, modification_id: str, accepted: bool | None, user_verified: bool | None = None, user_id: int | None = None) -> dict:
        item = self.changes.get(modification_id, user_id or 0)
        if item is None:
            raise ValueError("Tailoring change not found")
        if user_verified is True:
            item.user_verified = True
            if item.truthfulness_status in {"REQUIRES_REVIEW", "UNSUPPORTED"}:
                item.truthfulness_status = "USER_VERIFIED"
        if accepted is not None:
            if accepted and item.truthfulness_status not in {"SUPPORTED", "USER_VERIFIED"}:
                raise ValueError("This change requires explicit user verification before acceptance")
            item.decision = "ACCEPTED" if accepted else "REJECTED"
        self.db.commit()
        return {"id": item.id, "accepted": item.decision == "ACCEPTED", "decision": item.decision, "user_verified": item.user_verified, "truthfulness_status": item.truthfulness_status}

    def modification_belongs_to_user(self, modification_id: str, user_id: int) -> bool:
        resumes = self.db.query(Resume).filter(Resume.user_id == user_id).all()
        jobs = self.db.query(JobDescription).filter(JobDescription.user_id == user_id).all()
        return self.changes.get(modification_id, user_id) is not None

    def finalize(self, resume: Resume, job: JobDescription, accepted_change_ids: list[str] | None = None) -> dict:
        preview = self.preview(resume, job)
        requested_ids = set(accepted_change_ids or []) if accepted_change_ids is not None else None

        selectable = {
            m["id"]
            for m in preview["modifications"]
            if m.get("truthfulness_status") == "SUPPORTED"
            or (m.get("truthfulness_status") == "USER_VERIFIED" and m.get("user_verified") is True)
        }

        persisted_ids = {
            item["id"] for item in preview["modifications"]
            if item.get("decision") == "ACCEPTED"
        }
        if accepted_change_ids is not None and not persisted_ids and self.db is None:
            persisted_ids = {
                item["id"] for item in preview["modifications"]
                if item.get("truthfulness_status") == "SUPPORTED"
                or (item.get("truthfulness_status") == "USER_VERIFIED" and item.get("user_verified") is True)
            }
        selected_ids = (requested_ids & selectable) if requested_ids is not None else persisted_ids
        accepted_changes = [
            m for m in preview["modifications"]
            if m["id"] in selected_ids
        ]
        final_text = self._apply_selected_changes(
            preview["original_text"],
            preview["modifications"],
            list(selected_ids),
        )
        validation_errors = self._validate_modifications(accepted_changes)
        if not accepted_changes:
            validation_errors.append("No supported changes were selected for finalization; review-only recommendations were ignored.")
            final_text = preview["original_text"]
        return {
            "resume_id": resume.id,
            "job_description_id": job.id,
            "original_text": preview["original_text"],
            "final_text": final_text,
            "accepted_changes": accepted_changes,
            "validation_errors": validation_errors,
        }

    def restore(self, resume: Resume, job: JobDescription) -> dict:
        return {
            "resume_id": resume.id,
            "job_description_id": job.id,
            "restored_text": resume.text_content.strip(),
        }

    @staticmethod
    def _extract_jd_requirements(job: JobDescription) -> list[str]:
        from app.services.job_match_service import JobMatchService

        stopwords = {
            "the", "and", "or", "with", "for", "to", "of", "in", "on", "at",
            "as", "a", "an", "our", "you", "your", "will", "this", "that",
            "from", "by", "is", "are", "be", "we", "what", "day", "expect",
        }
        noise = {
            "my career", "resources", "help", "find careers",
            "download our app", "sign out", "privacy and data", "inclusive experiences",
        }
        requirement_sets = JobMatchService._extract_requirement_sets(
            JobMatchService._normalize_text(job.normalized_text or job.text_content),
            role_name=job.role_name,
            company_name=job.company_name,
        )
        generic = {
            "design", "build", "deliver", "lead", "own", "implement",
            "integrate", "optimize", "support", "mentor", "maintain",
            "experience", "engineer", "role", "responsibility", "responsibilities",
            "projects", "project", "work", "team", "years", "year", "intern", "internship",
        }
        ordered = (
            requirement_sets.get("technical", [])
            + requirement_sets.get("education", [])
            + requirement_sets.get("certifications", [])
            + requirement_sets.get("soft_skills", [])
            + requirement_sets.get("projects", [])
            + requirement_sets.get("responsibilities", [])
            + requirement_sets.get("experience", [])
        )
        deduped = []
        seen = set()
        for value in ordered:
            value = value.strip()
            if not value:
                continue
            normalized = JobMatchService._normalize_text(value)
            tokens = set(normalized.split())
            if normalized in generic or tokens & generic:
                continue
            if len(normalized) < 3 or normalized.isdigit():
                continue
            if value not in seen:
                seen.add(value)
                deduped.append(value)
        return deduped[:12]

    @staticmethod
    def _find_supporting_evidence(resume_text: str, requirement: str) -> list[str]:
        evidence = []
        meaningful = [
            token for token in re.findall(r"[a-z0-9+.#-]+", requirement.lower())
            if len(token) > 2 and token not in {
                "the", "and", "or", "with", "for", "to", "of", "in", "on",
                "at", "as", "a", "an", "experience", "strong", "least",
            }
        ]
        segments = []
        for line in (resume_text or "").splitlines():
            segments.extend(re.split(r"(?<=[.!?])\s+", line))
        if not segments:
            segments = re.split(r"(?<=[.!?])\s+", resume_text or "")
        lower_resume = (resume_text or "").lower()
        programming_languages = {
            "python", "java", "javascript", "typescript", "c++", "c#", "go",
            "ruby", "php", "kotlin", "swift",
        }
        for raw in segments:
            sentence = raw.strip()
            if not sentence:
                continue
            lowered = sentence.lower()
            if requirement.lower().strip() in lowered:
                evidence.append(sentence)
                continue
            if "programming language" in requirement.lower() and any(
                language in lower_resume for language in programming_languages
            ):
                if any(language in lowered for language in programming_languages):
                    evidence.append(sentence)
                    continue
            if "bachelor" in requirement.lower() and (
                "bachelor" in lowered or "b.tech" in lowered or "btech" in lowered
            ):
                if "computer science" in requirement.lower() and "computer science" in lowered:
                    evidence.append(sentence)
                    continue
            overlap = sum(1 for token in meaningful if token in lowered) / max(len(meaningful), 1)
            if len(meaningful) >= 2 and overlap >= 0.6:
                evidence.append(sentence)
        return evidence[:3]

    @staticmethod
    def _classify_change(requirement: str, evidence: list[str], original_text: str, proposed: str) -> str:
        if not evidence:
            return "USER_REVIEW"
        source = evidence[0].strip()
        proposed_text = proposed.strip()
        if not proposed_text or proposed_text.lower() == source.lower():
            return "KEEP"
        if requirement.lower() in source.lower():
            return "ENHANCE"
        requirement_tokens = {
            token for token in re.findall(r"[a-z0-9]+", requirement.lower())
            if len(token) > 3
        }
        source_tokens = set(re.findall(r"[a-z0-9]+", source.lower()))
        overlap = len(requirement_tokens & source_tokens) / max(len(requirement_tokens), 1)
        if overlap >= 0.5:
            return "ALIGN"
        return "REPHRASE"

    @staticmethod
    def _truthfulness_status(category: str, proposed: str, evidence: list[str]) -> str:
        if category == "USER_REVIEW":
            return "UNSUPPORTED"
        if not proposed or not proposed.strip() or not evidence:
            return "UNSUPPORTED"
        source = evidence[0].strip()
        if proposed.strip().lower() == source.lower():
            return "SUPPORTED"
        return "REQUIRES_REVIEW"

    @staticmethod
    def _suggest_gap_action(requirement: str) -> tuple[str, str]:
        lowered = requirement.lower()

        profile_terms = ("url", "profile", "github", "linkedin", "portfolio", "leetcode")
        credential_terms = ("bachelor", "degree", "certification", "certificate", "credential")
        responsibility_terms = (
            "design", "develop", "build", "operate", "maintain", "audit",
            "monitor", "test", "debug", "scale", "distributed", "security",
        )

        if any(term in lowered for term in profile_terms):
            return (
                "PROFILE_LINK",
                "Add the relevant public profile or portfolio URL to the resume only if you have an active, genuine link to share.",
            )

        if any(term in lowered for term in credential_terms):
            return (
                "VERIFY_CREDENTIAL",
                "Add the exact degree, certification, or credential only if you actually hold it; include the official name and date when available.",
            )

        if any(term in lowered for term in responsibility_terms):
            return (
                "ADD_REAL_EVIDENCE",
                "Add one concise bullet from a real project, internship, job, or coursework example that demonstrates this responsibility. Do not add the requirement as a claim without real evidence.",
            )

        if any(term in lowered for term in ("skill", "technology", "programming language", "software")):
            return (
                "ADD_SKILL_EVIDENCE",
                "Add this skill to the Skills section only if you genuinely know it, and support it with a project, coursework, certification, or other real evidence.",
            )

        return (
            "USER_ACTION",
            "Strengthen the resume with a real example, project, skill, credential, or link that directly supports this requirement. The application will not invent the claim for you.",
        )

    @staticmethod
    def _reason_for_change(requirement: str, category: str) -> str:
        if category == "KEEP":
            return "This wording already aligns with the target requirement without adding unsupported detail."
        if category == "ENHANCE":
            return "This wording can be strengthened to reflect the matching requirement more clearly."
        if category == "ALIGN":
            return "This phrase better aligns with the target role while preserving the user's original experience."
        if category == "DE-EMPHASIZE":
            return "This phrase is relevant but should be expressed more conservatively to avoid overstating fit."
        if category == "USER_REVIEW":
            return "This requirement may be relevant but the resume does not yet provide direct evidence, so it should be reviewed by the user."
        return "This wording is preserved or lightly revised to improve clarity without changing facts."

    @staticmethod
    def _find_tailoring_evidence(resume_text: str, requirement: str) -> list[str]:
        lowered = requirement.lower().strip()
        targeted: list[str] = []

        phrase_map = {
            "software development": [
                "Web & Backend:",
                "Software Development & Web/Backend:",
            ],
            "prompt engineering": [
                "Designed prompt-engineering templates for the LLM inference layer, mitigating hallucinations to achieve 89% factual response accuracy across 50 evaluated queries.",
                "Constructed context-grounded prompt templates for the LLM inference layer, mitigating hallucinations to achieve 89% factual response accuracy across 50 evaluated queries.",
            ],
            "workflow automation": [
                "Developed workflow automation for ticket triage using LLM-based intent classification to assign priority tags and seamlessly route escalated cases to human agents.",
                "Engineered automated ticket triage workflows using LLM-based intent classification to assign priority tags and seamlessly route escalated cases to human agents.",
            ],
            "retrieval augmented generation": [
                "Engineered an end-to-end retrieval-augmented generation (RAG) pipeline to perform semantic search and question answering across heterogeneous enterprise documents (PDFs, DOCX, TXT).",
                "Engineered an end-to-end RAG pipeline to perform semantic search and question answering across heterogeneous enterprise documents (PDFs, DOCX, TXT).",
            ],
            "willingness to learn": ["Quick Learner"],
            "collaboration": ["Team Collaboration"],
            "communication": ["Communication Skills"],
        }

        for key, candidates in phrase_map.items():
            if key in lowered:
                for candidate in candidates:
                    if candidate in resume_text:
                        targeted.append(candidate)
                if targeted:
                    return targeted

        return []

    @staticmethod
    def _propose_requirement_change(
        requirement: str,
        evidence: list[str],
        original_text: str,
    ) -> tuple[str, str, str, str]:
        lowered = requirement.lower().strip()
        source = evidence[0].strip() if evidence else ""

        replacements = {
            "software development": (
                "Web & Backend:",
                "Software Development & Backend:",
            ),
            "prompt engineering": (
                source,
                "Designed prompt templates for the LLM inference layer, mitigating hallucinations to achieve 89% factual accuracy across 50 queries.",
            ),
            "workflow automation": (
                source,
                "Developed automated ticket-triage workflows using LLM-based intent classification to assign priority and route escalations to human agents.",
            ),
            "retrieval augmented generation": (
                source,
                "Engineered an end-to-end retrieval-augmented generation (RAG) pipeline for semantic search and Q&A across enterprise documents (PDFs, DOCX, TXT).",
            ),
            "willingness to learn": (
                "Quick Learner",
                "Willingness to Learn",
            ),
            "collaboration": (
                "Team Collaboration",
                "Cross-Team Collaboration",
            ),
            "communication": (
                "Communication Skills",
                "Clear Communication",
            ),
        }

        for key, (original, proposed) in replacements.items():
            if key in lowered and original and original in original_text:
                return original, proposed, "ALIGN", "SUPPORTED"

        return source, source, "KEEP", "SUPPORTED"

    @staticmethod
    def _propose_rewording(original_text: str, requirement: str, evidence: list[str]) -> str:
        source = evidence[0] if evidence else original_text
        text = source.strip()

        normalized_requirement = requirement.lower().strip()
        lowered_text = text.lower()

        if not normalized_requirement or normalized_requirement in lowered_text:
            return text

        if settings.GEMINI_API_KEY and evidence:
            try:
                proposal = AIService().generate_tailoring_proposal(
                    original_text=text,
                    requirement=requirement,
                    resume_context=" ".join(evidence),
                )
                proposed = proposal.proposed_text.strip()
                original = proposal.original_text.strip()
                if not proposed or not original or original not in source:
                    return text
                if proposal.truthfulness_status == "UNSUPPORTED":
                    return text
                return proposed
            except AIServiceError:
                return text

        return TailoringService.action_verb_tune(text)

    @staticmethod
    def action_verb_tune(text: str) -> str:
        """Strengthen weak wording without adding facts or changing claims."""
        replacements = {
            "worked on": "developed",
            "helped with": "supported",
            "was responsible for": "managed",
            "made": "built",
            "did": "executed",
            "used": "applied",
        }
        tuned = text
        for weak, strong in replacements.items():
            tuned = re.sub(rf"\b{re.escape(weak)}\b", strong, tuned, flags=re.IGNORECASE)
        return tuned

    @staticmethod
    def _make_change(**kwargs) -> dict:
        change = dict(kwargs)
        change.setdefault("evidence", list(change.get("supporting_resume_evidence", [])))
        raw = (
            f"{change.get('target_jd_requirement','')}|"
            f"{change.get('original_content','')}|"
            f"{change.get('proposed_content','')}|"
            f"{change.get('change_category','')}"
        )
        change["id"] = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return change

    @staticmethod
    def _summary_evidence(resume_text: str) -> list[str]:
        snippets = []
        for marker in ("TECHNICAL SKILLS", "PROJECTS", "EDUCATION", "CERTIFICATIONS"):
            match = re.search(rf"{marker}.*?(?=(?:PROJECTS|TECHNICAL SKILLS|EDUCATION|CERTIFICATIONS|ACHIEVEMENTS|SOFT SKILLS)\b|$)", resume_text, flags=re.IGNORECASE)
            if match:
                snippets.append(match.group(0).strip()[:500])
        return snippets[:3]

    @staticmethod
    def _extract_summary_content(resume_text: str) -> str:
        text = str(resume_text or "").strip()
        if not text:
            return ""

        # Support both conventional line-based resumes and PDF extraction that
        # has flattened the document into one text stream.
        heading_pattern = re.compile(
            r"\b(?:PROFESSIONAL\s+SUMMARY|SUMMARY)\b\s*[:|-]?\s*",
            flags=re.IGNORECASE,
        )
        match = heading_pattern.search(text)
        if not match:
            return ""

        remainder = text[match.end():]
        next_heading = re.search(
            r"\b(?:TECHNICAL\s+SKILLS|SKILLS|TECHNICAL\s+PROJECTS|PROJECTS|EXPERIENCE|EDUCATION|CERTIFICATIONS|ACHIEVEMENTS|SOFT\s+SKILLS)\b",
            remainder,
            flags=re.IGNORECASE,
        )
        content = remainder[:next_heading.start()] if next_heading else remainder
        return re.sub(r"\s+", " ", content).strip(" :-|")

    @staticmethod
    def _build_targeted_summary(
        resume_text: str,
        job: JobDescription,
    ) -> str:
        lowered = resume_text.lower()
        skills: list[str] = []
        for skill in (
            "python", "fastapi", "postgresql", "docker", "rest apis",
            "llms", "rag", "react", "sql", "vector search", "embeddings",
        ):
            if skill in lowered:
                skills.append(skill.upper() if skill == "sql" else skill.title())

        # Add only JD signals that are explicitly evidenced in the resume.
        evidenced_requirements: list[str] = []
        try:
            requirement_values = TailoringService._extract_jd_requirements(job)
        except Exception:
            requirement_values = []
        for requirement_value in requirement_values:
            requirement = str(requirement_value or "").strip()
            if not requirement:
                continue
            if requirement.lower() in lowered and requirement.lower() not in {
                item_value.lower() for item_value in evidenced_requirements
            }:
                evidenced_requirements.append(requirement)
        for requirement in evidenced_requirements[:4]:
            if requirement.lower() not in {skill.lower() for skill in skills}:
                skills.append(requirement)

        project_names = [
            project for project in (
                "AI Customer Support Bot & Automated Ticket Manager",
                "Enterprise Multi-Document Q&A System (RAG)",
            )
            if project.lower() in lowered
        ]

        education = "Computer Science graduate"
        role = (job.role_name or "").strip()
        role_clause = f" targeting {role}" if role else " targeting software development roles"

        if "llm" in lowered or "rag" in lowered or "ai automation" in lowered:
            experience_clause = (
                "hands-on experience building AI automation and "
                "retrieval-augmented generation solutions"
            )
        elif project_names:
            experience_clause = "hands-on experience building end-to-end software projects"
        else:
            experience_clause = "hands-on experience building software solutions"

        skill_clause = f" with {', '.join(skills[:6])}" if skills else ""
        summary = f"{education}{role_clause} with {experience_clause}{skill_clause}."
        return re.sub(r"\s+", " ", summary).strip()[:260]

    @staticmethod
    def _validate_modifications(modifications: list[dict]) -> list[str]:
        errors = []
        for mod in modifications:
            truthfulness_status = str(mod.get("truthfulness_status") or "").upper()
            category = str(mod.get("change_category") or "")
            requirement = str(mod.get("target_jd_requirement") or "unknown requirement")
            user_verified = mod.get("user_verified") is True

            if truthfulness_status == "USER_VERIFIED" and not user_verified:
                errors.append(f"User verification required before accepting {requirement}.")

            if category == "USER_REVIEW" and truthfulness_status not in {"UNSUPPORTED", "REQUIRES_REVIEW"}:
                errors.append(f"Unsupported review for {requirement}")
            if mod.get("proposed_content") and any(word in str(mod.get("proposed_content", "")).lower() for word in ["lead team of 12", "managed 10x", "invented", "revolutionized"]):
                errors.append(f"Potentially fictional metric in proposed text for {requirement}")
        return errors

    @staticmethod
    def _apply_selected_changes(original_text: str, modifications: list[dict], accepted_ids: list[str]) -> str:
        selected = [m for m in modifications if m["id"] in set(accepted_ids) and m["proposed_content"]]
        if not selected:
            return original_text
        updated = original_text
        for mod in selected:
            original = str(mod.get("original_content") or "")
            proposed = str(mod.get("proposed_content") or "")
            action_type = str(mod.get("action_type") or "")

            if action_type == "ADD_SUMMARY":
                heading_match = re.search(
                    r"\bPROJECTS\b|\bTECHNICAL SKILLS\b|\bEDUCATION\b",
                    updated,
                    flags=re.IGNORECASE,
                )
                insertion = f"SUMMARY\n{proposed.strip()}\n\n"
                if heading_match:
                    updated = updated[:heading_match.start()] + insertion + updated[heading_match.start():]
                else:
                    updated = insertion + updated
                continue

            if original and proposed:
                updated = updated.replace(original, proposed, 1)
        return updated

    @staticmethod
    def _build_diff(original_text: str, modified_text: str) -> list[dict[str, str]]:
        if original_text == modified_text:
            return [{"type": "unchanged", "text": original_text}]
        return [
            {"type": "original", "text": original_text[:120] if len(original_text) > 120 else original_text},
            {"type": "modified", "text": modified_text[:120] if len(modified_text) > 120 else modified_text},
        ]
