// Génère les pages /fr/ et /en/ à partir de index.html (arabe) et des traductions de site.js,
// et (ré)écrit le bloc SEO de chaque page (titre, description, hreflang, Open Graph, données structurées).
// Usage : node tools/build-i18n.mjs   (à relancer après chaque modification de index.html ou des traductions)
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";

const SITE = "https://intilakagroup.com";
const root = new URL("..", import.meta.url).pathname;
const read = (file) => readFileSync(root + file, "utf8");

// --- Traductions : l'objet `translations` de site.js ---
const js = read("site.js");
const start = js.indexOf("const translations = ") + "const translations = ".length;
let end = start, depth = 0;
for (; end < js.length; end++) {
  if (js[end] === "{") depth++;
  else if (js[end] === "}" && --depth === 0) { end++; break; }
}
const translations = Function(`"use strict"; return (${js.slice(start, end)});`)();

const SEO = {
  ar: {
    path: "/", locale: "ar_MA", dir: "rtl",
    title: "Intilaka Group | الدراسة والإقامة في إسبانيا وأوروبا",
    description: "الدراسة في إسبانيا، التحول من السياحة إلى الدراسة، Cuenta Propia، الإقامة غير الربحية ولمّ الشمل: مجموعة انطلاقة ترافقك من تطوان وملقة. احجز استشارتك.",
  },
  fr: {
    path: "/fr/", locale: "fr_FR", dir: "ltr",
    title: "Intilaka Group | Études, visa et résidence en Espagne",
    description: "Études en Espagne, passage de touriste à étudiant, Cuenta Propia, No Lucrativa, regroupement familial : Intilaka Group vous accompagne. Réservez une consultation.",
  },
  en: {
    path: "/en/", locale: "en_US", dir: "ltr",
    title: "Intilaka Group | Study, Visa & Residency in Spain",
    description: "Study in Spain, tourist-to-student change, Cuenta Propia, non-lucrative residency, family reunification: Intilaka Group guides you. Book a consultation.",
  },
};

// Textes en attributs (alt, aria-label) qui ne passent pas par les traductions de site.js
const ATTRIBUTES = {
  "مستشارة Intilaka Group مع أعلام المغرب وإسبانيا والاتحاد الأوروبي": { fr: "Conseillère Intilaka Group avec les drapeaux du Maroc, de l'Espagne et de l'Union européenne", en: "Intilaka Group advisor with the flags of Morocco, Spain and the European Union" },
  "من فيزا سياحة إلى إقامة دراسة في إسبانيا": { fr: "Du visa touristique au titre de séjour étudiant en Espagne", en: "From tourist visa to student residency in Spain" },
  "التكوين المهني والدراسة في إسبانيا": { fr: "Formation professionnelle et études en Espagne", en: "Vocational training and studies in Spain" },
  "معلومات حول الإقامة في إسبانيا": { fr: "Informations sur la résidence en Espagne", en: "Information about residency in Spain" },
  "فتح القائمة": { fr: "Ouvrir le menu", en: "Open menu" },
  "اختيار اللغة": { fr: "Choisir la langue", en: "Choose language" },
  "السابق": { fr: "Précédent", en: "Previous" },
  "التالي": { fr: "Suivant", en: "Next" },
  "إغلاق": { fr: "Fermer", en: "Close" },
};

