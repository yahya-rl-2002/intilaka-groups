// Google Analytics 4 (G-K1NDM9HWSC) avec Consent Mode v2 et bandeau cookies (ar / fr / en).
// - Avant tout choix : consentement refusé par défaut, Google ne reçoit que des signaux anonymes sans cookies.
// - « Accepter » active la mesure complète ; « Refuser » la laisse désactivée. Le choix est mémorisé.
// - Événements suivis : réservation envoyée, clics WhatsApp, téléphone et e-mail. Aucune donnée personnelle n'est envoyée.
(() => {
  const MEASUREMENT_ID = "G-K1NDM9HWSC";
  const STORAGE_KEY = "intilaka-consent";

  window.dataLayer = window.dataLayer || [];
  function gtag() { window.dataLayer.push(arguments); }
  window.gtag = gtag;

  const readChoice = () => { try { return localStorage.getItem(STORAGE_KEY); } catch (error) { return null; } };
  const saveChoice = (value) => { try { localStorage.setItem(STORAGE_KEY, value); } catch (error) {} };

  // Consentement par défaut : tout refusé (la publicité reste toujours refusée, le site n'en fait pas).
  gtag("consent", "default", {
    analytics_storage: readChoice() === "granted" ? "granted" : "denied",
    ad_storage: "denied",
    ad_user_data: "denied",
    ad_personalization: "denied",
    wait_for_update: 500,
  });
  gtag("js", new Date());
  gtag("config", MEASUREMENT_ID);

  const script = document.createElement("script");
  script.async = true;
  script.src = `https://www.googletagmanager.com/gtag/js?id=${MEASUREMENT_ID}`;
  document.head.appendChild(script);

  // --- Bandeau cookies ---
  const TEXT = {
    ar: { message: "نستخدم ملفات تعريف الارتباط لقياس زيارات الموقع وتحسينه. يمكنك القبول أو الرفض.", accept: "قبول", refuse: "رفض", manage: "ملفات تعريف الارتباط" },
    fr: { message: "Nous utilisons des cookies pour mesurer l'audience du site et l'améliorer. Vous pouvez accepter ou refuser.", accept: "Accepter", refuse: "Refuser", manage: "Cookies" },
    en: { message: "We use cookies to measure site traffic and improve it. You can accept or decline.", accept: "Accept", refuse: "Decline", manage: "Cookies" },
  };
  const lang = TEXT[document.documentElement.lang] ? document.documentElement.lang : "ar";
  const copy = TEXT[lang];

  function applyChoice(value) {
    saveChoice(value);
    gtag("consent", "update", { analytics_storage: value });
    const banner = document.querySelector(".cookie-banner");
    if (banner) banner.remove();
  }

  function showBanner() {
    if (document.querySelector(".cookie-banner")) return;
    const banner = document.createElement("div");
    banner.className = "cookie-banner";
    banner.setAttribute("role", "dialog");
    banner.setAttribute("aria-live", "polite");
    banner.setAttribute("aria-label", copy.manage);
    const message = document.createElement("p");
    message.textContent = copy.message;
    const actions = document.createElement("div");
    actions.className = "cookie-actions";
    const refuse = document.createElement("button");
    refuse.type = "button";
    refuse.className = "button cookie-refuse";
    refuse.textContent = copy.refuse;
    refuse.addEventListener("click", () => applyChoice("denied"));
    const accept = document.createElement("button");
    accept.type = "button";
    accept.className = "button button-blue cookie-accept";
    accept.textContent = copy.accept;
    accept.addEventListener("click", () => applyChoice("granted"));
    actions.append(refuse, accept);
    banner.append(message, actions);
    document.body.appendChild(banner);
  }

  function addFooterLink() {
    const footer = document.querySelector(".footer-bottom");
    if (!footer || footer.querySelector(".cookie-settings")) return;
    const link = document.createElement("button");
    link.type = "button";
    link.className = "cookie-settings";
    link.textContent = copy.manage;
    link.addEventListener("click", showBanner);
    footer.appendChild(link);
  }

  // --- Événements utiles ---
  function track(name, params) { gtag("event", name, params || {}); }

  document.addEventListener("click", (event) => {
    const link = event.target.closest && event.target.closest("a[href]");
    if (!link) return;
    const href = link.getAttribute("href");
    const location = link.className ? String(link.className).split(" ")[0] : "link";
    if (href.includes("wa.me/")) track("whatsapp_click", { link_location: location });
    else if (href.startsWith("tel:")) track("phone_click", { link_location: location });
    else if (href.startsWith("mailto:")) track("email_click", { link_location: location });
  });

  // Envoyé par site.js quand une réservation est confirmée par le serveur.
  document.addEventListener("intilaka:booking", (event) => {
    track("generate_lead", { form_name: "booking", service: event.detail && event.detail.service });
  });

  function start() {
    addFooterLink();
    if (!readChoice()) showBanner();
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
