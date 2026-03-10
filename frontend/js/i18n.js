/**
 * Pie Office — Internationalization System
 * Supports 16 languages with auto-detection and runtime switching.
 * Load this before other JS modules so I18N.t() is available everywhere.
 */
const I18N = {
  _strings: {},
  _fallback: {},
  _lang: "en",
  _supported: [
    "en",
    "ko",
    "zh-CN",
    "zh-TW",
    "ja",
    "es",
    "hi",
    "ar",
    "pt",
    "fr",
    "de",
    "ru",
    "it",
    "tr",
    "vi",
    "th",
  ],
  _ready: false,

  /**
   * Initialize the i18n system.
   * Detection priority: URL ?lang= > localStorage > navigator.language > "en"
   */
  async init() {
    const detected = this._detectLang();
    const lang = this._normalize(detected);
    const resolved = this._supported.includes(lang) ? lang : "en";

    // Always load English as fallback
    if (resolved !== "en") {
      this._fallback = await this._fetch("en");
    }

    this._strings = await this._fetch(resolved);

    // If the requested language failed to load, fall back to English
    if (Object.keys(this._strings).length === 0 && resolved !== "en") {
      this._strings = this._fallback;
      this._lang = "en";
    } else {
      this._lang = resolved;
      // When primary language loaded, set fallback for missing keys
      if (resolved !== "en" && Object.keys(this._fallback).length === 0) {
        this._fallback = await this._fetch("en");
      }
    }

    localStorage.setItem("temple-office-lang", this._lang);
    document.documentElement.lang = this._lang;

    // Set text direction for RTL languages
    if (this._lang === "ar") {
      document.documentElement.dir = "rtl";
    } else {
      document.documentElement.dir = "ltr";
    }

    this._ready = true;
  },

  /**
   * Detect language from available sources.
   */
  _detectLang() {
    // 1. URL parameter ?lang=
    const params = new URLSearchParams(window.location.search);
    const urlLang = params.get("lang");
    if (urlLang) return urlLang;

    // 2. localStorage
    const stored = localStorage.getItem("temple-office-lang");
    if (stored) return stored;

    // 3. Browser language
    if (navigator.language) return navigator.language;

    // 4. Default
    return "en";
  },

  /**
   * Normalize language codes to our supported format.
   * Examples: "ko-KR" -> "ko", "zh-Hans" -> "zh-CN", "zh-Hant" -> "zh-TW"
   */
  _normalize(code) {
    if (!code) return "en";

    // Direct match first
    if (this._supported.includes(code)) return code;

    // Normalize known variants
    const map = {
      "zh-hans": "zh-CN",
      "zh-hant": "zh-TW",
      "zh-sg": "zh-CN",
      "zh-my": "zh-CN",
      "zh-hk": "zh-TW",
      "zh-mo": "zh-TW",
      "pt-br": "pt",
      "pt-pt": "pt",
    };

    const lower = code.toLowerCase();
    if (map[lower]) return map[lower];

    // Try base language (e.g., "ko-KR" -> "ko")
    const base = lower.split("-")[0];

    // Special case: bare "zh" defaults to Simplified
    if (base === "zh") return "zh-CN";

    if (this._supported.includes(base)) return base;

    return code;
  },

  /**
   * Fetch a language JSON file.
   */
  async _fetch(lang) {
    try {
      const resp = await fetch(`/static/i18n/${lang}.json`);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      return await resp.json();
    } catch (err) {
      console.warn(`[i18n] Failed to load ${lang}.json:`, err.message);
      // If not English, try English fallback
      if (lang !== "en") {
        try {
          const resp = await fetch("/static/i18n/en.json");
          if (resp.ok) return await resp.json();
        } catch (_) {
          /* give up */
        }
      }
      return {};
    }
  },

  /**
   * Translate a key, with optional parameter substitution.
   * @param {string} key - Dot-notation key (e.g., "bubble.working")
   * @param {Object} [params] - Replacement values (e.g., { name: "Pie" })
   * @returns {string} Translated string, or the key itself if not found.
   */
  t(key, params) {
    let str = this._strings[key] ?? this._fallback[key] ?? key;

    if (params && typeof params === "object") {
      for (const [k, v] of Object.entries(params)) {
        // Escape regex metacharacters in key to prevent injection
        const safeKey = k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        str = str.replace(new RegExp(`\\{${safeKey}\\}`, "g"), v);
      }
    }

    return str;
  },

  /** Current language code. */
  get lang() {
    return this._lang;
  },

  /** List of supported language codes (copy). */
  get supported() {
    return [...this._supported];
  },

  /** Whether init() has completed. */
  get ready() {
    return this._ready;
  },

  /**
   * Switch language at runtime.
   * @param {string} lang - Language code to switch to.
   */
  async setLang(lang) {
    const normalized = this._normalize(lang);
    const resolved = this._supported.includes(normalized) ? normalized : "en";

    if (resolved === this._lang) return;

    const strings = await this._fetch(resolved);
    if (Object.keys(strings).length === 0) return; // keep current on failure

    this._strings = strings;
    this._lang = resolved;

    // Ensure English fallback is loaded
    if (resolved !== "en" && Object.keys(this._fallback).length === 0) {
      this._fallback = await this._fetch("en");
    }

    localStorage.setItem("temple-office-lang", this._lang);
    document.documentElement.lang = this._lang;
    document.documentElement.dir = this._lang === "ar" ? "rtl" : "ltr";

    // Dispatch event so UI components can re-render
    window.dispatchEvent(
      new CustomEvent("langchange", { detail: { lang: this._lang } }),
    );
  },
};
