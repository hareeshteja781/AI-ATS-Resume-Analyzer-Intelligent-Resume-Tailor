export type User = {
  id: number
  email: string
  is_active: boolean
}

export type Resume = {
  id: number
  user_id: number
  filename: string
  original_filename: string
  text_content: string
  status: string
  storage_path: string
}

export type JobDescription = {
  id: number
  user_id: number
  filename?: string | null
  source_type: string
  text_content: string
  normalized_text: string
  status: string
}

export type JobMatchResult = {
  id: number
  resume_id: number
  job_description_id: number
  job_match_score: number
  ats_compatibility_score: number
  layout_preservation_score: number
  truthfulness_status: string
  matched_skills: string[]
  missing_skills: string[]
  partially_matched_skills: string[]
  responsibilities_matched: string[]
  evidence_found: string[]
  important_gaps: string[]
  ats_structure_issues: string[]
  recommendations: string[]
  score_breakdown: Record<string, number>
  category_scores?: Record<string, number>
  category_statuses?: Record<string, 'EVALUATED' | 'NOT_EVALUATED'>
  requirement_matches?: Array<{
    requirement: string
    category: string
    importance: string
    status: 'MATCHED' | 'PARTIALLY_MATCHED' | 'MISSING' | 'NOT_EVALUATED'
    evidence?: string
    evidence_reference?: string | null
    match_method?: string
    reason?: string
  }>
  benchmark: Record<string, unknown>
  section_scores?: Record<string, number>
  section_details?: Record<string, string[]>
  present_sections?: string[]
  project_matches?: Array<Record<string, unknown>>
  layout_analysis?: Record<string, unknown>
}
