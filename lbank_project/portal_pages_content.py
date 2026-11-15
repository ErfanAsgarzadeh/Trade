"""Copy for the server-rendered public pages (trust pages and product pages), in Persian and English.
Each page: title (<=60 chars), description (<=160), h1, lead, sections [(heading, [paragraph | [bullets]])], and for product
pages a call to action. Nothing here describes how the bots trade; results and risk controls are described in general terms."""

CONTENT = {}

CONTENT['about'] = dict(
    fa=dict(title='دربارهٔ آوینا | ربات معامله‌گر هوشمند', description='آوینا چیست و چگونه کار می‌کند: سرویس سیگنال و معاملهٔ خودکار فیوچرز، با سرمایه در حساب صرافی خودتان و بدون تضمین سود.',
            h1='دربارهٔ آوینا', lead='آوینا یک سرویس آنلاین برای معامله در بازار فیوچرز ارز دیجیتال است که از خانوادهٔ ARTAX ارائه می‌شود.',
            sections=[('آوینا چه می‌کند', ['آوینا سه ربات معامله‌گر دارد: شاهین، موج‌سوار و ققنوس. هر سه با هم روی یک حساب کار می‌کنند و هدفشان معامله با قاعده و مدیریت ریسک خودکار است. شما می‌توانید فقط سیگنال بگیرید و خودتان تصمیم بگیرید، یا اتصال حساب صرافی را برای معاملهٔ خودکار آماده کنید.',
                                                'روش معامله‌ی ربات‌ها منتشر نمی‌شود، اما نتایج را می‌توانید ببینید: بک‌تست پنج‌ساله با دادهٔ روزانه و روش محاسبه، و یک آزمون پیشرو (کاغذی) که هر روز به‌روز می‌شود.']),
                      ('چگونه کار می‌کند', [['حساب می‌سازید و پلن متناسب با سرمایه‌تان را انتخاب می‌کنید.', 'با USDT یا USDC پرداخت می‌کنید و پس از تأیید پرداخت، پلن فعال می‌شود.', 'سیگنال‌ها در پنل و ربات تلگرام می‌رسند.', 'برای معاملهٔ خودکار، کلید API فقط‌خواندنی صرافی را وصل می‌کنید؛ سرمایه همیشه در حساب خودتان می‌ماند.']]),
                      ('آنچه نمی‌گوییم', ['ما سود تضمین نمی‌کنیم. معامله در فیوچرز ریسک از دست دادن سرمایه دارد و نتایج گذشته آینده را تضمین نمی‌کند. اطلاعات این سایت توصیهٔ سرمایه‌گذاری نیست.']),
                      ('ارتباط', ['راه‌های تماس در صفحهٔ تماس آمده است.'])]),
    en=dict(title='About Avina | Smart Crypto Futures Trading Bot', description='What Avina is and how it works: a signal and automated futures-trading service where your funds stay in your own exchange account. No profit guaranteed.',
            h1='About Avina', lead='Avina is an online service for crypto futures trading, offered by the ARTAX family.',
            sections=[('What Avina does', ['Avina runs three trading bots: Falcon, Wave Rider and Phoenix. They work together on one account, aiming for rule-based trading with automatic risk management. You can take signals only and decide yourself, or prepare an exchange connection for automated trading.',
                                           'How the bots trade is not published, but you can see the results: a five-year backtest with daily data and its calculation method, and a forward (paper) test that updates every day.']),
                      ('How it works', [['You create an account and choose a plan that fits your capital.', 'You pay in USDT or USDC and the plan is activated once the payment is confirmed.', 'Signals arrive in your panel and in the Telegram bot.', 'For automated trading you connect a read-only exchange API key; your funds always stay in your own account.']]),
                      ('What we do not say', ['We do not guarantee profit. Futures trading carries the risk of losing capital and past results do not guarantee the future. Nothing on this site is investment advice.']),
                      ('Contact', ['Ways to reach us are on the contact page.'])]))

CONTENT['contact'] = dict(
    fa=dict(title='تماس با آوینا | پشتیبانی و راه‌های ارتباط', description='راه‌های تماس با پشتیبانی آوینا: ایمیل و تلگرام. برای مشکلات حساب، پرداخت و اتصال صرافی از این راه‌ها استفاده کنید.',
            h1='تماس با آوینا', lead='برای پرسش دربارهٔ حساب، پرداخت یا اتصال صرافی با ما در ارتباط باشید.',
            sections=[('نکات پیش از تماس', [['هرگز رمز عبور، کد دومرحله‌ای یا کلید خصوصی صرافی را برای کسی نفرستید؛ پشتیبانی آوینا این‌ها را نمی‌پرسد.', 'نام کاربری و شمارهٔ سفارش یا مرجع تراکنش را همراه پیام بنویسید.', 'بازپرداخت‌ها به‌صورت دستی بررسی می‌شوند.']])]),
    en=dict(title='Contact Avina | Support and How to Reach Us', description='How to contact Avina support by e-mail and Telegram for account, payment and exchange-connection questions.',
            h1='Contact Avina', lead='Get in touch about your account, a payment or an exchange connection.',
            sections=[('Before you write', [['Never send anyone your password, two-step code or an exchange private key; Avina support never asks for these.', 'Include your username and the order number or transaction reference.', 'Refunds are reviewed manually.']])]))

