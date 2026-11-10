"use strict";
const licenseElement = (id) => document.getElementById(id);
let plansCatalog = null,
  licenseSnapshot = null,
  quoteRevision = 0,
  checkoutQuote = null,
  checkoutKey = "",
  installPrompt = null;
const licenseLabels = {
  none: "بدون لایسنس",
  active: "فعال",
  grace: "مهلت ارتقای سرمایه",
  capital_exceeded: "نیازمند ارتقا",
  expired: "پایان اعتبار",
  not_yet_valid: "در انتظار شروع",
};
const orderLabels = {
  pending: "در انتظار بررسی",
  approved: "تأیید و صادر شد",
  cancelled: "لغوشده",
};
const faNumber = (value) =>
  new Intl.NumberFormat("fa-IR", { maximumFractionDigits: 2 }).format(value);
const usd = (value) => faNumber(value) + " دلار";
const faDate = (value) =>
  new Date(value).toLocaleDateString("fa-IR", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
function hasCurrentLicense() {
  return (
    licenseSnapshot?.license?.expires_at &&
    Date.parse(licenseSnapshot.license.expires_at) > Date.now()
  );
}
function selectedTerm() {
  return Number(document.querySelector('input[name="term"]:checked').value);
}
function clearLicensing() {
  quoteRevision++;
  plansCatalog = null;
  licenseSnapshot = null;
  checkoutQuote = null;
  checkoutKey = "";
  if (licenseElement("checkout-dialog").open)
    licenseElement("checkout-dialog").close();
  licenseElement("order-rows").replaceChildren();
  licenseElement("pricing-rows").replaceChildren();
  licenseElement("license-state").textContent = "—";
  licenseElement("license-funded").textContent = "—";
  licenseElement("license-cap").textContent = "—";
  licenseElement("license-expiry").textContent = "—";
  licenseElement("license-account").textContent = "";
  licenseElement("license-alert").hidden = true;
  licenseElement("download-license").hidden = true;
  licenseElement("checkout-summary").textContent = "";
  licenseElement("checkout-price").textContent = "";
  licenseElement("checkout-consent").checked = false;
  licenseElement("request-license").disabled = true;
}
async function loadLicensing() {
  const [plans, snapshot] = await Promise.all([
    api("/api/plans"),
    api("/api/me/license"),
  ]);
  plansCatalog = plans;
  licenseSnapshot = snapshot;
  licenseElement("capital-tier").replaceChildren();
  licenseElement("pricing-rows").replaceChildren();
  for (const tier of plans.tiers) {
    const option = document.createElement("option");
    option.value = tier.cap_usd;
    option.textContent = "تا " + usd(tier.cap_usd);
    licenseElement("capital-tier").append(option);
    licenseElement("pricing-rows").append(
      row([
        usd(tier.cap_usd),
        ...["1", "3", "6"].map((m) => usd(tier.prices_cents[m] / 100)),
      ]),
    );
  }
  licenseElement("capital-tier").value = hasCurrentLicense()
    ? String(snapshot.license.cap_usd)
    : "10000";
  for (const radio of document.querySelectorAll('input[name="term"]')) {
    radio.disabled = !!hasCurrentLicense();
    if (hasCurrentLicense())
      radio.checked = Number(radio.value) === snapshot.license.months;
  }
  renderLicenseSnapshot();
  await previewPlan();
}
function renderLicenseSnapshot() {
  const p = licenseSnapshot.license;
  licenseElement("license-state").textContent =
    licenseLabels[p.state] || "نامشخص";
  licenseElement("license-cap").textContent = p.cap_usd ? usd(p.cap_usd) : "—";
  licenseElement("license-funded").textContent =
    p.funded_capital_usd !== undefined
      ? usd(Number(p.funded_capital_usd))
      : "—";
  licenseElement("license-expiry").textContent = p.expires_at
    ? "پایان اعتبار: " + faDate(p.expires_at)
    : "با انتخاب پلن شروع کنید";
  licenseElement("license-account").textContent = p.account_id
    ? "حساب متصل به لایسنس: " + p.account_id
    : "هنوز لایسنس فعالی ندارید.";
  licenseElement("download-license").hidden = !p.license_id;
  const alerts = {
    grace:
      "واریز جدید از سقف پلن عبور کرده است. مهلت ارتقا تا " +
      (p.grace_ends_at ? faDate(p.grace_ends_at) : "—") +
      " است. پس از آن فقط ورود جدید متوقف می‌شود.",
    capital_exceeded:
      "سقف سرمایهٔ لایسنس رد شده است. ورود جدید پس از نصب لایسنس ارتقایافته از سر گرفته می‌شود؛ مدیریت معاملات باز ادامه دارد.",
    expired:
      "اعتبار لایسنس به پایان رسیده است. برای ادامهٔ ورودهای جدید، اشتراک را تمدید کنید.",
  };
  licenseElement("license-alert").hidden = !alerts[p.state];
  licenseElement("license-alert").textContent = alerts[p.state] || "";
  licenseElement("order-rows").replaceChildren();
  licenseElement("orders-empty").hidden = licenseSnapshot.orders.length > 0;
  licenseElement("orders-table").hidden = !licenseSnapshot.orders.length;
  for (const o of licenseSnapshot.orders) {
    const tr = row([
      o.id.slice(0, 8),
      usd(o.cap_usd) + " / " + faNumber(o.months) + " ماه",
      usd(o.price_cents / 100),
      faDate(o.created * 1000),
    ]);
    const statusCell = document.createElement("td");
    const badge = document.createElement("span");
    badge.className = "order-status " + o.status;
    badge.textContent = orderLabels[o.status] || o.status;
    statusCell.append(badge);
    tr.append(statusCell);
    const actionCell = document.createElement("td");
    if (o.status === "pending") {
      const cancel = document.createElement("button");
      cancel.className = "text-button";
      cancel.textContent = "لغو درخواست";
      cancel.setAttribute("aria-label", "لغو درخواست " + o.id.slice(0, 8));
      cancel.addEventListener("click", async () => {
        if (!confirm("درخواست بررسی لایسنس لغو شود؟")) return;
        cancel.disabled = true;
        try {
          await api(
            "/api/me/license/orders/" + encodeURIComponent(o.id) + "/cancel",
            "POST",
          );
          await loadLicensing();
          message("درخواست لغو شد.");
        } catch (e) {
          message(e.message);
          cancel.disabled = false;
        }
      });
      actionCell.append(cancel);
    } else actionCell.textContent = "—";
    tr.append(actionCell);
    licenseElement("order-rows").append(tr);
  }
}
function planSelection() {
  return {
    cap_usd: Number(licenseElement("capital-tier").value),
    months: selectedTerm(),
    kind: hasCurrentLicense() ? "upgrade" : "subscription",
  };
}
async function previewPlan() {
  if (!plansCatalog || !licenseSnapshot) return;
  const rev = ++quoteRevision;
  checkoutQuote = null;
  licenseElement("request-license").disabled = true;
  const chosen = planSelection(),
    tier = plansCatalog.tiers.find((t) => t.cap_usd === chosen.cap_usd);
  if (!tier) return;
  const fullPrice = tier.prices_cents[String(chosen.months)] / 100;
  licenseElement("plan-price").textContent = faNumber(fullPrice);
  licenseElement("selected-cap").textContent = usd(chosen.cap_usd);
  licenseElement("monthly-equivalent").textContent =
    "معادل " +
    usd(fullPrice / chosen.months) +
    " در ماه · قیمت کل " +
    faNumber(chosen.months) +
    " ماه";
  const saving =
    100 * (1 - fullPrice / ((tier.prices_cents["1"] / 100) * chosen.months));
  licenseElement("saving-badge").textContent =
    saving > 0 ? faNumber(Math.round(saving)) + "٪ صرفه‌جویی" : "USD";
  licenseElement("purchase-kind").textContent =
    chosen.kind === "upgrade"
      ? "ارتقای پلن فعال"
      : licenseSnapshot.license.state === "expired"
        ? "تمدید اشتراک"
        : "اشتراک جدید";
  licenseElement("request-license").textContent = "بررسی و ثبت درخواست ←";
  licenseElement("term-help").textContent = hasCurrentLicense()
    ? "ارتقا با حفظ تاریخ پایان و مدت پلن فعلی انجام می‌شود. تمدید پس از پایان اعتبار در دسترس است."
    : "";
  licenseElement("purchase-note").textContent =
    "فعال‌سازی پس از تأیید پرداخت و سرمایهٔ حساب توسط پشتیبانی انجام می‌شود.";
  if (licenseSnapshot.orders.some((o) => o.status === "pending")) {
    licenseElement("purchase-note").textContent =
      "یک درخواست در انتظار بررسی دارید؛ ابتدا آن را تکمیل یا لغو کنید.";
    return;
  }
  if (
    hasCurrentLicense() &&
    chosen.cap_usd <= licenseSnapshot.license.cap_usd
  ) {
    licenseElement("purchase-note").textContent =
      "برای ارتقا، سقفی بالاتر از پلن فعلی انتخاب کنید. رشد سرمایه از سود در همین دوره نیازی به ارتقا ندارد.";
    return;
  }
  licenseElement("plan-price").textContent = "…";
  try {
    const quote = await api("/api/me/license/quote", "POST", chosen);
    if (rev !== quoteRevision) return;
    checkoutQuote = quote;
    licenseElement("plan-price").textContent = faNumber(
      quote.price_cents / 100,
    );
    licenseElement("request-license").disabled = false;
    if (chosen.kind === "upgrade") {
      licenseElement("monthly-equivalent").textContent =
        "مابه‌التفاوت تا " +
        faDate(quote.expires_at) +
        " · پایان دوره تغییر نمی‌کند";
      licenseElement("saving-badge").textContent = "ارتقای پلن";
      licenseElement("purchase-note").textContent =
        "مبلغ بر اساس زمان باقی‌مانده محاسبه شده و پس از ثبت درخواست ثابت می‌شود.";
    }
  } catch (e) {
    if (rev === quoteRevision) {
      licenseElement("plan-price").textContent = "—";
      licenseElement("purchase-note").textContent = e.message;
    }
  }
}
licenseElement("capital-tier").addEventListener("change", previewPlan);
for (const radio of document.querySelectorAll('input[name="term"]'))
  radio.addEventListener("change", previewPlan);
licenseElement("request-license").addEventListener("click", async () => {
  const button = licenseElement("request-license");
  button.disabled = true;
  try {
    await previewPlan();
    if (!checkoutQuote) return;
    checkoutKey = crypto.randomUUID();
    licenseElement("checkout-consent").checked = false;
    licenseElement("confirm-order").disabled = true;
    licenseElement("checkout-error").textContent = "";
    licenseElement("checkout-summary").textContent =
      "پکیج هر سه ربات، سقف " +
      usd(checkoutQuote.cap_usd) +
      "، " +
      faNumber(checkoutQuote.months) +
      " ماه" +
      (checkoutQuote.kind === "upgrade"
        ? " · ارتقا با پایان اعتبار " + faDate(checkoutQuote.expires_at)
        : " · شروع دوره پس از تأیید پشتیبانی");
    licenseElement("checkout-price").textContent = usd(
      checkoutQuote.price_cents / 100,
    );
    licenseElement("checkout-dialog").showModal();
  } catch (e) {
    message(e.message);
  } finally {
    button.disabled = !checkoutQuote;
  }
});
licenseElement("checkout-consent").addEventListener("change", () => {
  licenseElement("confirm-order").disabled =
    !licenseElement("checkout-consent").checked;
});
licenseElement("close-checkout").addEventListener("click", () =>
  licenseElement("checkout-dialog").close(),
);
licenseElement("confirm-order").addEventListener("click", async () => {
  if (!checkoutQuote || !licenseElement("checkout-consent").checked) return;
  licenseElement("confirm-order").disabled = true;
  licenseElement("close-checkout").disabled = true;
  licenseElement("checkout-error").textContent = "";
  const quote = checkoutQuote;
  try {
    const result = await api("/api/me/license/orders", "POST", {
      cap_usd: quote.cap_usd,
      months: quote.months,
      kind: quote.kind,
      request_key: checkoutKey,
      expected_price_cents: quote.price_cents,
    });
    licenseElement("checkout-dialog").close();
    await loadLicensing();
    message(
      "درخواست شما ثبت شد. کد پیگیری: " +
        result.id.slice(0, 8) +
        " · در انتظار بررسی پشتیبانی",
    );
  } catch (e) {
    licenseElement("checkout-error").textContent = e.message;
    licenseElement("confirm-order").disabled = false;
  } finally {
    licenseElement("close-checkout").disabled = false;
  }
});
licenseElement("refresh-license").addEventListener("click", async () => {
  const button = licenseElement("refresh-license");
  button.disabled = true;
  try {
    await loadLicensing();
    message("وضعیت لایسنس به‌روز شد.");
  } catch (e) {
    message(e.message);
  } finally {
    button.disabled = false;
  }
});
window.addEventListener("beforeinstallprompt", (event) => {
  event.preventDefault();
  installPrompt = event;
  licenseElement("install-app").hidden = false;
});
licenseElement("install-app").addEventListener("click", async () => {
  if (!installPrompt) return;
  await installPrompt.prompt();
  await installPrompt.userChoice;
  installPrompt = null;
  licenseElement("install-app").hidden = true;
});
window.addEventListener("appinstalled", () => {
  licenseElement("install-app").hidden = true;
  installPrompt = null;
});
window.addEventListener("offline", () =>
  message("اتصال اینترنت قطع است؛ وضعیت نمایش‌داده‌شده ممکن است به‌روز نباشد."),
);
window.addEventListener("online", () =>
  message("اتصال برقرار شد؛ برای دریافت آخرین وضعیت، به‌روزرسانی را بزنید."),
);
if ("serviceWorker" in navigator)
  navigator.serviceWorker.register("/portal-sw.js").catch(() => {});
