// Senado CPI/CPMI temporal gates
// Promotion blockers:
// - senado_temporal_invalid_edges_count must be 0
// - senado_fallback_rows_count must be 0

MATCH (i:Inquiry {source: 'senado_cpis'})
RETURN count(i) AS senado_inquiry_count;

MATCH (r:InquiryRequirement {source: 'senado_cpis'})
RETURN count(r) AS senado_requirements_count;

MATCH (s:InquirySession {source: 'senado_cpis'})
RETURN count(s) AS senado_sessions_count;

MATCH (i:Inquiry {source: 'senado_cpis'})
WHERE i.inquiry_id = 'senado-cpmi-inss-2026'
RETURN count(i) AS senado_fallback_rows_count;

MATCH (i:Inquiry {source: 'senado_cpis'})-[r:TEM_REQUERIMENTO|REALIZOU_SESSAO]->()
WHERE r.temporal_status = 'invalid'
RETURN count(r) AS senado_temporal_invalid_edges_count;

MATCH (i:Inquiry {source: 'senado_cpis'})-[r:TEM_REQUERIMENTO|REALIZOU_SESSAO]->()
WHERE r.temporal_status = 'unknown'
RETURN count(r) AS senado_temporal_unknown_edges_count;