CONTENT['terms'] = dict(
    fa=dict(title='شرایط استفاده از خدمات آوینا', description='شرایط استفاده از سرویس آوینا: حساب کاربری، پلن‌ها و پرداخت با USDT/USDC، بازپرداخت دستی، مسئولیت کلید API و سلب تضمین سود.',
            h1='شرایط استفاده از خدمات', lead='با ساخت حساب یا خرید پلن، این شرایط را می‌پذیرید. متن ساده و کوتاه نوشته شده است.',
            sections=[('۱. خدمات', ['آوینا سیگنال معاملاتی و ابزار اتصال به حساب صرافی ارائه می‌دهد. موتور معاملهٔ خودکار در حال حاضر در مرحلهٔ آزمایشی است و ممکن است سفارش واقعی ثبت نکند؛ وضعیت فعلی در پنل نمایش داده می‌شود.']),
                      ('۲. حساب کاربری', ['شما مسئول نگهداری رمز عبور و ورود دومرحله‌ای خود هستید. هر حساب برای یک نفر است. در صورت سوءاستفاده یا نقض این شرایط می‌توانیم دسترسی را متوقف کنیم.']),
                      ('۳. پلن‌ها و پرداخت', ['پرداخت با USDT یا USDC به کیف پول اعلام‌شدهٔ اپراتور انجام می‌شود. پلن پس از تأیید پرداخت فعال می‌شود. قیمت‌ها و وضعیت فروش در پنل نمایش داده می‌شود و ممکن است تغییر کند؛ تغییر قیمت بر سفارش‌های پرداخت‌شده اثر ندارد.']),
                      ('۴. بازپرداخت', ['بازپرداخت‌ها به‌صورت دستی بررسی می‌شوند. برای درخواست بازپرداخت با پشتیبانی تماس بگیرید. اعتبار معرفی (ریفرال) قابل تبدیل به پول نقد نیست و فقط برای خرید پلن به کار می‌رود.']),
                      ('۵. کلید API صرافی', ['شما مسئول مجوزهای کلیدی هستید که می‌سازید. کلید باید فقط خواندنی باشد و مجوز برداشت نداشته باشد؛ کلیدی که مجوز برداشت داشته باشد پذیرفته نمی‌شود. ما هیچ‌گاه سرمایهٔ شما را نگه نمی‌داریم.']),
                      ('۶. بدون تضمین سود', ['هیچ سود یا نتیجه‌ای تضمین نمی‌شود. نتایج بک‌تست و آزمون کاغذی شبیه‌سازی‌اند و ممکن است با معامله با پول واقعی تفاوت داشته باشند. معامله ریسک از دست دادن سرمایه دارد.']),
                      ('۷. محدودیت مسئولیت', ['تا حدی که قانون اجازه می‌دهد، آوینا مسئول زیان معاملاتی، قطع دسترسی به صرافی یا خطای داده‌های شخص ثالث نیست. سرویس «همان‌گونه که هست» ارائه می‌شود و ممکن است موقتاً در دسترس نباشد.']),
                      ('۸. تغییر شرایط', ['ممکن است این شرایط را به‌روز کنیم. نسخهٔ جاری همین صفحه است.'])]),
    en=dict(title='Terms of Service | Avina', description='Terms for using Avina: accounts, plans and USDT/USDC payment, manual refunds, API key responsibility and no guarantee of profit.',
            h1='Terms of service', lead='By creating an account or buying a plan you accept these terms. They are written in plain language.',
            sections=[('1. The service', ['Avina provides trading signals and tools to connect an exchange account. The automated trading engine is currently in trial and may not place real orders; the current status is shown in your panel.']),
                      ('2. Your account', ['You are responsible for your password and two-step login. Each account is for one person. We may suspend access for abuse or breach of these terms.']),
                      ('3. Plans and payment', ['Payment is made in USDT or USDC to the operator wallet shown to you. A plan is activated after the payment is confirmed. Prices and sales status are shown in your panel and may change; a change does not affect orders already paid.']),
                      ('4. Refunds', ['Refunds are reviewed manually; contact support to ask for one. Referral credits cannot be redeemed for cash and are used only toward plans.']),
                      ('5. Exchange API keys', ['You are responsible for the permissions of the keys you create. A key must be read-only with no withdrawal permission; a key that can withdraw is refused. We never hold your funds.']),
                      ('6. No guarantee of profit', ['No profit or result is guaranteed. Backtest and paper-trading results are simulations and can differ from trading real money. Trading carries the risk of losing capital.']),
                      ('7. Limit of liability', ['To the extent the law allows, Avina is not liable for trading losses, loss of access to an exchange or errors in third-party data. The service is provided as is and may be unavailable at times.']),
                      ('8. Changes', ['We may update these terms. The current version is this page.'])]))

