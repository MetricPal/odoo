-- A copied database must obtain fresh, explicit sandbox authorization.
UPDATE omni_account SET telegram_sandbox_authorized = false;
