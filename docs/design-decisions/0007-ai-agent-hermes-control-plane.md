# AI Agent with Hermes runtime

Decision: 2026-10-12; user explicitly selected Hermes as the agent engine,
`ai_agent` as the Community addon name, Enterprise AI as the functional reference,
and simplicity with direct APIs instead of broker infrastructure.

Odoo owns business identity, scoped context, approved configuration and execution
governance. Hermes owns inference/runtime. Runtime integration uses HTTPS APIs,
with a distinct management surface when required. No NATS or custom host bridge
is introduced for the first increment. Credentials use masked write-only setup fields and encrypted private runtime
files; only inaccessible opaque references enter database records. Legacy
deployment environment references remain supported. Local setup imports the
approved profile credentials privately. Deployment controls allowed
origins; transport pins resolved IP and validates TLS against the configured host.

Start with a dedicated tool-free, memory-free internal profile. Odoo supplies
bounded reads as the actual requester; a powerful bot user is never used to
retrieve an employee's context. Customer agents and external effects remain
unavailable until corresponding deterministic authorization and approved-action
adapters exist. Instructions and skills are never authorization.

Native Odoo cards, sheets, forms, chatter, lists and optional columns provide the
initial UI. The initial conversation request uses a native dialog and run history;
it is not presented as the finished Enterprise chat experience. Future contextual
chat, source retrieval and execution integrations retain this safety boundary.

Every remote submission has a durable claim and unique request key. Unknown
acceptance stops automatic retries. Cancellation is cooperative and confirmed
terminal states are distinct from requested stops. Audit is append-only through
normal ORM/RPC; database operators remain trusted administrators.

Provider/model selection (2026-10-13): Odoo shows the connected Hermes catalog
and verifies agent overrides against freshly reported authentication/model
state. Provider secrets, OAuth sessions and engine-default configuration stay
in Hermes’s native management UI, opened through the reviewed connection URL.
The initial integration deliberately uses this native setup handoff rather than
duplicating provider authentication or granting Odoo generic environment/config
write APIs. No live provider or model configuration is changed by development.

Persistent model selection correction (2026-10-13): management belongs in the
main connection setup. Each engine has a provider/model browser and a persisted,
company-scoped enabled-model registry. Native agent dropdowns select that engine's
enabled models; disabling a selected entry blocks subsequent use. Both enabling
and inference recheck Hermes authentication. Catalog refresh does not change the
engine default. Native Hermes setup remains the owner of provider authentication.