CONTENT['privacy'] = dict(
    fa=dict(title='سیاست حریم خصوصی آوینا', description='آوینا چه داده‌هایی نگه می‌دارد: نام کاربری، ایمیل، رمز هش‌شده، کلید API رمزنگاری‌شده، مرجع پرداخت و لاگ دسترسی ۳۰ روزه.',
            h1='سیاست حریم خصوصی', lead='این صفحه می‌گوید چه داده‌ای جمع می‌کنیم، برای چه و تا کی نگه می‌داریم.',
            sections=[('داده‌هایی که نگه می‌داریم', [['نام کاربری و ایمیل شما.', 'رمز عبور فقط به‌صورت هش (نه متن اصلی).', 'کلیدهای API صرافی، رمزنگاری‌شده؛ فقط برای خواندن موجودی و موقعیت‌ها.', 'اتصال اختیاری تلگرام (شناسهٔ گفت‌وگو و نام کاربری).', 'مرجع تراکنش‌های پرداخت و سفارش‌ها.', 'نشانی IP برای محدودکردن نرخ درخواست و لاگ دسترسی که حداکثر ۳۰ روز نگه داشته می‌شود.']]),
                      ('چرا', ['برای ساخت حساب، ارائهٔ سیگنال، تأیید پرداخت، امنیت و جلوگیری از سوءاستفاده. آنچه نگه داشته می‌شود را برای تبلیغات فروخته نمی‌شود و در این سایت از ردیاب‌ها یا سرویس‌های تحلیلی بیرونی استفاده نمی‌کنیم.']),
                      ('اشتراک با دیگران', ['داده‌های حساب شما را نمی‌فروشیم. اطلاعات لازم برای خواندن حساب فقط با صرافی که خودتان انتخاب کرده‌اید رد‌وبدل می‌شود و پیام‌های تلگرام از طریق تلگرام می‌رسند.']),
                      ('حذف و اصلاح', ['برای اصلاح یا حذف حساب با پشتیبانی تماس بگیرید. می‌توانید هر زمان کلید صرافی را از پنل قطع کنید. برخی سوابق پرداخت برای حسابداری و رسیدگی به اختلاف نگه داشته می‌شوند.']),
                      ('کوکی‌ها', ['فقط یک کوکی نشست لازم برای ورود استفاده می‌شود.'])]),
    en=dict(title='Privacy Policy | Avina', description='What data Avina keeps: username, e-mail, hashed password, encrypted exchange API keys, payment references and access logs kept for 30 days.',
            h1='Privacy policy', lead='This page says what data we collect, why, and how long we keep it.',
            sections=[('Data we keep', [['Your username and e-mail address.', 'Your password only as a hash, never in plain text.', 'Exchange API keys, encrypted; used only to read balances and positions.', 'An optional Telegram link (chat ID and username).', 'Payment transaction references and orders.', 'IP addresses for rate limiting, and access logs kept for at most 30 days.']]),
                      ('Why', ['To create your account, deliver signals, confirm payments, keep the service secure and prevent abuse. We do not sell data, and this site loads no external trackers or analytics.']),
                      ('Sharing', ['We do not sell your account data. Information needed to read your account goes only to the exchange you chose, and Telegram messages travel through Telegram.']),
                      ('Deletion and correction', ['Contact support to correct or delete your account. You can disconnect your exchange key from your panel at any time. Some payment records are kept for accounting and dispute handling.']),
                      ('Cookies', ['Only one session cookie, needed for sign-in, is used.'])]))

