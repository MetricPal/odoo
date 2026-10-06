-- Restore/copy isolation: preserve history and uncertain outcomes for reconciliation.
UPDATE omni_channel SET dispatch_enabled = false;
UPDATE omni_channel SET alerts_enabled = false;
UPDATE omni_inbound_endpoint SET state = 'disabled' WHERE state = 'enabled';
UPDATE omni_inbound_policy SET state = 'paused' WHERE state = 'active';
-- Also protect module-only neutralization, independently of base's cron hook.
UPDATE ir_cron SET active = false WHERE id IN (
    SELECT res_id FROM ir_model_data
    WHERE module = 'omni_channel' AND model = 'ir.cron'
);
