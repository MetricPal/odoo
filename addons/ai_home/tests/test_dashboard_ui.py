from odoo.tests import HttpCase, tagged


@tagged('post_install', '-at_install')
class TestHomeLayout(HttpCase):
    def test_home_sections_follow_the_design(self):
        self.browser_js('/odoo/action-ai_home.action_ai_home', """
            (async () => {
                for (let i = 0; i < 150 && !document.querySelector('.o_ai_home_attention'); i++) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                const rect = selector => document.querySelector(selector).getBoundingClientRect();
                const left = rect('.o_ai_home_left');
                const center = rect('.o_ai_home_center');
                const right = rect('.o_ai_home_right');
                if (!(left.right < center.left && center.right < right.left)) throw new Error('Three columns side by side');
                if (Math.abs((center.left - left.right) - (right.left - center.right)) > 1) throw new Error('Equal column gaps');
                if (Math.abs(left.bottom - right.bottom) > 1) throw new Error('Side columns reach the same bottom');
                if (!document.querySelector('.o_ai_home_left .o_ai_home_today') || !document.querySelector('.o_ai_home_left .o_ai_home_plan')) throw new Error('Today and My plan are in the left column');
                if (document.querySelector('.o_ai_home_tile')) throw new Error('Live tiles were removed');
                if (document.querySelector('.o_ai_home_quick')) throw new Error('Quick actions were removed');
                if (!document.querySelector('.o_ai_home_composer textarea').disabled) throw new Error('Without an assistant the box is shown disabled');
                if (document.querySelector('.o_ai_home_global_search')) throw new Error('Global search was removed');
                console.log('test successful');
            })();
        """, login='admin', timeout=90)

    def test_mobile_home_has_no_horizontal_overflow(self):
        self.browser_size = '390x844'
        self.browser_js('/odoo/action-ai_home.action_ai_home', """
            (async () => {
                for (let i = 0; i < 150 && !document.querySelector('.o_ai_home_attention'); i++) {
                    await new Promise(resolve => setTimeout(resolve, 100));
                }
                const home = document.querySelector('.o_ai_home');
                if (!home || home.scrollWidth > home.clientWidth + 1) throw new Error('Mobile Home overflows');
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
