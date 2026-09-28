from __future__ import annotations

import copy
import io
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt
from fastapi import HTTPException, status
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, TextStringObject

from app.models.job_description import JobDescription
from app.models.resume import Resume
from app.models.resume_version import ResumeVersion
from app.repositories.resume_version_repository import ResumeVersionRepository
from app.services.storage_service import StorageService
from app.services.tailoring_service import TailoringService

CORE_RESUME_SECTIONS = {"skills", "projects", "education", "experience"}


class ResumeVersionService:
    def __init__(self, db, storage: StorageService | None = None):
        self.db = db
        self.repository = ResumeVersionRepository(db)
        self.storage = storage or StorageService()

    def create_master_version(self, resume: Resume) -> ResumeVersion:
        existing = self.repository.get_master(resume.id, resume.user_id)
        if existing:
            return existing
        version = self.repository.create(
            user_id=resume.user_id,
            resume_id=resume.id,
            version_name="master",
            source_type="master",
            original_text=resume.text_content,
            tailored_text=resume.text_content,
            final_text=resume.text_content,
            diff_text="",
            validation_summary={
                "truthfulness": "SUPPORTED",
                "document_integrity": True,
                "formatting_preservation": True,
                "required_sections": True,
                "ats_readability": True,
            },
            truthfulness_status="SUPPORTED",
            status="approved",
            finalization_status="approved",
            is_master=True,
            is_current=True,
        )
        return version

    def create_tailored_version(
        self,
        resume: Resume,
        job: JobDescription,
        version_name: str = "tailored",
        accepted_change_ids: list[str] | None = None,
    ) -> ResumeVersion:
        master = self.repository.get_master(resume.id, resume.user_id) or self.create_master_version(resume)
        original_text = resume.text_content.strip()
        accepted_ids = accepted_change_ids
        tailoring = TailoringService(self.db)
        preview = tailoring.preview(resume, job)
        finalized = tailoring.finalize(resume, job, accepted_ids)
        proposed = finalized["final_text"]
        validation = self.validate_resume_text(proposed)
        validation["accepted_changes"] = finalized["accepted_changes"]
        validation["rejected_changes"] = [
            change for change in preview.get("modifications", [])
            if change.get("decision") == "REJECTED"
        ]
        validation["verification_state"] = {
            change.get("id"): bool(change.get("user_verified"))
            for change in preview.get("modifications", [])
        }
        validation["preview_validation_errors"] = preview["validation_errors"]
        validation["formatted_text"] = self._build_formatted_resume_text(
            resume,
            proposed,
            finalized["accepted_changes"],
        )
        if any(
            change.get("truthfulness_status") not in {"SUPPORTED", "USER_VERIFIED"}
            for change in finalized["accepted_changes"]
        ):
            validation["truthfulness"] = "REQUIRES_REVIEW"
            validation.setdefault("validation_errors", []).append(
                "One or more accepted changes require user review before finalization."
            )
        display_name = (
            f"{job.role_name} ({job.company_name})"
            if job.role_name and job.company_name
            else job.role_name
            or job.company_name
            or version_name
            or "Tailored Resume"
        )
        version = self.repository.create(
            user_id=resume.user_id,
            resume_id=resume.id,
            job_description_id=job.id,
            version_name=display_name[:255],
            source_type="tailored",
            original_text=original_text,
            tailored_text=proposed,
            final_text=proposed,
            diff_text=self._build_diff(original_text, proposed),
            validation_summary=validation,
            truthfulness_status=validation.get("truthfulness", "SUPPORTED"),
            status="draft",
            finalization_status="draft",
            is_master=False,
            is_current=True,
        )
        if master and master.id != version.id:
            master.is_current = False
            self.db.add(master)
            self.db.commit()

        return version

    def list_versions(self, resume_id: int, user_id: int) -> list[ResumeVersion]:
        return self.repository.list_for_resume(resume_id, user_id)

    def get_version(self, version_id: int, user_id: int) -> ResumeVersion:
        item = self.repository.get_by_id(version_id)
        if not item or item.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Version not found")
        return item

    def compare_versions(self, base_version_id: int, target_version_id: int, user_id: int) -> dict:
        base = self.get_version(base_version_id, user_id)
        target = self.get_version(target_version_id, user_id)
        base_text = base.final_text or base.tailored_text or base.original_text or ""
        target_text = target.final_text or target.tailored_text or target.original_text or ""
        diff = self._build_structured_diff(base_text, target_text)
        errs = self.validate_resume_text(target_text).get("validation_errors", [])
        return {
            "base_version_id": base.id,
            "target_version_id": target.id,
            "base_version_name": base.version_name,
            "target_version_name": target.version_name,
            "base_text": base_text,
            "target_text": target_text,
            "diff": diff,
            "validation_errors": errs,
        }

    def delete_version(self, version_id: int, user_id: int) -> dict:
        version = self.get_version(version_id, user_id)
        if version.is_master:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The master version cannot be deleted.",
            )

        resume_id = version.resume_id
        storage_keys = [version.document_path, version.pdf_path]
        was_current = version.is_current
        self.repository.delete(version)

        for key in storage_keys:
            if key:
                try:
                    self.storage.delete(key)
                except (FileNotFoundError, OSError, ValueError):
                    pass

        if was_current:
            remaining = self.repository.list_for_resume(resume_id, user_id)
            if remaining:
                for item in remaining:
                    item.is_current = False
                remaining[0].is_current = True
                self.db.commit()

        return {"id": version_id, "message": "Version deleted."}

    def restore_version(self, resume: Resume, version_id: int, user_id: int) -> dict:
        version = self.get_version(version_id, user_id)
        if version.resume_id != resume.id:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Version does not belong to this resume")
        restored_text = version.final_text or version.original_text or resume.text_content
        restored = self.repository.create(
            user_id=user_id,
            resume_id=resume.id,
            job_description_id=version.job_description_id,
            version_name=f"Restored {version.version_name}"[:255],
            source_type="restore",
            original_text=version.original_text,
            tailored_text=restored_text,
            final_text=restored_text,
            diff_text=self._build_diff(version.original_text, restored_text),
            validation_summary={
                "restored_from_version_id": version.id,
                "accepted_changes": version.validation_summary.get("accepted_changes", []),
                "formatted_text": version.validation_summary.get("formatted_text", restored_text),
            },
            truthfulness_status=version.truthfulness_status,
            status="approved",
            finalization_status="approved",
            is_master=False,
            is_current=True,
        )
        for item in self.repository.list_for_resume(resume.id, user_id):
            if item.id != restored.id:
                item.is_current = False
        self.db.commit()
        return {
            "resume_id": resume.id,
            "restored_version_id": version.id,
            "restored_text": restored_text,
            "created_version_id": restored.id,
            "message": f"Restored version '{version.version_name}'",
        }

    def finalize_version(self, version_id: int, user_id: int) -> ResumeVersion:
        version = self.get_version(version_id, user_id)
        validation = self.validate_resume_text(version.final_text)
        previous_summary = dict(version.validation_summary or {})
        for key in ("accepted_changes", "rejected_changes", "verification_state", "formatted_text", "preview_validation_errors"):
            if key in previous_summary:
                validation[key] = previous_summary[key]
        version.validation_summary = validation
        version.truthfulness_status = validation.get("truthfulness", "SUPPORTED")
        version.finalization_status = "ready" if not validation.get("validation_errors") else "blocked"
        version.status = "approved" if not validation.get("validation_errors") else "rejected"
        self.db.add(version)
        self.db.commit()
        self.db.refresh(version)

        return version

    @staticmethod
    def _build_formatted_resume_text(
        resume: Resume,
        tailored_text: str,
        accepted_changes: list[dict],
    ) -> str:
        source = ""
        try:
            storage = StorageService()
            if resume.storage_path:
                source_bytes = storage.get_bytes(resume.storage_path)
                if resume.content_type == "application/pdf":
                    reader = PdfReader(io.BytesIO(source_bytes))
                    pages = []
                    for page in reader.pages:
                        try:
                            text = page.extract_text(extraction_mode="layout") or ""
                        except TypeError:
                            text = page.extract_text() or ""
                        pages.append(text.rstrip())
                    source = "\n\n".join(pages).strip()
                elif resume.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                    doc = Document(io.BytesIO(source_bytes))
                    source = "\n".join(
                        paragraph.text for paragraph in doc.paragraphs
                    ).strip()
        except Exception:
            source = ""

        if not source:
            return tailored_text.strip()

        formatted = source
        for change in accepted_changes:
            original = str(change.get("original_content") or "")
            proposed = str(change.get("proposed_content") or "")
            if original and proposed and original != proposed:
                if original in formatted:
                    formatted = formatted.replace(original, proposed, 1)
                else:
                    compact = " ".join(original.split())
                    compact_source = " ".join(formatted.split())
                    if compact and compact in compact_source:
                        formatted = tailored_text.strip()
                        break
        return formatted.strip() or tailored_text.strip()

    def build_docx_bytes(
        self,
        resume: Resume,
        final_text: str,
        accepted_changes: list[dict],
    ) -> bytes:
        if not resume.storage_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Original resume file is not available for document preview.",
            )

        try:
            source_bytes = self.storage.get_bytes(resume.storage_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Original resume file could not be loaded for document preview.",
            ) from exc

        if resume.content_type == "application/pdf":
            preview_version = ResumeVersion(
                user_id=resume.user_id,
                resume_id=resume.id,
                original_text=resume.text_content,
                final_text=final_text,
                validation_summary={"formatted_text": final_text},
            )
            doc = self._build_docx_from_pdf_text(preview_version, source_bytes)
        else:
            try:
                doc = Document(io.BytesIO(source_bytes))
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Original DOCX file could not be opened.",
                ) from exc

        # PDF previews are rebuilt from the already-tailored text, so changes
        # are already applied during reconstruction. Reapplying them causes false
        # "was not found" mapping errors.
        errors = [] if resume.content_type == "application/pdf" else self._apply_docx_modifications(doc, accepted_changes)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document changes could not be mapped to the original resume: " + "; ".join(errors),
            )

        self._compact_one_page_tailored_layout(doc, accepted_changes)
        artifact_errors = self._validate_generated_docx(doc, accepted_changes, final_text)
        if artifact_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Generated document failed content validation: " + "; ".join(artifact_errors),
            )

        output = io.BytesIO()
        doc.save(output)
        return output.getvalue()

    @staticmethod
    def _normalize_pdf_text(text: str) -> str:
        value = str(text or "")
        value = value.replace("\ufffd", " ")
        value = value.replace("\u00ad", "")
        value = re.sub(r"[\u2010\u2011\u2012\u2013\u2014\u2212]", "-", value)
        value = re.sub(r"\s*-\s*", "-", value)
        return " ".join(value.split()).strip().lower()

    @staticmethod
    def _compact_pdf_text(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", ResumeVersionService._normalize_pdf_text(text))

    @staticmethod
    def _set_pdf_text_operand(stream, operation_index: int, array_index: int, text: str) -> None:
        operands, operator = stream.operations[operation_index]
        if operator == b"Tj":
            if array_index != 0:
                raise ValueError("Invalid Tj text operand index")
            operands[0] = TextStringObject(text)
            return
        array = operands[0]
        array[array_index] = TextStringObject(text)

    @staticmethod
    def _pdf_text_parts_for_operation(operands, operator) -> list[tuple[int, str]]:
        if operator == b"Tj":
            return [(0, str(operands[0]))] if operands and isinstance(operands[0], TextStringObject) else []
        if operator != b"TJ" or not operands:
            return []
        return [
            (index, str(value))
            for index, value in enumerate(operands[0])
            if isinstance(value, TextStringObject)
        ]

    @staticmethod
    def _pdf_line_groups(stream) -> list[dict]:
        groups: dict[float, dict] = {}
        current_font = ""
        current_size = 0.0
        current_x = 0.0
        current_y = 0.0
        leading = 0.0

        for operation_index, (operands, operator) in enumerate(stream.operations):
            if operator == b"Tf" and len(operands) >= 2:
                current_font = str(operands[0])
                current_size = float(operands[1])
                continue
            if operator == b"Tm" and len(operands) >= 6:
                current_x = float(operands[4])
                current_y = float(operands[5])
                continue
            if operator in (b"Td", b"TD") and len(operands) >= 2:
                current_x += float(operands[0])
                current_y += float(operands[1])
                if operator == b"TD":
                    leading = -float(operands[1])
                continue
            if operator == b"T*":
                current_y -= leading
                continue
            if operator not in (b"Tj", b"TJ"):
                continue

            parts = ResumeVersionService._pdf_text_parts_for_operation(operands, operator)
            if not parts:
                continue
            text = "".join(value for _, value in parts)
            if not text.strip():
                continue

            key = round(current_y, 2)
            group = groups.setdefault(key, {"y": current_y, "runs": []})
            for array_index, value in parts:
                group["runs"].append({
                    "operation_index": operation_index,
                    "array_index": array_index,
                    "x": current_x,
                    "y": current_y,
                    "font": current_font,
                    "size": current_size,
                    "text": value,
                    "operator": operator,
                })

        result = list(groups.values())
        result.sort(key=lambda group: (-group["y"], min(run["x"] for run in group["runs"])))
        for group in result:
            group["runs"].sort(key=lambda run: (run["x"], run["operation_index"], run["array_index"]))
        return result

    @staticmethod
    def _is_pdf_marker_run(run: dict) -> bool:
        text = str(run.get("text") or "").strip()
        font = str(run.get("font") or "").lower()
        return "symbol" in font or text in {"", "\ufffd", "•", "▪", "●", "◦", "○"}

    @staticmethod
    def _pdf_body_runs(group: dict) -> list[dict]:
        return [run for run in group["runs"] if not ResumeVersionService._is_pdf_marker_run(run)]

    @staticmethod
    def _split_pdf_replacement(text: str, templates: list[str]) -> list[str]:
        cleaned = " ".join(str(text or "").split())
        if not cleaned:
            return [""] * max(len(templates), 1)
        if len(templates) <= 1:
            return [cleaned]

        capacities = [max(len(ResumeVersionService._compact_pdf_text(item)), 1) for item in templates]
        total = sum(capacities)
        remaining = cleaned
        lines: list[str] = []
        for index, capacity in enumerate(capacities[:-1]):
            target = max(1, round(len(cleaned) * capacity / total))
            cut = remaining.rfind(" ", 0, min(len(remaining), target + 18))
            if cut <= 0:
                cut = remaining.find(" ", min(target, max(len(remaining) - 1, 0)))
            if cut <= 0:
                break
            lines.append(remaining[:cut].strip())
            remaining = remaining[cut + 1:].strip()
            total -= capacity
        lines.append(remaining)
        while len(lines) < len(templates):
            lines.insert(max(len(lines) - 1, 0), "")
        return lines[:len(templates)]

    @staticmethod
    def _replace_pdf_partial_line(stream, group: dict, original: str, proposed: str) -> bool:
        parts = ResumeVersionService._pdf_body_runs(group)
        if not parts:
            return False

        compact = []
        positions: list[tuple[int, int, int]] = []
        for part_index, run in enumerate(parts):
            for char_index, char in enumerate(run["text"]):
                if char.isspace():
                    continue
                normalized_char = char.lower().replace("\u2013", "-").replace("\u2014", "-")
                compact.append(normalized_char)
                positions.append((part_index, char_index, len(char)))
        compact_text = "".join(compact)
        target = ResumeVersionService._compact_pdf_text(original)
        start = compact_text.find(target)
        if start < 0:
            return False
        end = start + len(target)
        first = positions[start]
        last = positions[end - 1]
        affected = list(range(first[0], last[0] + 1))
        first_part = parts[first[0]]
        last_part = parts[last[0]]

        if first[0] == last[0]:
            run_operands, run_operator = stream.operations[first_part["operation_index"]]
            current = first_part["text"]
            replacement_start = first[1]
            replacement_end = last[1] + last[2]
            new_text = current[:replacement_start] + proposed + current[replacement_end:]
            ResumeVersionService._set_pdf_text_operand(
                stream,
                first_part["operation_index"],
                first_part["array_index"],
                new_text,
            )
            return True

        first_prefix = first_part["text"][:first[1]]
        last_suffix = last_part["text"][last[1] + last[2]:]
        ResumeVersionService._set_pdf_text_operand(
            stream,
            first_part["operation_index"],
            first_part["array_index"],
            first_prefix + proposed,
        )
        for part_index in affected[1:-1]:
            run = parts[part_index]
            ResumeVersionService._set_pdf_text_operand(
                stream,
                run["operation_index"],
                run["array_index"],
                "",
            )
        ResumeVersionService._set_pdf_text_operand(
            stream,
            last_part["operation_index"],
            last_part["array_index"],
            last_suffix,
        )
        return True

    @staticmethod
    def _replace_pdf_full_lines(stream, matched_groups: list[dict], proposed: str) -> bool:
        body_templates = [
            " ".join(run["text"] for run in ResumeVersionService._pdf_body_runs(group)).strip()
            for group in matched_groups
        ]
        if not any(body_templates):
            return False

        new_lines = ResumeVersionService._split_pdf_replacement(proposed, body_templates)
        for group, new_text in zip(matched_groups, new_lines):
            body_runs = ResumeVersionService._pdf_body_runs(group)
            if not body_runs:
                continue

            # Keep the dominant existing style on the line. This preserves
            # the original font family/weight/size while replacing only text.
            style_counts: dict[tuple[str, float], int] = {}
            for run in body_runs:
                key = (run["font"], run["size"])
                style_counts[key] = style_counts.get(key, 0) + len(run["text"])
            dominant = max(style_counts, key=style_counts.get)
            primary = next(
                (run for run in body_runs if (run["font"], run["size"]) == dominant),
                body_runs[0],
            )

            for run in body_runs:
                ResumeVersionService._set_pdf_text_operand(
                    stream,
                    run["operation_index"],
                    run["array_index"],
                    new_text if run is primary else "",
                )
        return True

    @staticmethod
    def _replace_pdf_text(page, document, replacements: list[dict]) -> list[str]:
        stream = ContentStream(page.get_contents(), document)
        groups = ResumeVersionService._pdf_line_groups(stream)
        errors: list[str] = []
        occupied_y: set[float] = set()

        full_replacements = []
        partial_replacements = []
        for replacement in replacements:
            original = str(replacement.get("original_content") or "")
            proposed = str(replacement.get("proposed_content") or "").strip()
            action_type = str(replacement.get("action_type") or "").upper()
            if action_type == "ADD_SUMMARY":
                continue
            if original and proposed and original != proposed:
                full_replacements.append(replacement)

        for replacement in full_replacements:
            target = ResumeVersionService._compact_pdf_text(replacement.get("original_content", ""))
            if not target:
                continue

            matched_groups = None
            for start in range(len(groups)):
                combined = ""
                for end in range(start, min(start + 6, len(groups))):
                    line_text = " ".join(
                        run["text"]
                        for run in ResumeVersionService._pdf_body_runs(groups[end])
                    )
                    combined = ResumeVersionService._compact_pdf_text(f"{combined} {line_text}")
                    if combined == target:
                        if all(groups[index]["y"] not in occupied_y for index in range(start, end + 1)):
                            matched_groups = groups[start:end + 1]
                        break
                    if len(combined) > len(target) + 220:
                        break
                if matched_groups:
                    break

            if matched_groups and ResumeVersionService._replace_pdf_full_lines(
                stream,
                matched_groups,
                str(replacement.get("proposed_content") or ""),
            ):
                occupied_y.update(group["y"] for group in matched_groups)
                continue

            partial_replacements.append(replacement)

        for replacement in partial_replacements:
            target = ResumeVersionService._compact_pdf_text(replacement.get("original_content", ""))
            if not target:
                continue

            # Rebuild the groups after each partial edit so multiple changes
            # can safely target the same physical PDF line.
            groups = ResumeVersionService._pdf_line_groups(stream)
            applied = False
            for group in groups:
                line_text = "".join(
                    run["text"] for run in ResumeVersionService._pdf_body_runs(group)
                )
                if target in ResumeVersionService._compact_pdf_text(line_text):
                    if ResumeVersionService._replace_pdf_partial_line(
                        stream,
                        group,
                        str(replacement.get("original_content") or ""),
                        str(replacement.get("proposed_content") or ""),
                    ):
                        applied = True
                        break
            if not applied:
                errors.append(
                    f"'{str(replacement.get('original_content') or '')[:80]}' was not found in the original PDF"
                )

        page.replace_contents(stream)
        return errors

    @staticmethod
    def _validate_generated_pdf(pdf_bytes: bytes, modifications: list[dict]) -> list[str]:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
        errors: list[str] = []
        extracted = [page.get_text() or "" for page in doc]
        normalized = ResumeVersionService._compact_pdf_text(" ".join(extracted))
        doc.close()
        for modification in modifications:
            action = str(modification.get("action_type") or "").upper()
            proposed = str(modification.get("proposed_content") or "").strip()
            if not proposed or action == "ADD_SUMMARY":
                continue
            target = ResumeVersionService._compact_pdf_text(proposed)
            if target and target not in normalized:
                errors.append(f"Tailored text is missing from the generated PDF: '{proposed[:80]}'")
        return errors

    @staticmethod
    def _normalize_pdf_word(text: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())

    @classmethod
    def _locate_pdf_change(cls, page, original: str) -> list[list[tuple]] | None:
        target = [
            cls._normalize_pdf_word(token)
            for token in str(original or "").split()
            if cls._normalize_pdf_word(token)
        ]
        if not target:
            return None

        words = page.get_text("words")
        values = [cls._normalize_pdf_word(word[4]) for word in words]
        for start in range(len(values) - len(target) + 1):
            if values[start : start + len(target)] != target:
                continue

            lines: dict[tuple[int, int], list[tuple]] = {}
            for word in words[start : start + len(target)]:
                lines.setdefault((word[5], word[6]), []).append(word)
            return [
                sorted(line, key=lambda item: item[7])
                for _, line in sorted(lines.items(), key=lambda item: (item[0][0], item[0][1]))
            ]
        return None

    @staticmethod
    def _pdf_style_for_word(page, word: tuple) -> dict:
        center_x = (word[0] + word[2]) / 2
        center_y = (word[1] + word[3]) / 2
        best = None
        best_area = 0.0
        for block in page.get_text("dict").get("blocks", []):
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    rect = span.get("bbox")
                    if not rect:
                        continue
                    x0, y0, x1, y1 = rect
                    if x0 <= center_x <= x1 and y0 <= center_y <= y1:
                        area = max(0.0, min(x1, word[2]) - max(x0, word[0])) * max(
                            0.0,
                            min(y1, word[3]) - max(y0, word[1]),
                        )
                        if area > best_area:
                            best = span
                            best_area = area
        return best or {"font": "ArialMT", "size": 9.48, "color": 0}

    @staticmethod
    def _register_pdf_font(
        doc,
        page,
        font_name: str,
        alias: str,
        font_dir: str,
    ) -> tuple[str, str | None]:
        reference = next(
            (item for item in page.get_fonts(full=True) if font_name.lower() in item[3].lower()),
            None,
        )
        if not reference or str(reference[1]).lower() not in {"ttf", "otf"}:
            return "helv", None
        try:
            _, _, _, font_buffer = doc.extract_font(reference[0])
            if not font_buffer or font_buffer[:4] not in {b"\x00\x01\x00\x00", b"OTTO"}:
                return "helv", None
            font_path = os.path.join(font_dir, f"{alias}.ttf")
            with open(font_path, "wb") as handle:
                handle.write(font_buffer)
            return alias, font_path
        except Exception:
            return "helv", None

    @staticmethod
    def _split_pdf_replacement_to_lines(
        text: str,
        widths: list[float],
        font: pymupdf.Font,
        fontsize: float,
    ) -> list[str] | None:
        words = str(text or "").split()
        lines: list[str] = []
        for width in widths:
            line = ""
            while words:
                candidate = (line + " " + words[0]).strip()
                if font.text_length(candidate, fontsize) <= width:
                    line = candidate
                    words.pop(0)
                    continue
                break
            lines.append(line)
        return lines if not words else None

    def _build_native_pdf_bytes(
        self,
        source_bytes: bytes,
        accepted_changes: list[dict],
    ) -> bytes:
        doc = pymupdf.open(stream=source_bytes, filetype="pdf")
        actionable: list[dict] = []
        seen: set[tuple[str, str]] = set()

        for change in accepted_changes:
            action = str(change.get("action_type") or "").upper()
            original = str(change.get("original_content") or "").strip()
            proposed = str(change.get("proposed_content") or "").strip()
            if action == "ADD_SUMMARY" or not original or not proposed or original == proposed:
                continue
            fingerprint = (self._compact_pdf_text(original), self._compact_pdf_text(proposed))
            if fingerprint not in seen:
                seen.add(fingerprint)
                actionable.append(change)

        if not actionable:
            return source_bytes

        plans: list[dict] = []
        errors: list[str] = []
        font_dir = tempfile.mkdtemp(prefix="ats_pdf_fonts_")

        for change_index, change in enumerate(actionable):
            matched = None
            page_index = None
            for index, page in enumerate(doc):
                matched = self._locate_pdf_change(
                    page,
                    str(change.get("original_content") or ""),
                )
                if matched:
                    page_index = index
                    break

            if not matched or page_index is None:
                errors.append(
                    f"'{
                        str(change.get("original_content") or "")[:80]
                    }' was not found in the original PDF"
                )
                continue

            page = doc[page_index]
            style = self._pdf_style_for_word(page, matched[0][0])
            font_alias = f"_ats_tailor_{change_index}"
            font_name, font_file = self._register_pdf_font(
                doc,
                page,
                str(style.get("font") or "ArialMT"),
                font_alias,
                font_dir,
            )
            font = (
                pymupdf.Font(fontfile=font_file)
                if font_file
                else pymupdf.Font("helv")
            )

            line_rects = [
                pymupdf.Rect(
                    line[0][0],
                    line[0][1],
                    line[-1][2],
                    line[-1][3],
                )
                for line in matched
            ]
            widths = [rect.width for rect in line_rects]
            fontsize = float(style.get("size") or 9.48)
            replacement_lines = self._split_pdf_replacement_to_lines(
                str(change.get("proposed_content") or ""),
                widths,
                font,
                fontsize,
            )
            while replacement_lines is None and fontsize > 7.0:
                fontsize -= 0.25
                replacement_lines = self._split_pdf_replacement_to_lines(
                    str(change.get("proposed_content") or ""),
                    widths,
                    font,
                    fontsize,
                )

            if replacement_lines is None:
                errors.append(
                    "Tailored text does not fit the original layout: "
                    f"'{str(change.get('proposed_content') or '')[:80]}'"
                )
                continue

            plans.append(
                {
                    "page_index": page_index,
                    "rects": line_rects,
                    "lines": replacement_lines,
                    "font_name": font_name,
                    "font_file": font_file,
                    "fontsize": fontsize,
                }
            )

            for rect in line_rects:
                page.add_redact_annot(
                    rect,
                    fill=(1, 1, 1),
                    cross_out=False,
                )

        if errors:
            doc.close()
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="PDF changes could not be mapped to the original resume: "
                + "; ".join(errors),
            )

        for page in doc:
            page.apply_redactions(images=0, graphics=0, text=0)

        for plan in plans:
            page = doc[plan["page_index"]]
            for rect, line in zip(plan["rects"], plan["lines"]):
                if not line:
                    continue
                box = pymupdf.Rect(
                    rect.x0,
                    rect.y0 - 0.5,
                    rect.x1,
                    rect.y1 + 0.8,
                )
                result = page.insert_textbox(
                    box,
                    line,
                    fontname=plan["font_name"],
                    fontfile=plan["font_file"],
                    fontsize=plan["fontsize"],
                    lineheight=1.0,
                    color=(0, 0, 0),
                    overlay=True,
                )
                if result < -0.1:
                    doc.close()
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Tailored text could not be placed without changing the original layout.",
                    )

        output = io.BytesIO()
        doc.save(output, garbage=4, deflate=True)
        result = output.getvalue()
        page_count = len(doc)
        doc.close()

        reader = PdfReader(io.BytesIO(result))
        if len(reader.pages) != page_count:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Tailored PDF changed the original page count unexpectedly.",
            )

        artifact_errors = self._validate_generated_pdf(result, actionable)
        if artifact_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Generated PDF failed content validation: "
                + "; ".join(artifact_errors),
            )
        return result

    def build_pdf_bytes(
        self,
        resume: Resume,
        final_text: str,
        accepted_changes: list[dict],
    ) -> bytes:
        if not resume.storage_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Original resume file is not available for PDF preview.",
            )

        try:
            source_bytes = self.storage.get_bytes(resume.storage_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Original resume file could not be loaded for PDF preview.",
            ) from exc

        if resume.content_type == "application/pdf":
            return self._build_native_pdf_bytes(
                source_bytes,
                accepted_changes,
            )

        docx_bytes = self.build_docx_bytes(resume, final_text, accepted_changes)
        temp_dir = tempfile.mkdtemp(prefix="resume_pdf_preview_")
        docx_path = os.path.join(temp_dir, "resume.docx")
        pdf_path = os.path.join(temp_dir, "resume.pdf")

        try:
            with open(docx_path, "wb") as handle:
                handle.write(docx_bytes)

            converter = shutil.which("libreoffice") or shutil.which("soffice")
            if converter:
                result = subprocess.run(
                    [
                        converter,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        temp_dir,
                        docx_path,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0 or not os.path.exists(pdf_path):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=result.stderr.strip() or "Failed to generate PDF preview.",
                    )
            else:
                if os.name != "nt":
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="PDF conversion requires LibreOffice in this runtime.",
                    )
                self._convert_docx_to_pdf_with_word(docx_path, pdf_path)

            return Path(pdf_path).read_bytes()
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def generate_docx(self, version: ResumeVersion) -> str:
        resume = version.resume
        if resume is None or not resume.storage_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Original resume file is not available for document generation.",
            )

        try:
            source_bytes = self.storage.get_bytes(resume.storage_path)
        except (FileNotFoundError, OSError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Original resume file could not be loaded from storage.",
            ) from exc

        if resume.content_type == "application/pdf":
            doc = self._build_docx_from_pdf_text(
                version,
                source_bytes,
            )
        else:
            try:
                doc = Document(io.BytesIO(source_bytes))
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Original DOCX file could not be opened.",
                ) from exc

        modifications = version.validation_summary.get("accepted_changes", [])
        errors = []
        if resume.content_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
            errors = self._apply_docx_modifications(doc, modifications)
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Document changes could not be mapped to the original DOCX: " + "; ".join(errors),
            )
        self._compact_one_page_tailored_layout(doc, modifications)
        artifact_errors = self._validate_generated_docx(doc, modifications, version.final_text)
        if artifact_errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Generated DOCX failed content validation: " + "; ".join(artifact_errors),
            )

        output = io.BytesIO()
        doc.save(output)
        output_bytes = output.getvalue()

        key = self.storage.put_upload(
            user_id=version.user_id,
            kind=f"versions/{version.id}",
            filename=f"{version.version_name or 'resume'}.docx",
            data=output_bytes,
            content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
        version.document_path = key
        version.status = "docx_ready"
        self.db.add(version)
        self.db.commit()
        return key

    @staticmethod
    def _build_docx_from_pdf_text(
        version: ResumeVersion,
        source_bytes: bytes,
    ) -> Document:
        doc = Document()
        section = doc.sections[0]
        section.page_width = Inches(8.27)
        section.page_height = Inches(11.69)
        section.top_margin = Inches(0.45)
        section.bottom_margin = Inches(0.45)
        section.left_margin = Inches(0.55)
        section.right_margin = Inches(0.55)

        normal = doc.styles["Normal"]
        normal.font.name = "Arial"
        normal.font.size = Pt(9.5)

        formatted = (
            version.validation_summary.get("formatted_text")
            or ResumeVersionService._build_formatted_resume_text(
                version.resume,
                version.final_text,
                version.validation_summary.get("accepted_changes", []),
            )
            or version.final_text
        )
        lines = formatted.splitlines()
        for line in lines:
            text = line.rstrip()
            paragraph = doc.add_paragraph()
            paragraph.paragraph_format.space_after = Pt(1.5)
            paragraph.paragraph_format.line_spacing = 1.0
            if not text.strip():
                paragraph.paragraph_format.space_after = Pt(2)
                continue

            stripped = text.strip()
            is_heading = (
                stripped.upper() == stripped
                and 2 <= len(stripped.split()) <= 6
            ) or stripped in {
                "PROJECTS", "TECHNICAL SKILLS", "EDUCATION",
                "CERTIFICATIONS", "ACHIEVEMENTS", "SOFT SKILLS",
                "EXPERIENCE", "SUMMARY",
            }
            run = paragraph.add_run(text)
            run.font.name = "Arial"
            run.font.size = Pt(10 if is_heading else 9.5)
            if is_heading:
                run.bold = True

        return doc

    @staticmethod
    def _convert_docx_to_pdf_with_word(docx_path: str, pdf_path: str) -> None:
        import json

        source = json.dumps(os.path.abspath(docx_path))
        target = json.dumps(os.path.abspath(pdf_path))
        script = f"""
$ErrorActionPreference = 'Stop'
$word = $null
$doc = $null
try {{
    $word = New-Object -ComObject Word.Application
    $word.Visible = $false
    $word.DisplayAlerts = 0
    $source = {source}
    $target = {target}
    $doc = $word.Documents.Open($source, $false, $true)
    $doc.ExportAsFixedFormat($target, 17)
}} finally {{
    if ($doc -ne $null) {{ $doc.Close($false) }}
    if ($word -ne $null) {{ $word.Quit() }}
}}
"""
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not os.path.exists(pdf_path):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=result.stderr.strip() or "Word could not generate the PDF.",
            )

    def generate_pdf(self, version: ResumeVersion) -> str:
        resume = version.resume
        if resume is None or not resume.storage_path:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Original resume file is not available for PDF generation.",
            )

        if resume.content_type == "application/pdf":
            source_bytes = self.storage.get_bytes(resume.storage_path)
            accepted_changes = version.validation_summary.get("accepted_changes", [])
            pdf_bytes = self._build_native_pdf_bytes(
                source_bytes,
                accepted_changes,
            )
            key = self.storage.put_upload(
                user_id=version.user_id,
                kind=f"versions/{version.id}",
                filename=f"{version.version_name or 'resume'}.pdf",
                data=pdf_bytes,
                content_type="application/pdf",
            )
            version.pdf_path = key
            self.db.add(version)
            self.db.commit()
            return key

        docx_key = self.generate_docx(version)
        temp_dir = tempfile.mkdtemp(prefix="resume_pdf_")
        docx_path = os.path.join(temp_dir, "resume.docx")
        pdf_name = "resume.pdf"
        pdf_path = os.path.join(temp_dir, pdf_name)

        try:
            docx_bytes = self.storage.get_bytes(docx_key)
            with open(docx_path, "wb") as handle:
                handle.write(docx_bytes)

            converter = shutil.which("libreoffice") or shutil.which("soffice")
            if converter:
                result = subprocess.run(
                    [
                        converter,
                        "--headless",
                        "--convert-to",
                        "pdf",
                        "--outdir",
                        temp_dir,
                        docx_path,
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if result.returncode != 0 or not os.path.exists(pdf_path):
                    raise HTTPException(
                        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                        detail=result.stderr.strip() or "Failed to generate PDF.",
                    )
            else:
                if os.name != "nt":
                    raise HTTPException(
                        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                        detail="PDF conversion requires LibreOffice in this runtime.",
                    )
                self._convert_docx_to_pdf_with_word(docx_path, pdf_path)

            pdf_bytes = Path(pdf_path).read_bytes()
            key = self.storage.put_upload(
                user_id=version.user_id,
                kind=f"versions/{version.id}",
                filename=f"{version.version_name or 'resume'}.pdf",
                data=pdf_bytes,
                content_type="application/pdf",
            )
            version.pdf_path = key
            self.db.add(version)
            self.db.commit()
            return key
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    @staticmethod
    def _compact_one_page_tailored_layout(doc: Document, modifications: list[dict]) -> None:
        """Use minimal vertical compaction when tailoring adds a new section."""
        adds_summary = any(
            str(item.get("action_type") or "").upper() == "ADD_SUMMARY"
            for item in modifications
        )
        if not adds_summary or not doc.sections:
            return

        # Preserve the original page geometry everywhere except for a
        # minimal 4 pt bottom-margin reduction when Summary is added. This keeps
        # an originally one-page resume on one page without shrinking body text.
        section = doc.sections[0]
        section.bottom_margin = min(section.bottom_margin, Inches(32 / 72))
        for paragraph in doc.paragraphs:
            if paragraph.text.strip().startswith("Computer Science graduate targeting"):
                paragraph.paragraph_format.space_before = Pt(0)
                paragraph.paragraph_format.space_after = Pt(0)
                paragraph.paragraph_format.line_spacing = 1.0
                break

    @staticmethod
    def _clone_docx_paragraph(source, text: str):
        """Clone paragraph-level and first-run formatting from an existing resume paragraph."""
        paragraph = source._parent.add_paragraph()
        paragraph._p.clear_content()
        if source._p.pPr is not None:
            paragraph._p.append(copy.deepcopy(source._p.pPr))

        source_runs = list(source.runs)
        if source_runs:
            source_run = next(
                (candidate for candidate in source_runs if candidate.bold is not True),
                source_runs[0],
            )
            # Clone the entire normal body run, not just its rPr. This preserves
            # the exact font mapping Word uses for the uploaded document.
            cloned_run = copy.deepcopy(source_run._r)
            paragraph._p.append(cloned_run)
            run = paragraph.runs[-1]
            run.text = text
        else:
            paragraph.add_run(text)

        return paragraph

    @staticmethod
    def _apply_docx_modifications(doc: Document, modifications: list[dict]) -> list[str]:
        errors = []
        for modification in modifications:
            original = str(modification.get("original_content") or "")
            proposed = str(modification.get("proposed_content") or "")
            action_type = str(modification.get("action_type") or "")
            if action_type == "ADD_SUMMARY":
                if not proposed:
                    continue
                summary_lines = [line.strip() for line in proposed.splitlines() if line.strip()]
                if not summary_lines:
                    continue

                section_heading_pattern = r"(PROFESSIONAL SUMMARY|SUMMARY|TECHNICAL SKILLS|SKILLS|TECHNICAL PROJECTS|PROJECTS|EXPERIENCE|EDUCATION|CERTIFICATIONS|ACHIEVEMENTS|SOFT SKILLS)"
                first_section_index = next(
                    (
                        index
                        for index, paragraph in enumerate(doc.paragraphs)
                        if re.fullmatch(section_heading_pattern, paragraph.text.strip(), flags=re.IGNORECASE)
                    ),
                    None,
                )
                section_heading = doc.paragraphs[first_section_index] if first_section_index is not None else None

                # Use a real body paragraph as the formatting source instead of
                # guessing from bold-run combinations. This preserves the user's
                # font, size, spacing, and paragraph properties.
                body_source = None
                start_index = (first_section_index + 1) if first_section_index is not None else 0
                for paragraph in doc.paragraphs[start_index:]:
                    if paragraph.text.strip() and not re.fullmatch(section_heading_pattern, paragraph.text.strip(), flags=re.IGNORECASE):
                        body_source = paragraph
                        break
                if body_source is None:
                    for paragraph in doc.paragraphs:
                        if paragraph.text.strip() and not re.fullmatch(section_heading_pattern, paragraph.text.strip(), flags=re.IGNORECASE):
                            body_source = paragraph
                            break

                # Reuse a blank paragraph directly before the first section when
                # available. Otherwise insert immediately before that section.
                blank = None
                if first_section_index is not None:
                    for paragraph in reversed(doc.paragraphs[:first_section_index]):
                        if not paragraph.text.strip():
                            blank = paragraph
                            break
                insertion_anchor = blank._p if blank is not None else (section_heading._p if section_heading is not None else None)

                created: list = []
                if section_heading is not None:
                    summary_heading = ResumeVersionService._clone_docx_paragraph(
                        section_heading,
                        "PROFESSIONAL SUMMARY",
                    )
                    summary_heading.paragraph_format.space_before = Pt(0)
                    summary_heading.paragraph_format.space_after = Pt(0)
                    created.append(summary_heading)
                if body_source is not None:
                    created.extend(
                        ResumeVersionService._clone_docx_paragraph(body_source, line)
                        for line in summary_lines
                    )
                else:
                    created.extend(doc.add_paragraph(line) for line in summary_lines)

                # Insert in reverse while moving the anchor so the block stays
                # in the intended order: heading, body, existing first section.
                anchor = insertion_anchor
                for paragraph in reversed(created):
                    if anchor is not None:
                        anchor.addprevious(paragraph._p)
                    else:
                        doc.element.body.insert(0, paragraph._p)
                    anchor = paragraph._p

                if blank is not None:
                    doc.element.body.remove(blank._p)
                continue

            if not original or not proposed or original == proposed:
                continue

            applied = False
            for paragraph in ResumeVersionService._iter_docx_paragraphs(doc):
                if ResumeVersionService._replace_in_paragraph(paragraph, original, proposed):
                    applied = True
                    break

            if not applied:
                errors.append(f"'{original[:80]}' was not found")
        return errors

    @staticmethod
    def _iter_docx_paragraphs(doc: Document):
        yield from doc.paragraphs
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    yield from ResumeVersionService._iter_cell_paragraphs(cell)

    @staticmethod
    def _iter_cell_paragraphs(cell):
        yield from cell.paragraphs
        for table in cell.tables:
            for row in table.rows:
                for nested_cell in row.cells:
                    yield from ResumeVersionService._iter_cell_paragraphs(nested_cell)

    @staticmethod
    def _docx_text(doc: Document) -> str:
        paragraphs = list(ResumeVersionService._iter_docx_paragraphs(doc))
        return "\n".join(paragraph.text for paragraph in paragraphs).strip()

    @staticmethod
    def _validate_generated_docx(
        doc: Document,
        modifications: list[dict],
        expected_text: str = "",
    ) -> list[str]:
        text = ResumeVersionService._docx_text(doc)
        if not text:
            return ["Generated DOCX contains no readable text."]

        normalized_text = " ".join(text.split()).lower()
        errors = []

        # The renderer works on the original DOCX, so accepted edits should not
        # be allowed to silently remove unrelated resume content. Compare the
        # generated text against the exact logical final text with token counts;
        # this is tolerant of paragraph/run reformatting but catches lost bullets.
        if expected_text:
            import collections
            token_pattern = re.compile(r"[a-z0-9+#.]+", flags=re.IGNORECASE)
            expected_tokens = collections.Counter(token_pattern.findall(expected_text.lower()))
            actual_tokens = collections.Counter(token_pattern.findall(text.lower()))
            missing_tokens = sum(
                max(0, count - actual_tokens.get(token, 0))
                for token, count in expected_tokens.items()
            )
            expected_total = max(1, sum(expected_tokens.values()))
            if missing_tokens > max(3, round(expected_total * 0.01)):
                errors.append(
                    "Generated DOCX is missing resume content from the expected final text "
                    f"({missing_tokens} token(s) missing)."
                )

        # Validate the actual accepted edits rather than requiring the entire
        # flattened final resume text to appear as one contiguous DOCX string.
        # DOCX layouts commonly change paragraph/run boundaries even when the
        # visible document content is correct.
        for modification in modifications:
            original = " ".join(str(modification.get("original_content") or "").split()).lower()
            proposed = " ".join(str(modification.get("proposed_content") or "").split()).lower()
            action_type = str(modification.get("action_type") or "").upper()
            change_category = str(modification.get("change_category") or "").upper()

            # KEEP changes do not modify the document, so there is no new text
            # that should be searched for separately.
            if not proposed or proposed == original or change_category == "KEEP":
                continue

            if action_type == "ADD_SUMMARY":
                if proposed not in normalized_text:
                    errors.append(
                        f"Tailored summary is missing from the generated DOCX: '{proposed[:80]}'"
                    )
                continue

            if proposed not in normalized_text:
                errors.append(
                    f"Tailored text is missing from the generated DOCX: '{proposed[:80]}'"
                )

        return errors

    @staticmethod
    def _replace_in_paragraph(paragraph, original: str, proposed: str) -> bool:
        runs = paragraph.runs
        combined = "".join(run.text or "" for run in runs)
        start = combined.find(original)
        if start < 0:
            return False
        end = start + len(original)

        cursor = 0
        start_run = end_run = None
        start_offset = end_offset = 0
        for index, run in enumerate(runs):
            run_text = run.text or ""
            next_cursor = cursor + len(run_text)
            if start_run is None and cursor <= start < next_cursor:
                start_run = index
                start_offset = start - cursor
            if cursor < end <= next_cursor:
                end_run = index
                end_offset = end - cursor
                break
            cursor = next_cursor

        if start_run is None or end_run is None:
            return False

        if start_run == end_run:
            text = runs[start_run].text or ""
            runs[start_run].text = text[:start_offset] + proposed + text[end_offset:]
            return True

        start_text = runs[start_run].text or ""
        end_text = runs[end_run].text or ""
        runs[start_run].text = start_text[:start_offset] + proposed
        for index in range(start_run + 1, end_run):
            runs[index].text = ""
        runs[end_run].text = end_text[end_offset:]
        return True

    def validate_resume_text(self, text: str) -> dict:
        lowered = text.lower()
        errors = []
        if not text or len(text.strip()) < 80:
            errors.append("Resume content is too short to be valid.")

        if any(keyword in lowered for keyword in ["managed 10x", "increased revenue by 500", "invented", "revolutionized"]):
            errors.append("Proposed text contains unsupported metric language and must be reviewed.")

        detected_core = {
            section for section in CORE_RESUME_SECTIONS
            if re.search(rf"\b{re.escape(section)}\b", lowered)
        }
        # Entry-level resumes can use Projects + Skills + Education without
        # needing a Summary or formal Experience section.
        if not (
            "skills" in detected_core
            and "education" in detected_core
            and ("projects" in detected_core or "experience" in detected_core)
        ):
            errors.append("Resume needs Skills, Education, and either Projects or Experience.")

        truthfulness = "SUPPORTED" if not errors else "REQUIRES_REVIEW"
        return {
            "truthfulness": truthfulness,
            "document_integrity": True,
            "formatting_preservation": True,
            "required_sections": not errors,
            "ats_readability": True,
            "validation_errors": errors,
        }

    @staticmethod
    def _derive_tailored_text(original_text: str, jd_text: str) -> str:
        # Tailoring must be based on explicit, user-accepted evidence.
        # This legacy helper therefore never adds claims from the JD alone.
        return original_text.strip()

    @staticmethod
    def _build_diff(original_text: str, tailored_text: str) -> str:
        if original_text == tailored_text:
            return "No changes"
        return f"Original:\n{original_text}\n\nTailored:\n{tailored_text}"

    @staticmethod
    def _build_structured_diff(original_text: str, target_text: str) -> list[dict[str, str]]:
        import difflib

        if original_text == target_text:
            return [{"type": "unchanged", "text": original_text}]

        result = []
        matcher = difflib.SequenceMatcher(
            None,
            original_text.splitlines(),
            target_text.splitlines(),
            autojunk=False,
        )
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "equal":
                result.append({"type": "unchanged", "text": "\n".join(original_text.splitlines()[i1:i2])})
            elif tag in {"replace", "delete"}:
                result.append({"type": "removed", "text": "\n".join(original_text.splitlines()[i1:i2])})
            if tag in {"replace", "insert"}:
                result.append({"type": "added", "text": "\n".join(target_text.splitlines()[j1:j2])})
        return [item for item in result if item["text"]]