CONTENT['risk'] = dict(
    fa=dict(title='اعلام ریسک معامله | آوینا', description='معاملهٔ فیوچرز ریسک از دست دادن سرمایه دارد. اعلام ریسک آوینا: اهرم، بک‌تست و آزمون کاغذی، کلید API و نبود تضمین سود.',
            h1='اعلام ریسک', lead='پیش از استفاده از هر سیگنال یا ربات، این موارد را بخوانید.',
            sections=[('زیان ممکن است', ['معامله با اهرم در فیوچرز می‌تواند در مدت کوتاه به زیان‌های بزرگ و حتی از دست رفتن کل سرمایهٔ معامله منجر شود. فقط با پولی معامله کنید که تحمل از دست دادنش را دارید.']),
                      ('نتایج گذشته تضمین نیستند', ['بک‌تست روی داده‌های گذشته ساخته می‌شود و ممکن است خوش‌بینانه باشد. آزمون پیشرو (کاغذی) پول واقعی ندارد و هزینه‌هایی مانند لغزش قیمت و فاندینگ را کامل نشان نمی‌دهد. هیچ‌کدام تضمین سود آینده نیستند.']),
                      ('ریسک اجرا و فنی', ['قطع اینترنت، خطای صرافی، تغییر قوانین صرافی، تأخیر در اجرای سفارش و لغزش قیمت می‌توانند نتیجه را تغییر دهند. حد ضرر هم ممکن است در بازار پرنوسان با قیمت بدتر اجرا شود.']),
                      ('مسئولیت کلید API', ['کلید صرافی را فقط‌خواندنی و بدون مجوز برداشت بسازید و در صورت امکان آدرس‌های مجاز (IP) را محدود کنید. مسئولیت مجوزهای کلید با شماست.']),
                      ('بدون توصیهٔ سرمایه‌گذاری', ['آوینا سرمایهٔ شما را نگه نمی‌دارد و مشاور مالی نیست. تصمیم نهایی و مسئولیت آن با شماست.'])]),
    en=dict(title='Risk Disclosure | Avina', description='Futures trading can lose your capital. Avina risk disclosure: leverage, backtests and paper trading, API keys and no guarantee of profit.',
            h1='Risk disclosure', lead='Read this before you use any signal or bot.',
            sections=[('You can lose money', ['Leveraged futures trading can lead to large losses in a short time, up to the loss of the whole trading capital. Trade only with money you can afford to lose.']),
                      ('Past results are not a guarantee', ['A backtest is built on past data and can be optimistic. A forward (paper) test uses no real money and does not fully show costs such as slippage and funding. Neither guarantees future profit.']),
                      ('Execution and technical risk', ['Connection failures, exchange errors, changes to exchange rules, order delays and slippage can change the outcome. A stop-loss can also fill at a worse price in a fast market.']),
                      ('API key responsibility', ['Create exchange keys as read-only with no withdrawal permission and, where possible, restrict allowed IP addresses. You are responsible for your key permissions.']),
                      ('Not investment advice', ['Avina does not hold your funds and is not a financial adviser. The final decision and its consequences are yours.'])]))

CONTENT['pricing'] = dict(
    fa=dict(title='قیمت و پلن‌های آوینا | سیگنال و معاملهٔ خودکار', description='پلن‌های آوینا بر اساس سرمایهٔ حساب و مدت: فقط سیگنال یا معاملهٔ خودکار، پرداخت با USDT یا USDC، فعال‌سازی پس از تأیید پرداخت.',
            h1='قیمت و پلن‌های آوینا', lead='قیمت هر پلن به سقف سرمایهٔ حساب و مدت اشتراک بستگی دارد. جدول‌ها قیمت فعلی را به دلار آمریکا نشان می‌دهند.',
            sections=[('چگونه پلن انتخاب کنم؟', ['دو محصول داریم: «فقط سیگنال» برای کسی که خودش معامله می‌کند و «معاملهٔ خودکار» که مجوز اتصال حساب و مدیریت معاملات را هم شامل می‌شود. سقف سرمایه را بر اساس موجودی حساب معاملاتی‌تان انتخاب کنید؛ اگر سرمایه‌تان رشد کرد می‌توانید ارتقا بدهید.',
                                                       'مدت‌های ۱، ۳ و ۶ ماهه داریم. مدت بلندتر معمولاً ماهانهٔ ارزان‌تری دارد. پرداخت با USDT یا USDC روی شبکهٔ TRON یا BNB Smart Chain انجام می‌شود و پلن پس از تأیید پرداخت فعال می‌شود.']),
                      ('پیش از خرید', ['نتایج بک‌تست و آزمون پیشرو را ببینید، صفحهٔ اعلام ریسک را بخوانید و بدانید که هیچ سودی تضمین نمی‌شود. بازپرداخت‌ها دستی بررسی می‌شوند.'])],
            faq=[('آیا سرمایه‌ام را شما نگه می‌دارید؟', 'خیر. سرمایه همیشه در حساب صرافی خودتان می‌ماند و آوینا فقط با کلید فقط‌خواندنی موجودی را می‌خواند.'),
                 ('با چه ارزی پرداخت می‌کنم؟', 'با USDT یا USDC روی شبکه‌هایی که در صفحهٔ پرداخت پنل نشان داده می‌شود.'),
                 ('اگر سرمایه‌ام بیشتر شد چه؟', 'پلن ارتقا می‌یابد؛ سقف سرمایهٔ پلن شما باید به موجودی حساب بخورد.'),
                 ('آیا سود تضمین می‌شود؟', 'خیر. معامله در فیوچرز ریسک از دست دادن سرمایه دارد و هیچ نتیجه‌ای تضمین نمی‌شود.')]),
    en=dict(title='Avina Pricing and Plans | Signals and Auto Trading', description='Avina plans by account capital and term: signals only or automated trading, paid in USDT or USDC and activated once payment is confirmed.',
            h1='Avina pricing and plans', lead='The price of a plan depends on the capital cap of the account and the term. The tables below show current prices in US dollars.',
            sections=[('How do I choose a plan?', ['There are two products: Signals only, for people who trade themselves, and Automated trading, which also licenses connecting your account and managing trades. Pick the capital cap from the balance of your trading account; if your capital grows you can upgrade.',
                                                  'Terms are 1, 3 and 6 months. A longer term usually has a lower monthly cost. You pay in USDT or USDC on TRON or BNB Smart Chain and the plan is activated once the payment is confirmed.']),
                      ('Before you buy', ['Look at the backtest and forward-test results, read the risk disclosure and remember that no profit is guaranteed. Refunds are reviewed manually.'])],
            faq=[('Do you hold my funds?', 'No. Your funds always stay in your own exchange account and Avina only reads balances with a read-only key.'),
                 ('Which currency do I pay in?', 'USDT or USDC on the networks shown on the payment page in your panel.'),
                 ('What if my capital grows?', 'You upgrade your plan; its capital cap needs to match your account balance.'),
                 ('Is profit guaranteed?', 'No. Futures trading carries the risk of losing capital and no result is guaranteed.')]))

