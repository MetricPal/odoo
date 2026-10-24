"""The structured answer expected from the AI agent, and its strict validation.

Model output is untrusted: it is parsed as JSON, every field is type-checked
and size-limited, unknown keys are ignored, evidence must point at findings
of the same research run. Anything that does not fit is rejected as a whole.
"""

import json
import re

from odoo.addons.marketing_intel.models.strategy import CHANNEL_KEYS, RISK_CATEGORIES

RISK_KEYS = {key for key, _label in RISK_CATEGORIES}
CONFIDENCE_KEYS = ('low', 'medium', 'high')
SWOT_KEYS = ('strengths', 'weaknesses', 'opportunities', 'threats')
MAX_OPTIONS = 4
MAX_RISKS = 10

SCHEMA_TEXT = """{
  "summary": "3-6 short paragraphs: what the evidence means for us",
  "swot": {"strengths": ["..."], "weaknesses": ["..."], "opportunities": ["..."], "threats": ["..."]},
  "options": [
    {"title": "short name", "problem": "problem or opportunity it answers",
     "channels": ["social|messaging|email|sms|event_virtual|event_physical|content|ads|partnership"],
     "audience": "who", "budget": 0, "duration_days": 14,
     "kpis": ["measurable target"], "expected_result": "what success looks like",
     "confidence": "low|medium|high", "evidence": [finding ids], "risks": "risks and compliance notes"}
  ],
  "risks": [
    {"title": "short", "description": "why it matters",
     "category": "market|competitor|compliance|brand|budget|operational",
     "likelihood": 1, "impact": 1, "mitigation": "what to do", "option": null}
  ]
}"""


class InvalidAnswer(ValueError):
    """The answer is not usable; nothing is stored."""


def _text(value, limit, name, required=False):
    if value is None:
        value = ''
    if not isinstance(value, str):
        raise InvalidAnswer(f'"{name}" must be text.')
    value = value.strip()
    if required and not value:
        raise InvalidAnswer(f'"{name}" is missing.')
    return value[:limit]


def _lines(value, name, limit=8, width=300):
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise InvalidAnswer(f'"{name}" must be a list of text.')
    return [item.strip()[:width] for item in value if item.strip()][:limit]


def _int(value, name, low, high, default=None):
    if value is None and default is not None:
        return default
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        raise InvalidAnswer(f'"{name}" must be a whole number.')
    if not low <= value <= high:
        raise InvalidAnswer(f'"{name}" must be between {low} and {high}.')
    return int(value)


def extract_json(text):
    """The JSON object in the answer, tolerating a Markdown fence or a sentence around it."""
    if not isinstance(text, str) or not text.strip():
        raise InvalidAnswer('The answer is empty.')
    fenced = re.search(r'```(?:json)?\s*(\{.*\})\s*```', text, re.S)
    candidate = fenced.group(1) if fenced else text[text.find('{'):text.rfind('}') + 1]
    if not candidate:
        raise InvalidAnswer('The answer has no JSON object.')
    try:
        data = json.loads(candidate)
    except ValueError as error:
        raise InvalidAnswer(f'The answer is not valid JSON ({error.msg}).') from None
    if not isinstance(data, dict):
        raise InvalidAnswer('The answer must be a JSON object.')
    return data


def parse(text, finding_ids):
    """Validated analysis: {summary, swot{4 lists}, options[1-4], risks[0-10]}."""
    data = extract_json(text)
    allowed = set(finding_ids)
    swot = data.get('swot') or {}
    if not isinstance(swot, dict):
        raise InvalidAnswer('"swot" must be an object.')
    result = {
        'summary': _text(data.get('summary'), 6000, 'summary', required=True),
        'swot': {key: _lines(swot.get(key), f'swot.{key}') for key in SWOT_KEYS},
        'options': [],
        'risks': [],
    }
    options = data.get('options')
    if not isinstance(options, list) or not options:
        raise InvalidAnswer('"options" must list at least one campaign option.')
    if len(options) > MAX_OPTIONS:
        raise InvalidAnswer(f'At most {MAX_OPTIONS} options are accepted.')
    for index, option in enumerate(options, 1):
        name = f'options[{index}]'
        if not isinstance(option, dict):
            raise InvalidAnswer(f'"{name}" must be an object.')
        channels = [c for c in _lines(option.get('channels'), f'{name}.channels', limit=9, width=40)
                    if c in CHANNEL_KEYS]
        if not channels:
            raise InvalidAnswer(f'"{name}.channels" needs at least one known channel.')
        budget = option.get('budget', 0)
        if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not 0 <= budget <= 10 ** 9:
            raise InvalidAnswer(f'"{name}.budget" must be a positive number.')
        confidence = option.get('confidence') or 'medium'
        if confidence not in CONFIDENCE_KEYS:
            raise InvalidAnswer(f'"{name}.confidence" must be low, medium or high.')
        evidence = option.get('evidence') or []
        if not isinstance(evidence, list):
            raise InvalidAnswer(f'"{name}.evidence" must be a list of finding ids.')
        result['options'].append({
            'title': _text(option.get('title'), 120, f'{name}.title', required=True),
            'problem': _text(option.get('problem'), 2000, f'{name}.problem'),
            'channels': list(dict.fromkeys(channels)),
            'audience': _text(option.get('audience'), 1000, f'{name}.audience'),
            'budget': float(budget),
            'duration_days': _int(option.get('duration_days'), f'{name}.duration_days', 1, 365, default=14),
            'kpis': _lines(option.get('kpis'), f'{name}.kpis'),
            'expected_result': _text(option.get('expected_result'), 1000, f'{name}.expected_result'),
            'confidence': confidence,
            # Evidence the model cannot point at in this run is dropped, never trusted.
            'evidence': [i for i in evidence if isinstance(i, int) and not isinstance(i, bool) and i in allowed],
            'risks': _text(option.get('risks'), 2000, f'{name}.risks'),
        })
    risks = data.get('risks') or []
    if not isinstance(risks, list):
        raise InvalidAnswer('"risks" must be a list.')
    for index, risk in enumerate(risks[:MAX_RISKS], 1):
        name = f'risks[{index}]'
        if not isinstance(risk, dict):
            raise InvalidAnswer(f'"{name}" must be an object.')
        category = risk.get('category') or 'market'
        if category not in RISK_KEYS:
            raise InvalidAnswer(f'"{name}.category" is not a known category.')
        option = risk.get('option')
        if option is not None:
            option = _int(option, f'{name}.option', 1, len(result['options']))
        result['risks'].append({
            'title': _text(risk.get('title'), 160, f'{name}.title', required=True),
            'description': _text(risk.get('description'), 2000, f'{name}.description'),
            'category': category,
            'likelihood': _int(risk.get('likelihood'), f'{name}.likelihood', 1, 3, default=2),
            'impact': _int(risk.get('impact'), f'{name}.impact', 1, 3, default=2),
            'mitigation': _text(risk.get('mitigation'), 2000, f'{name}.mitigation'),
            'option': option,
        })
    return result
