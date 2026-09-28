"""Coverage catalog.

"Tier A" here means a real, implemented collector (see
app/ingestion/sources.py) — not an independently verified one. No
session that has worked on this codebase has had live internet access
to actually load these government sites and confirm today's markup
matches what the adapters expect, so none of them ship enabled by
default; an operator must do that check before flipping
`enabled=True`. An earlier version of this file (and of
app/ingestion/sources.py) described these as "verified"/"live
validated" and shipped them enabled — that was a false claim with no
real verification behind it, and has been corrected.

Tier B entries are maintained integration targets; they are
intentionally not scraped at all until someone builds and validates an
adapter for their current official publishing surface.
"""
TIER_A = [
 {"name":"UPSC","category":"Civil Services / Defence / Engineering / Medical","url":"https://www.upsc.gov.in/examinations/active-exams"},
 {"name":"SSC","category":"SSC examinations","url":"https://ssc.gov.in/"},
 {"name":"Railway Recruitment Boards","category":"Railways","url":"https://www.rrbcdg.gov.in/employment-notices.php"},
 {"name":"IBPS","category":"Banking","url":"https://www.ibps.in/index.php/crp-updates/"},
 # V16 batch — see the caveat comment above each SourceConfig in
 # app/ingestion/sources.py: implemented, not live-verified.
 {"name":"NTA","category":"NTA","url":"https://nta.ac.in/"},
 {"name":"India Post","category":"India Post","url":"https://www.indiapost.gov.in/VAS/Pages/Recruitment.aspx"},
 {"name":"ISRO","category":"ISRO","url":"https://www.isro.gov.in/Careers.html"},
 {"name":"DRDO","category":"DRDO","url":"https://drdo.gov.in/drdo/recruitment"},
 {"name":"EPFO","category":"EPFO","url":"https://www.epfindia.gov.in/site_en/Recruitment.php"},
 {"name":"ESIC","category":"ESIC","url":"https://www.esic.gov.in/recruitments"},
 {"name":"RBI","category":"Banking","url":"https://opportunities.rbi.org.in/Scripts/bs_viewcontent.aspx?Id=79"},
 {"name":"SBI Careers","category":"Banking","url":"https://bank.sbi/web/careers"},
]
COVERAGE_TARGETS = [
 "Indian Army","Indian Navy","Indian Air Force",
 "Coast Guard","BARC","CSIR","ICMR","AIIMS",
 "FCI","LIC","NABARD","SEBI","SIDBI",
 "Delhi Subordinate Services","BPSC","UPPSC","MPPSC","RPSC","HPSC","PPSC",
 "UKPSC","JPSC","CGPSC","OPSC","WBPSC","APPSC","TSPSC","KPSC","KPSC Kerala",
 "TNPSC","MPSC","GPSC","Goa PSC","Assam PSC","Arunachal PSC","Manipur PSC",
 "Meghalaya PSC","Mizoram PSC","Nagaland PSC","Sikkim PSC","Tripura PSC",
 "Jammu & Kashmir recruiting bodies","State police recruitment boards",
 "State teacher recruitment boards","Major PSU career portals"
]