CONTENT['signals'] = dict(
    fa=dict(title='سیگنال معاملاتی فیوچرز آوینا | ورود، حد ضرر، هدف', description='اشتراک سیگنال آوینا: ورود پیشنهادی، حد ضرر و زمان اعتبار در پنل و تلگرام، بدون نیاز به کلید صرافی. تصمیم و اجرا با خودتان است.',
            h1='سیگنال معاملاتی آوینا', lead='سیگنال‌های ربات‌های آوینا را در پنل و تلگرام دریافت کنید و خودتان تصمیم بگیرید. بدون نیاز به کلید صرافی.',
            sections=[('اشتراک سیگنال چه چیزی دارد؟', [['ورود پیشنهادی، حد ضرر و، در صورت تعریف، هدف هر سیگنال.', 'زمان اعتبار هر سیگنال؛ پس از انقضا، سیگنال منقضی‌شده علامت می‌خورد.', 'نام ربات سازنده: شاهین، موج‌سوار یا ققنوس.', 'مشاهده در پنل و اعلان در ربات تلگرام (اختیاری).']]),
                      ('سیگنال‌ها چگونه می‌رسند؟', ['وقتی یکی از ربات‌ها شرایط معامله را ببیند، سیگنال در پنل شما ثبت می‌شود. اگر تلگرام را وصل کرده باشید، همان سیگنال به گفت‌وگوی شما هم ارسال می‌شود. سیگنال‌ها فقط پیشنهادند؛ آوینا سفارشی از طرف شما ثبت نمی‌کند.',
                                                   'برای اتصال تلگرام در پنل یک کد یک‌بارمصرف می‌گیرید و به ربات می‌فرستید. هر زمان بخواهید اعلان‌ها را خاموش یا اتصال را قطع می‌کنید.']),
                      ('این سرویس برای چه کسی مناسب است؟', ['برای کسی که خودش پشت صفحه معامله می‌کند و می‌خواهد ایدهٔ ورود و حد ضرر مشخص داشته باشد؛ کسی که نمی‌خواهد کلید صرافی را به سرویسی بدهد؛ و برای کسی که می‌خواهد پیش از معاملهٔ خودکار، سیگنال‌ها را مدتی دنبال کند.',
                                                          'اگر وقت یا حوصلهٔ دنبال کردن بازار را ندارید، معاملهٔ خودکار را ببینید. در هر دو حالت حد ضرر بخش مهمی از مدیریت ریسک است و باید خودتان اندازهٔ معامله را متناسب با سرمایه‌تان انتخاب کنید.']),
                      ('پیش از شروع', ['نتایج بک‌تست و آزمون پیشرو شبیه‌سازی‌اند و سود آینده را تضمین نمی‌کنند. معامله در فیوچرز ریسک از دست دادن سرمایه دارد؛ اعلام ریسک را بخوانید.'])],
            links=[('pricing', 'دیدن قیمت‌ها'), ('auto-trading', 'معاملهٔ خودکار'), ('forward-test', 'نتایج آزمون پیشرو')]),
    en=dict(title='Avina Futures Trading Signals | Entry, Stop, Target', description='Avina signal subscription: suggested entry, stop-loss and validity window in your panel and on Telegram, with no exchange key needed. You decide and trade.',
            h1='Avina trading signals', lead='Receive signals from the Avina bots in your panel and on Telegram, and decide for yourself. No exchange key needed.',
            sections=[('What the signal subscription includes', [['A suggested entry, a stop-loss and, where defined, a target for every signal.', 'A validity window for each signal; after it ends the signal is marked expired.', 'The bot that produced it: Falcon, Wave Rider or Phoenix.', 'Viewing in your panel and notifications in the Telegram bot (optional).']]),
                                                          ('How signals are delivered', ['When one of the bots sees a setup, the signal appears in your panel. If you have linked Telegram, the same signal is also sent to your chat. Signals are suggestions only; Avina never places an order on your behalf.',
                                                                                         'To link Telegram you get a one-time code in your panel and send it to the bot. You can turn notifications off or unlink at any time.']),
                                                          ('Who it suits', ['It suits people who trade by hand and want a clear idea of entry and stop; people who do not want to give an exchange key to a service; and people who want to follow the signals for a while before considering automated trading.',
                                                                            'If you do not have the time to follow the market, look at automated trading. Either way, a stop-loss is an important part of risk management and you must size each trade to your own capital.']),
                                                          ('Before you start', ['Backtest and forward-test results are simulations and do not guarantee future profit. Futures trading carries the risk of losing capital; read the risk disclosure.'])],
            links=[('pricing', 'See pricing'), ('auto-trading', 'Automated trading'), ('forward-test', 'Forward-test results')]))

