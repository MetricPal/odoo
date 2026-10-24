"""Fetch one approved source: HTTPS only, robots.txt respected, bounded size and time.

No logins, no cookies, no cross-host redirects. Returns plain text lines that
are compared week to week; nothing here interprets or acts on the content.
"""

import hashlib
import re
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import requests
from lxml import etree, html

USER_AGENT = 'metricio-research/1.0 (+approved-source collector)'
TIMEOUT = (5, 20)
MAX_BYTES = 2 * 1024 * 1024
MAX_TEXT = 200_000
BLOCKS = ('p', 'div', 'li', 'tr', 'td', 'th', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'section', 'article',
          'header', 'footer', 'blockquote', 'pre', 'dd', 'dt', 'title')


class CollectError(Exception):
    pass


@dataclass
class Result:
    url: str
    status: int
    title: str = ''
    lines: list = field(default_factory=list)
    items: list = field(default_factory=list)  # RSS: [(title, link)]

    @property
    def text(self):
        return '\n'.join(self.lines)[:MAX_TEXT]

    @property
    def digest(self):
        return hashlib.sha256(self.text.encode()).hexdigest()


def _get(url, session):
    host = urlsplit(url).hostname
    for _hop in range(4):
        if urlsplit(url).scheme != 'https':
            raise CollectError('Only HTTPS sources are collected.')
        response = session.get(url, timeout=TIMEOUT, allow_redirects=False, stream=True,
                               headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,application/xml;q=0.9'})
        if response.is_redirect:
            target = urljoin(url, response.headers.get('Location', ''))
            if urlsplit(target).hostname != host:
                raise CollectError(f'Redirected to another site ({urlsplit(target).hostname}); approve that address instead.')
            url = target
            continue
        body = b''
        for chunk in response.iter_content(65536):
            body += chunk
            if len(body) > MAX_BYTES:
                raise CollectError('The page is larger than 2 MB.')
        return url, response.status_code, body, response.headers.get('Content-Type', '')
    raise CollectError('Too many redirects.')


def allowed_by_robots(url, session):
    parts = urlsplit(url)
    robots = f'{parts.scheme}://{parts.netloc}/robots.txt'
    try:
        _url, status, body, _type = _get(robots, session)
    except (CollectError, requests.RequestException):
        return True  # no robots.txt reachable: the site sets no rule
    if status >= 400:
        return True
    parser = robotparser.RobotFileParser()
    parser.parse(body.decode('utf-8', 'replace').splitlines())
    return parser.can_fetch(USER_AGENT, url)


def _page_lines(body):
    tree = html.fromstring(body)
    for bad in tree.xpath('//script|//style|//noscript|//svg|//template'):
        bad.drop_tree()
    title = (tree.findtext('.//title') or '').strip()
    for node in tree.iter(*BLOCKS):
        node.text = '\n' + (node.text or '')
        node.tail = '\n' + (node.tail or '')
    body = tree.find('.//body')
    text = (body if body is not None else tree).text_content()
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.splitlines()]
    return title, [line for line in lines if len(line) > 2]


def _feed_items(body):
    root = etree.fromstring(body, parser=etree.XMLParser(resolve_entities=False, no_network=True, recover=True))
    items = []
    for node in root.iter('{*}item', '{*}entry'):
        title = (node.findtext('{*}title') or '').strip()
        link = (node.findtext('{*}link') or '').strip()
        if not link:
            element = node.find('{*}link')
            link = element.get('href', '') if element is not None else ''
        if title or link:
            items.append((title, link))
    title = (root.findtext('.//{*}title') or '').strip()
    return title, items[:100]


def fetch(url, kind='page', session=None):
    """Collect ``url``. Raises CollectError with a readable reason."""
    session = session or requests.Session()
    if urlsplit(url).scheme != 'https' or not urlsplit(url).hostname:
        raise CollectError('Use a full HTTPS address, e.g. https://example.com/pricing')
    if not allowed_by_robots(url, session):
        raise CollectError("The site's robots.txt does not allow automated collection of this page.")
    try:
        final_url, status, body, _type = _get(url, session)
    except requests.RequestException as error:
        raise CollectError(f'The site could not be reached ({type(error).__name__}).') from None
    if status >= 400:
        raise CollectError(f'The site answered with error {status}.')
    if kind == 'rss':
        title, items = _feed_items(body)
        return Result(final_url, status, title, [f'{t} — {l}' for t, l in items], items)
    title, lines = _page_lines(body)
    return Result(final_url, status, title, lines)
