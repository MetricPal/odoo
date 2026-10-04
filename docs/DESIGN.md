# UX / Design System Direction

## Design philosophy

The ERP should feel like a business operating system rather than a collection of forms.

Primary interaction:
Review → Understand → Approve/Reject → Done.

## Web

- Odoo-inspired top bar
- Anchored Floating Command Panel for App Launcher
- No permanent left sidebar as the primary application navigation
- AI actions available in context
- Approval Center highly accessible
- AI Workstream as a central work surface

## Module identity

- Every real module needs a deliberate name, one-sentence description, and icon.
- Names should describe the business surface users recognize, not the internal
  technical mechanism.
- Icons should be sourced, designed, or adapted intentionally before delivery;
  do not leave default or placeholder app icons in completed modules.

## Authentication

- Authentication pages use the company logo, concise page-owned title, and
  page-owned subtitle/message. The shared authentication shell should not own
  page-specific headings.
- Global authentication footer content belongs in the shared standalone auth
  layout and stays at the bottom of the viewport when the page content is short.
  Use the company name, `© 2026 .`, and a Privacy link to `/privacy`.
- Reset-password states are distinct: the email-entry form says
  `Reset your password`, the token/password-entry form says
  `Set your password`, and the sent-instructions state says `Check your email`
  with the server message as subtitle.

## Mobile

- Mobile-first layout
- Bottom navigation / touch-friendly navigation
- Contextual AI Agent inside the current application
- Approval-first interaction
- Quick review cards and bottom-sheet actions

## Workstream

Surface:
- items requiring approval
- AI recommendations
- completed automations
- analytics/prediction insights
- exceptions/errors

## Accessibility

Use clear hierarchy, readable typography, adequate touch targets, keyboard accessibility on web, semantic labels and understandable status indicators.

## UX consistency

Web and mobile should share concepts and terminology, not necessarily identical layouts.