CONTENT['auto-trading'] = dict(
    fa=dict(title='معاملهٔ خودکار آوینا | اتصال صرافی با کلید امن', description='معاملهٔ خودکار آوینا: اتصال حساب صرافی با کلید API فقط‌خواندنی، ایمنی کلید و کنترل‌های ریسک. سرمایهٔ شما در حساب خودتان می‌ماند.',
            h1='معاملهٔ خودکار با آوینا', lead='حساب صرافی خود را با کلید API امن وصل کنید و مدیریت ریسک را به قاعده بسپارید؛ سرمایه همیشه در حساب خودتان می‌ماند.',
            sections=[('اتصال حساب صرافی چگونه است؟', [['در صرافی یک کلید API می‌سازید.', 'فقط مجوز خواندن را فعال می‌کنید؛ مجوز برداشت را هرگز.', 'کلید را در پنل آوینا وارد می‌کنید؛ سرویس موجودی و موقعیت‌ها را فقط می‌خواند و وضعیت اتصال را نشان می‌دهد.', 'هر زمان بخواهید اتصال را قطع می‌کنید.']]),
                      ('ایمنی کلید API', ['کلیدها رمزنگاری‌شده ذخیره می‌شوند و کلید رمزنگاری جدا از پایگاه داده نگه داشته می‌شود. اگر صرافی گزارش دهد کلید اجازهٔ برداشت دارد، کلید رد و پاک می‌شود. در صرافی‌هایی که این گزارش را نمی‌دهند، باید در فرم تأیید کنید که کلید مجوز برداشت ندارد. توصیه می‌کنیم آدرس‌های مجاز (IP) را هم در صرافی محدود کنید و ورود دومرحله‌ای را در آوینا روشن کنید.']),
                      ('کنترل‌های ریسک', ['ربات‌ها برای هر معامله حد ضرر دارند و اندازهٔ هر معامله بر اساس ریسک مجاز نسبت به سرمایه تعیین می‌شود. سقف مجموع سرمایهٔ درگیر و حد زیان روزانه وجود دارد و مدیریت ریسک بین سه ربات مشترک است. جزئیات و پارامترها منتشر نمی‌شود.']),
                      ('وضعیت فعلی', ['موتور معاملهٔ خودکار در حال حاضر آزمایشی است و سفارش واقعی به صرافی ارسال نمی‌کند؛ اتصال فقط‌خواندنی برای آماده‌سازی و نمایش وضعیت حساب است. نتایج در صفحهٔ آزمون پیشرو به‌صورت کاغذی منتشر می‌شود.']),
                      ('ریسک', ['معامله ریسک از دست دادن سرمایه دارد و هیچ سودی تضمین نمی‌شود. پیش از استفاده اعلام ریسک را بخوانید.'])],
            links=[('exchanges', 'صرافی‌های پشتیبانی‌شده'), ('pricing', 'قیمت‌ها'), ('risk', 'اعلام ریسک')]),
    en=dict(title='Avina Automated Trading | Connect an Exchange Safely', description='Avina automated trading: connect your exchange with a read-only API key, API key safety and risk controls. Your funds stay in your own account.',
            h1='Automated trading with Avina', lead='Connect your exchange account with a safe API key and leave risk management to rules. Your funds always stay in your own account.',
            sections=[('How connecting an exchange works', [['You create an API key at your exchange.', 'You enable read permission only and never withdrawal permission.', 'You enter the key in your Avina panel; the service only reads balances and positions and shows the connection status.', 'You can disconnect at any time.']]),
                      ('API key safety', ['Keys are stored encrypted and the encryption key is kept apart from the database. If an exchange reports that a key can withdraw, the key is refused and wiped. For exchanges that do not report this, you confirm in the form that the key has no withdrawal permission. We also recommend restricting allowed IP addresses at the exchange and turning on two-step login in Avina.']),
                      ('Risk controls', ['Every trade has a stop-loss, and the size of each trade is set from an allowed risk relative to capital. There is a cap on total capital engaged and a daily loss limit, and risk management is shared across the three bots. Details and parameters are not published.']),
                      ('Current status', ['The automated trading engine is currently in trial and does not send real orders to the exchange; the read-only connection prepares your account and shows its status. Results are published as paper trading on the forward-test page.']),
                      ('Risk', ['Trading carries the risk of losing capital and no profit is guaranteed. Read the risk disclosure before you use the service.'])],
            links=[('exchanges', 'Supported exchanges'), ('pricing', 'Pricing'), ('risk', 'Risk disclosure')]))

