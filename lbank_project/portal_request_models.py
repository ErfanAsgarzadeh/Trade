"""Request validation models for the customer and admin APIs."""

from pydantic import BaseModel, ConfigDict, Field, SecretStr


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=2, max_length=40, pattern=r'^[a-z][a-z0-9-]+$')
    password: SecretStr = Field(min_length=12, max_length=128)


class Login(Credentials):
    totp: str | None = Field(
        default=None,
        max_length=14,
        pattern=r'^(\d{6}|[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4})$',
    )


class Registration(Credentials):
    password_confirmation: SecretStr = Field(min_length=12, max_length=128)
    email: str = Field(min_length=6, max_length=254)
    referral_code: str | None = Field(default=None, max_length=24)
    lang: str = Field(default='fa', pattern=r'^(fa|en)$')  # Language of the verification e-mail.
    website: str = Field(default='', max_length=200)  # Honeypot: people never see this field, so it must stay empty.
    form_token: str = Field(default='', max_length=100)  # Signed timestamp from GET /api/register/token.


class EmailChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=6, max_length=254)
    lang: str = Field(default='fa', pattern=r'^(fa|en)$')
    current_password: SecretStr = Field(min_length=1, max_length=128)


class VerifyResend(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lang: str = Field(default='fa', pattern=r'^(fa|en)$')


class PasswordChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: SecretStr = Field(min_length=1, max_length=128)
    new_password: SecretStr = Field(min_length=12, max_length=128)
    new_password_confirmation: SecretStr = Field(min_length=12, max_length=128)


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=2, max_length=40, pattern=r'^[a-z][a-z0-9-]+$')


class ResetConfirm(ResetRequest):
    code: str = Field(pattern=r'^\d{8}$')
    new_password: SecretStr = Field(min_length=12, max_length=128)
    new_password_confirmation: SecretStr = Field(min_length=12, max_length=128)


class TotpSetup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    current_password: SecretStr = Field(min_length=1, max_length=128)


