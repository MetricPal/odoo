from odoo.tests import HttpCase, tagged
from odoo.tests.common import ChromeBrowser


@tagged('post_install', '-at_install')
class TestHomeLayout(HttpCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        for section in ('attention', 'automation', 'recent'):
            for index in range(8):
                cls.env['ai.home.item'].create({
                    'name': f'{section.title()} {index + 1}',
                    'section': section,
                    'subtitle': 'Existing work item',
                    'occurred_label': 'Today',
                })

    def test_home_columns_and_composer(self):
        original = ChromeBrowser._handle_console
        def capture(browser, type, args=None, **kwargs):
            if args and args[0].get('value') == 'home_layout_preview':
                browser.take_screenshot(prefix='home_layout_')
            return original(browser, type, args=args, **kwargs)
        self.patch(ChromeBrowser, '_handle_console', capture)
        self.browser_js('/odoo/action-ai_home.action_ai_home', """
            (async () => {
                const wait = async predicate => {
                    for (let i = 0; i < 150; i++) {
                        if (predicate()) return;
                        await new Promise(resolve => setTimeout(resolve, 100));
                    }
                    throw new Error('Home did not render');
                };
                await wait(() => document.querySelector('.o_ai_home_composer'));
                const rect = selector => document.querySelector(selector).getBoundingClientRect();
                const left = rect('.o_ai_home_left');
                const center = rect('.o_ai_home_center');
                const right = rect('.o_ai_home_right');
                if (!(left.right <= center.left && center.right <= right.left)) throw new Error('Desktop columns overlap');
                if (rect('.o_ai_home_automations').bottom > rect('.o_ai_home_recent').top) throw new Error('Recent must follow automations');
                const composer = rect('.o_ai_home_composer');
                if (composer.left < center.left - 1 || composer.right > center.right + 1) throw new Error('Composer must sit under the center column');
                if (composer.bottom > window.innerHeight + 1) throw new Error('Composer must be visible without scrolling');
                if (center.bottom > composer.top + 1) throw new Error('Center content must end above the composer');
                if (document.querySelector('.o_ai_home_favorites')) throw new Error('Favorites were removed');
                const titles = ['#ai_home_mywork_title', '#ai_home_automations_title', '#ai_home_recent_title']
                    .map(selector => rect(selector).top);
                const scrollers = [...document.querySelectorAll('.o_ai_home_scroll, .o_ai_home_left, .o_ai_home_center, .o_ai_home_right, .o_ai_home')];
                for (const element of scrollers) element.scrollTop = 10000;
                await new Promise(resolve => setTimeout(resolve, 100));
                const after = rect('.o_ai_home_composer');
                if (Math.abs(after.top - composer.top) > 0.5) throw new Error(`Composer moved while scrolling (${composer.top} -> ${after.top})`);
                ['#ai_home_mywork_title', '#ai_home_automations_title', '#ai_home_recent_title'].forEach((selector, index) => {
                    if (Math.abs(rect(selector).top - titles[index]) > 0.5) throw new Error(`${selector} scrolled away`);
                });
                const automations = document.querySelector('.o_ai_home_automations .o_ai_home_panel');
                if (automations.scrollTop === 0) throw new Error('Automation rows must scroll inside their section');
                const rightColumn = rect('.o_ai_home_right');
                if (rect('.o_ai_home_recent').bottom > rightColumn.bottom + 1) throw new Error('Recent must stay visible on desktop');
                if (rect('.o_ai_home_recent').height < 100) throw new Error('Recent must keep room for its rows');
                for (const element of scrollers) element.scrollTop = 0;
                document.querySelector('.o_ai_home_add').click();
                await wait(() => document.querySelector('.o_ai_home_prepare'));
                document.querySelector('.o_ai_home_prepare').click();
                await wait(() => document.querySelector('#ai_home_prompt').value.startsWith('Prepare an approval'));
                if (!document.querySelector('.o_ai_home_ask_send').disabled) throw new Error('Request enabled without selected agent');
                console.log('home_layout_preview');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_mobile_home_has_no_horizontal_overflow(self):
        self.browser_size = '390x844'
        self.browser_js('/odoo/action-ai_home.action_ai_home', """
            (async () => {
                for (let i=0;i<150;i++) {
                    if (document.querySelector('.o_ai_home_composer')) break;
                    await new Promise(resolve => setTimeout(resolve,100));
                }
                const home = document.querySelector('.o_ai_home');
                if (!home || home.scrollWidth > home.clientWidth + 1) throw new Error('Mobile Home overflows');
                home.scrollTop = home.scrollHeight / 2;
                await new Promise(resolve => setTimeout(resolve, 100));
                const composer = document.querySelector('.o_ai_home_composer').getBoundingClientRect();
                const visible = home.getBoundingClientRect();
                if (Math.abs(composer.bottom - visible.bottom) > 1) throw new Error('Mobile composer must stay at the bottom');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_home_javascript(self):
        module_hash = 0
        for char in '@ai_home/dashboard':
            module_hash = ((module_hash << 5) - module_hash + ord(char)) & 0xFFFFFFFF
        self.browser_js(
            f'/web/tests?headless&loglevel=2&preset=desktop&timeout=15000&id={module_hash:08x}',
            '', login='admin', timeout=180,
            success_signal='[HOOT] Test suite succeeded',
        )