CONTENT['exchanges'] = dict(
    fa=dict(title='صرافی‌های پشتیبانی‌شده آوینا', description='فهرست صرافی‌هایی که آوینا می‌تواند با کلید API فقط‌خواندنی به آن‌ها وصل شود: بازارهای اسپات و فیوچرز و نیازهای اتصال.',
            h1='صرافی‌های پشتیبانی‌شده', lead='آوینا فقط به صرافی‌هایی وصل می‌شود که مسیر خواندن آن‌ها بررسی و فعال شده است. فهرست زیر همان فهرست فعلی سرویس است.',
            sections=[('نکات اتصال', [['اتصال با کلید API فقط‌خواندنی انجام می‌شود و کلید با مجوز برداشت پذیرفته نمی‌شود.', 'برای هر صرافی، بازارهای قابل‌اتصال مشخص شده‌اند؛ بازار «در انتظار» هنوز فعال نیست.', 'پشتیبانی از یک صرافی به‌معنی فعال بودن سفارش واقعی روی آن نیست؛ موتور معاملهٔ خودکار هنوز آزمایشی است.']])],
            links=[('auto-trading', 'معاملهٔ خودکار'), ('pricing', 'قیمت‌ها')]),
    en=dict(title='Exchanges Supported by Avina', description='The exchanges Avina can connect to with a read-only API key: spot and futures markets and what each connection needs.',
            h1='Supported exchanges', lead='Avina connects only to exchanges whose read route has been reviewed and enabled. The list below is the service\'s current list.',
            sections=[('Connection notes', [['The connection uses a read-only API key; a key with withdrawal permission is refused.', 'Each exchange lists the markets that can be connected; a pending market is not active yet.', 'Support for an exchange does not mean real orders are enabled on it; the automated trading engine is still in trial.']])],
            links=[('auto-trading', 'Automated trading'), ('pricing', 'Pricing')]))

CONTENT['methodology'] = dict(
    fa=dict(title='روش بک‌تست پنج‌ساله آوینا', description='روش محاسبهٔ بک‌تست پنج‌سالهٔ آوینا: دورهٔ زمانی، سرمایهٔ اولیه، فرض‌های هزینه و محدودیت‌های مدل.', h1='روش بک‌تست پنج‌ساله', lead='', sections=[]),
    en=dict(title='Avina Five-Year Backtest Method', description='How the five-year Avina backtest is calculated: period, starting capital, cost assumptions and the limits of the model.', h1='The five-year backtest method', lead='', sections=[]))

ORDER = ('pricing', 'signals', 'auto-trading', 'exchanges', 'about', 'contact', 'terms', 'privacy', 'risk', 'methodology')
NAMES = {'pricing': ('قیمت‌ها', 'Pricing'), 'signals': ('سیگنال', 'Signals'), 'auto-trading': ('معاملهٔ خودکار', 'Auto trading'),
         'exchanges': ('صرافی‌ها', 'Exchanges'), 'about': ('دربارهٔ ما', 'About'), 'contact': ('تماس', 'Contact'),
         'terms': ('شرایط استفاده', 'Terms'), 'privacy': ('حریم خصوصی', 'Privacy'), 'risk': ('اعلام ریسک', 'Risk disclosure'),
         'methodology': ('روش بک‌تست', 'Backtest method'), 'forward-test': ('فوروارد تست', 'Forward test')}