class TotpEnable(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(pattern=r'^\d{6}$')


class TotpDisable(TotpSetup):
    code: str = Field(
        min_length=6,
        max_length=14,
        pattern=r'^(\d{6}|[A-Za-z0-9]{4}-[A-Za-z0-9]{4}-[A-Za-z0-9]{4})$',
    )


class Connection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    market: str = Field(pattern=r'^(spot|futures)$')
    api_key: SecretStr = Field(min_length=8, max_length=512)
    secret: SecretStr = Field(min_length=8, max_length=8192)
    exchange_id: str = Field(default='lbank', min_length=2, max_length=40, pattern=r'^[a-z0-9]+$')
    passphrase: SecretStr | None = Field(default=None, max_length=512)
    uid: SecretStr | None = Field(default=None, max_length=128)
    no_withdrawal_ack: bool = False  # The customer confirms the key cannot withdraw, where the exchange will not tell us.


class LicenseQuote(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    cap_usd: int = Field(ge=1000, le=100000)
    months: int = Field(ge=1, le=6)
    kind: str = Field(default='subscription', pattern=r'^(subscription|upgrade)$')
    product: str = Field(default='autotrade', pattern=r'^(signals|autotrade)$')


class LicenseOrder(LicenseQuote):
    request_key: str = Field(min_length=16, max_length=80, pattern=r'^[a-zA-Z0-9-]+$')
    expected_price_cents: int = Field(ge=1, le=20000000)


class AdminUserState(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    disabled: bool


class AdminPricing(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: str = Field(min_length=1, max_length=80)
    prices: dict[str, dict[str, str]] = Field(min_length=7, max_length=7)


class AdminVersion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    expected_version: str = Field(min_length=1, max_length=80)


class AdminOpenSales(AdminVersion):
    confirmation: str = Field(pattern=r'^FINAL_PRICES_CONFIRMED$')


class AdminRejection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    reason: str = Field(min_length=3, max_length=500)


class AdminRefund(BaseModel):
    model_config = ConfigDict(extra='forbid')
    refund_ref: str = Field(pattern=r'^[A-Za-z0-9:._-]{4,120}$')


class TransferAttach(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tx_ref: str = Field(min_length=4, max_length=200)
    order_id: str = Field(pattern=r'^[0-9a-fA-F-]{8,36}$')


class BlogArticle(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lang: str = Field(default='fa', pattern=r'^(fa|en)$')
    slug: str = Field(min_length=1, max_length=80, pattern=r'^[a-z0-9]+(?:-[a-z0-9]+)*$')
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=300)
    keywords: list[str] = Field(default_factory=list, max_length=20)
    body: str = Field(min_length=1, max_length=60000)
    status: str = Field(pattern=r'^(draft|published)$')
    published_on: str | None = Field(default=None, pattern=r'^\d{4}-\d{2}-\d{2}$')
    author_name: str = Field(default='', max_length=80)
    author_bio: str = Field(default='', max_length=300)
    expected_updated: float | None = None


class InvoiceRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    network: str = Field(pattern=r'^(tron|bsc)$')
    token: str = Field(pattern=r'^(USDT|USDC)$')


class PaymentSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    tron_address: str = Field(default='', max_length=64)
    bsc_address: str = Field(default='', max_length=64)
    invoice_minutes: int = Field(default=60, ge=15, le=1440)
    auto_approve_signals: bool = False
    bsc_rpc: str = Field(default='', max_length=200)
    trongrid_url: str = Field(default='', max_length=200)
    bsc_rpc_verify: str = Field(default='', max_length=200)
    tron_verify_url: str = Field(default='', max_length=200)
    auto_approve_max_usd: int = Field(default=500, ge=0, le=1000000)
    totp: str = Field(pattern=r'^\d{6}$')


class TelegramPreferences(BaseModel):
    model_config = ConfigDict(extra='forbid')
    signals: bool
    notices: bool


class TelegramLink(BaseModel):
    model_config = ConfigDict(extra='forbid')
    lang: str = Field(default='fa', pattern=r'^(fa|en)$')


class SiteInfo(BaseModel):
    model_config = ConfigDict(extra='forbid')
    support_email: str = Field(default='', max_length=120)
    telegram_id: str = Field(default='', max_length=65)
    telegram_link: str = Field(default='', max_length=120)
    other_line: str = Field(default='', max_length=160)


class ForwardSwitch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    hidden: bool


class TelegramSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(default='', max_length=100)
    totp: str = Field(pattern=r'^\d{6}$')


class TelegramBroadcast(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=3500)


class ReferralCode(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=3, max_length=24)


class ReferralSettings(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    attach_days: int = Field(ge=0, le=365)
    credit_max_percent: int = Field(ge=0, le=100)
    max_discount_percent: int = Field(default=100, ge=0, le=100)


class ReferralProgram(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=2, max_length=80)
    config: dict
    active: bool = True
    is_default: bool = False
    starts: float | None = None
    ends: float | None = None


class AdminReferralCode(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=3, max_length=24)
    owner: str | None = Field(default=None, max_length=40)
    program_id: str | None = Field(default=None, max_length=40)
    label: str = Field(default='', max_length=80)
    max_uses: int = Field(default=0, ge=0, le=1000000)
    active: bool = True


class ReferralGrant(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=2, max_length=40)
    kind: str = Field(pattern=r'^(credit|coupon)$')
    value: float = Field(gt=0, le=100000)
    note: str = Field(default='', max_length=200)
    expiry_days: int = Field(default=0, ge=0, le=3650)
    totp: str = Field(pattern=r'^\d{6}$')


class AdminApproval(BaseModel):
    model_config = ConfigDict(extra='forbid')
    payment_ref: str = Field(pattern=r'^[A-Za-z0-9:._-]{4,120}$')
    account_id: str | None = Field(default=None, max_length=120)
    equity_usd: str | None = Field(default=None, max_length=30)
    confirmation: str = Field(pattern=r'^PAYMENT_AND_ACCOUNT_VERIFIED$')
