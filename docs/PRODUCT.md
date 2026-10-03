# Product Principles

## Vision

Build an AI-native Odoo ERP where the system performs most routine business work and humans supervise, review, approve, and govern.

## Core principle

> Humans supervise. Machines work.

## Experience model

Move from application-centric ERP usage toward work-centric interaction:

- The system surfaces what needs attention.
- Workflows execute predictable processes.
- AI/LLMs reason, summarize, draft, classify, and recommend.
- Analytics/prediction identifies trends, risks, and forecasts.
- Humans review important decisions and approve state-changing actions.

## User types

The experience must distinguish:

- Internal users: staff, managers, administrators.
- Portal users: customers, candidates, partners, external participants.
- Public users: unauthenticated/public website interactions.

User type, role, permissions, relationship, company, record rules, and application context jointly determine what the user and agent can see/do.

## Product UX

Primary concepts:

- My Work / AI Workstream
- Approval Center
- Contextual AI Agent
- App Launcher / Anchored Floating Command Panel on web
- Mobile-first navigation on mobile
- Automation Center
- Activity/audit timeline
- Analytics and prediction insights

The UI should minimize manual navigation and data entry where safe.

## AI behavior

AI should learn patterns from interaction, but learning a pattern never grants permission.

AI may propose an automation such as:
- recurring review
- report preparation
- follow-up drafting
- classification
- anomaly detection
- recommendation

The user can review and approve the automation/policy before it becomes active.

## Design goal

The user should usually be able to:
Review → Understand → Approve/Reject → Done.
