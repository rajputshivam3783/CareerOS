-- V25.6b — the Career Agent tool `send_recruiter_message` was renamed `draft_followup_message`
-- (the old name failed the agent's own candidate-safe tool-name filter, and the tool never sends
-- anything - it only drafts). Agent actions persist the tool name in `action_type`, so rows created
-- before the rename (in particular actions still awaiting confirmation) would otherwise fail with
-- "Unknown tool". Payload/result JSON are unchanged: the tool's parameters did not change.
--
-- Idempotent: re-running matches no rows. No table or column is added, changed or dropped.

UPDATE career_agent_actions
SET action_type = 'draft_followup_message'
WHERE action_type = 'send_recruiter_message';