# Longer guidance appended to the product pages (original copy; no trading-method details).
CONTENT['pricing']['fa']['sections'] += [
    ('هزینهٔ پلن در برابر ریسک', ['قیمت پلن هزینهٔ استفاده از سرویس است، نه تضمین سود. پیش از انتخاب سقف سرمایه، حداکثر زیانی را که می‌توانید تحمل کنید مشخص کنید و اندازهٔ معامله را بر همان اساس بگذارید. پلن بالاتر لزوماً نتیجهٔ بهتری نمی‌دهد؛ فقط حساب‌های بزرگ‌تر را پوشش می‌دهد.']),
    ('فعال‌سازی و تمدید', ['پس از ثبت سفارش، فاکتور پرداخت با مبلغ یکتا ساخته می‌شود. وقتی واریز روی شبکه دیده شد، پرداخت تطبیق داده و پلن فعال می‌شود. پیش از پایان اشتراک از طریق پنل و در صورت اتصال، تلگرام و ایمیل یادآوری می‌گیرید.']),
]
CONTENT['pricing']['en']['sections'] += [
    ('Plan cost versus risk', ['The price of a plan is the cost of using the service, not a promise of profit. Before choosing a capital cap, decide the largest loss you can tolerate and size your trades on that basis. A higher plan does not give a better result by itself; it only covers larger accounts.']),
    ('Activation and renewal', ['After you place an order a payment invoice with a unique amount is created. When the transfer is seen on the network the payment is matched and the plan is activated. Before a subscription ends you get reminders in your panel and, if linked, by Telegram and e-mail.']),
]
CONTENT['signals']['fa']['sections'] += [('پرسش‌های رایج دربارهٔ سیگنال', ['آیا سیگنال به‌معنای ثبت سفارش است؟ خیر؛ سیگنال فقط پیشنهاد است و اجرا با شماست. آیا همهٔ سیگنال‌ها سودده‌اند؟ خیر؛ برخی با حد ضرر بسته می‌شوند و این بخشی عادی از معامله است. آیا می‌توانم بعداً به معاملهٔ خودکار بروم؟ بله، با ارتقای پلن در همان حساب.'])]
CONTENT['signals']['en']['sections'] += [('Common questions about signals', ['Is a signal an order? No; a signal is a suggestion and execution is up to you. Are all signals profitable? No; some end at their stop-loss, which is a normal part of trading. Can I move to automated trading later? Yes, by upgrading your plan on the same account.'])]
CONTENT['auto-trading']['fa']['sections'] += [('پیش از اتصال چه چیزی آماده کنیم؟', ['یک حساب فعال صرافی، ورود دومرحله‌ای روی همان حساب، و کلید API فقط‌خواندنی. موجودی را متناسب با سقف پلن نگه دارید. اگر کلید را عوض یا ابطال کردید، اتصال در پنل ناموفق نشان داده می‌شود و می‌توانید کلید تازه وارد کنید. هیچ‌وقت کلید را با کسی در میان نگذارید.'])]
CONTENT['auto-trading']['en']['sections'] += [('What to prepare before connecting', ['An active exchange account, two-step login on that account, and a read-only API key. Keep a balance that fits your plan cap. If you rotate or revoke the key, the connection shows as failed in your panel and you can enter a new one. Never share a key with anyone.'])]
CONTENT['exchanges']['fa']['sections'] += [
    ('هر صرافی چه چیزی می‌خواهد؟', ['بیشتر صرافی‌ها کلید و رمز API می‌خواهند و برخی یک عبارت عبور (Passphrase) هم دارند. فهرست بالا فیلدهای لازم هر بازار را نشان می‌دهد. برای دو صرافی، آوینا خودش مجوزهای کلید را از صرافی می‌پرسد و کلید دارای مجوز برداشت را رد می‌کند؛ برای بقیه شما باید در فرم تأیید کنید.']),
    ('صرافی من در فهرست نیست', ['صرافی جدید فقط پس از بررسی مسیر خواندن آن اضافه می‌شود. می‌توانید درخواست خود را از راه‌های صفحهٔ تماس بفرستید. تا آن زمان می‌توانید از سیگنال‌ها بدون هیچ اتصال صرافی استفاده کنید.']),
]
CONTENT['exchanges']['en']['sections'] += [
    ('What each exchange needs', ['Most exchanges need an API key and secret and some also need a passphrase. The list above shows the fields each market requires. For two exchanges Avina asks the exchange itself for the key permissions and refuses a key that can withdraw; for the others you confirm this in the form.']),
    ('My exchange is not listed', ['A new exchange is added only after its read route has been reviewed. You can send your request through the ways on the contact page. Until then you can use signals without any exchange connection.']),
]

CONTENT['pricing']['fa']['sections'].append(('پرسش دارید؟', ['اگر مطمئن نیستید کدام پلن مناسب شماست، ابتدا با پلن سیگنال شروع کنید یا از راه‌های صفحهٔ تماس بپرسید.']))
CONTENT['pricing']['en']['sections'].append(('Still unsure?', ['If you are not sure which plan suits you, start with signals only or ask through the ways on the contact page.']))
CONTENT['signals']['fa']['sections'].append(('شروع سریع', ['حساب بسازید، پلن سیگنال را فعال کنید و در بخش تلگرام پنل، اتصال را انجام دهید. اولین سیگنال‌ها را بدون ریسک ابتدا در حالت دنبال‌کردن ببینید.']))
CONTENT['signals']['en']['sections'].append(('Quick start', ['Create an account, activate a signal plan and link Telegram in your panel. Watch the first signals without risk, simply following them, before you act on any.']))
CONTENT['auto-trading']['fa']['sections'].append(('قدم بعدی', ['اگر هنوز مطمئن نیستید، ابتدا نتایج آزمون پیشرو را دنبال کنید و صرافی‌های پشتیبانی‌شده را ببینید.']))
CONTENT['auto-trading']['en']['sections'].append(('Next step', ['If you are not sure yet, follow the forward-test results first and check the supported exchanges.']))
CONTENT["exchanges"]["fa"]["sections"].append(('اسپات و فیوچرز', ['بازار اسپات برای خواندن موجودی دارایی‌ها و بازار فیوچرز برای خواندن موجودی و موقعیت‌های باز است. هر صرافی ساختار حساب خودش را دارد؛ مثلاً حساب یکپارچه یا کلاسیک. برای همین مسیر خواندن هر صرافی جداگانه بررسی می‌شود و نمی‌توان فرض کرد که هر صرافی دیگری هم همان‌طور کار می‌کند. اگر موجودی نمایش‌داده‌شده با صرافی فرق داشت، نوع حساب و بازار انتخاب‌شده را بررسی کنید.']))
CONTENT['exchanges']['en']['sections'].append(('Spot and futures', ['The spot market is used to read asset balances and the futures market to read the balance and open positions. Every exchange has its own account structure, such as unified or classic accounts, which is why each exchange route is reviewed separately and nothing is assumed to work the same elsewhere. If the balance shown differs from the exchange, check the account type and the market you selected.']),)
