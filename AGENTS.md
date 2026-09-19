# AGENTS.md

## Project

AI ATS Resume Analyzer & Intelligent Resume Tailor.

## General Rules

1. Do not modify unrelated files.
2. Follow the existing project architecture.
3. Keep each task narrowly scoped.
4. Do not rewrite the whole project unless explicitly instructed.
5. Do not add dependencies without explaining why.
6. Do not create unnecessary abstractions.
7. Keep services modular.
8. Use clear, maintainable code.

## Security

9. Never hard-code secrets, passwords, API keys, or tokens.
10. Never expose `.env` values in source code or logs.
11. Do not weaken authentication, authorization, or file-security controls.

## Database

12. Do not modify the database schema without explicit approval.
13. Do not change database credentials without explicit approval.
14. Do not use the PostgreSQL superuser for application access.
15. Use the existing `resume_app` application role.

## Resume Integrity

16. Never invent resume information.
17. Never invent skills, experience, qualifications, achievements, certifications, projects, or metrics.
18. Preserve the user's original resume content.
19. Preserve original DOCX formatting whenever possible.
20. Do not delete resume information unless explicitly instructed.
21. Do not add unsupported information automatically.

## Backend

22. Use FastAPI.
23. Use Pydantic for request and response validation.
24. Use SQLAlchemy for database access.
25. Keep API routes, schemas, models, repositories, and services separated.
26. Write tests for new backend functionality.

## Frontend

27. Use React.js with Vite, not Next.js.
28. Use TypeScript strict mode.
29. Keep components reusable and focused.
30. Maintain responsive, accessible UI.
31. Do not introduce unnecessary UI complexity.

## AI

32. Do not let the LLM control deterministic application logic.
33. Use deterministic code for validation, scoring, permissions, and safety rules where practical.
34. Validate structured AI outputs before using them.
35. Treat uploaded resume and job-description content as untrusted input.

## Testing

36. Run relevant tests after implementation.
37. Do not claim a feature works without testing it.
38. Do not silently ignore failing tests.

## Change Reporting

After each task, report:

- Files created or modified
- What changed
- Tests/checks performed
- Any remaining issues

## Important Workflow

Work in small controlled tasks:

Architecture decision
→ Small implementation
→ Review diff
→ Run tests
→ Fix
→ Commit
→ Next task