const escapeHtml = (text) => String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const escapeAttr = (text) => escapeHtml(text).replace(/"/g, "&quot;");

function seoBlock(lang) {
  const page = SEO[lang];
  const url = SITE + page.path;
  const image = SITE + "/assets/intilaka-advisor-hero.jpg";
  const alternates = Object.entries(SEO)
    .map(([code, p]) => `  <link rel="alternate" hreflang="${code}" href="${SITE}${p.path}">`)
    .concat(`  <link rel="alternate" hreflang="x-default" href="${SITE}/">`).join("\n");
  const otherLocales = Object.entries(SEO).filter(([code]) => code !== lang)
    .map(([, p]) => `  <meta property="og:locale:alternate" content="${p.locale}">`).join("\n");
  const structured = {
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "ProfessionalService",
        "@id": `${SITE}/#organization`,
        name: "Intilaka Group",
        alternateName: "مجموعة انطلاقة",
        url: `${SITE}/`,
        logo: `${SITE}/icon-512.png`,
        image,
        description: page.description,
        telephone: "+34624593940",
        email: "info@intilakagroup.com",
        address: [
          { "@type": "PostalAddress", addressLocality: "Tétouan", addressCountry: "MA" },
          { "@type": "PostalAddress", addressLocality: "Málaga", addressCountry: "ES" },
        ],
        areaServed: [{ "@type": "Country", name: "Morocco" }, { "@type": "Country", name: "Spain" }],
        knowsLanguage: ["ar", "fr", "en"],
        sameAs: ["https://www.instagram.com/intilaka.spain/", "https://www.tiktok.com/@intilakagroup"],
      },
      {
        "@type": "WebSite",
        "@id": `${SITE}/#website`,
        url: `${SITE}/`,
        name: "Intilaka Group",
        inLanguage: Object.keys(SEO),
        publisher: { "@id": `${SITE}/#organization` },
      },
      {
        "@type": "WebPage",
        "@id": `${url}#webpage`,
        url,
        name: page.title,
        description: page.description,
        inLanguage: lang,
        isPartOf: { "@id": `${SITE}/#website` },
        about: { "@id": `${SITE}/#organization` },
      },
    ],
  };
  return `<!-- seo:start (généré par tools/build-i18n.mjs, ne pas modifier à la main) -->
  <title>${escapeHtml(page.title)}</title>
  <meta name="description" content="${escapeAttr(page.description)}">
  <meta name="robots" content="index, follow, max-image-preview:large">
  <meta http-equiv="content-language" content="${lang}">
  <link rel="canonical" href="${url}">
${alternates}
  <link rel="icon" href="/favicon.ico" sizes="48x48">
  <link rel="icon" type="image/png" sizes="512x512" href="/icon-512.png">
  <link rel="apple-touch-icon" href="/apple-touch-icon.png">
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="Intilaka Group">
  <meta property="og:url" content="${url}">
  <meta property="og:title" content="${escapeAttr(page.title)}">
  <meta property="og:description" content="${escapeAttr(page.description)}">
  <meta property="og:image" content="${image}">
  <meta property="og:image:width" content="1369">
  <meta property="og:image:height" content="1149">
  <meta property="og:locale" content="${page.locale}">
${otherLocales}
  <meta name="twitter:card" content="summary_large_image">
  <script type="application/ld+json">${JSON.stringify(structured)}</script>
  <!-- seo:end -->`;
}

function withSeo(html, lang) {
  const block = seoBlock(lang);
  if (!/<!-- seo:start[\s\S]*?<!-- seo:end -->/.test(html)) throw new Error("bloc seo:start/seo:end introuvable dans index.html");
  return html.replace(/<!-- seo:start[\s\S]*?<!-- seo:end -->/, () => block);
}

// --- Page arabe (source) : on ne fait que réécrire son bloc SEO ---
const source = read("index.html");
writeFileSync(root + "index.html", withSeo(source, "ar"));

// --- Pages traduites ---
for (const lang of ["fr", "en"]) {
  const copy = translations[lang];
  let html = withSeo(source, lang);
  html = html.replace(/<html lang="ar" dir="rtl">/, `<html lang="${lang}" dir="${SEO[lang].dir}">`);

  let replaced = 0, missing = new Set();
  // data-i18n : texte simple (l'élément ne contient pas de balise)
  html = html.replace(/(<([a-z0-9]+)\b[^>]*\sdata-i18n="([^"]+)"[^>]*>)([^<]*)(<\/\2>)/gi, (all, open, tag, key, text, close) => {
    if (copy[key] === undefined) { missing.add(key); return all; }
    replaced++; return open + escapeHtml(copy[key]) + close;
  });
  // data-i18n-html : contenu HTML fourni par la traduction
  html = html.replace(/(<([a-z0-9]+)\b[^>]*\sdata-i18n-html="([^"]+)"[^>]*>)([\s\S]*?)(<\/\2>)/gi, (all, open, tag, key, inner, close) => {
    if (copy[key] === undefined) { missing.add(key); return all; }
    replaced++; return open + copy[key] + close;
  });
  // data-i18n-placeholder
  html = html.replace(/<[a-z]+\b[^>]*\sdata-i18n-placeholder="([^"]+)"[^>]*>/gi, (tag, key) => {
    if (copy[key] === undefined) { missing.add(key); return tag; }
    replaced++; return tag.replace(/(\s)placeholder="[^"]*"/, `$1placeholder="${escapeAttr(copy[key])}"`);
  });

  // Attributs lus par Google et les lecteurs d'écran (alt, aria-label) et libellé de la langue courante
  for (const [arabic, translated] of Object.entries(ATTRIBUTES)) {
    const before = html;
    html = html.split(`"${arabic}"`).join(`"${escapeAttr(translated[lang])}"`);
    if (before === html) throw new Error(`attribut introuvable dans index.html : ${arabic}`);
  }
  html = html.replace(/(<span class="current-language">)العربية/, `$1${lang === "fr" ? "Français" : "English"}`);

  const total = (source.match(/\sdata-i18n(-html|-placeholder)?="/g) || []).length;
  mkdirSync(root + lang, { recursive: true });
  writeFileSync(root + lang + "/index.html", html);
  console.log(`${lang}: ${replaced}/${total} textes traduits` + (missing.size ? ` — sans traduction (gardés tels quels) : ${[...missing].join(", ")}` : ""));
}
console.log("ar: bloc SEO mis à jour");
