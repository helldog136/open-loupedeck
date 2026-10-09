/*
 * Front-end i18n. Loaded before app.js.
 *
 *   t(key, vars)                  -> translated string ({var} interpolation; vars.count picks key.one / key.other)
 *   i18n.ready                    -> Promise resolved once the current language is loaded and the DOM translated
 *   i18n.setLanguage(code)        -> "auto" or a language code; saved to the config, applied immediately
 *   i18n.apply(root)              -> (re)translate data-i18n / data-i18n-attr elements under root
 *   document "i18n:change" event  -> fired after every language change (detail: {lang})
 *
 * Static HTML:
 *   <span data-i18n="common.save">Save</span>                  (sets textContent)
 *   <input data-i18n-attr="placeholder:common.name;title:common.hint">
 *   Optional data-i18n-vars='{"count": 3}' supplies variables.
 *
 * Messages come from GET /api/locale/<code> (English already merged under missing keys).
 * Lookup never throws: missing key -> the key itself.
 */
(function () {
  "use strict";

  var messages = {};
  var lang = "en";
  var languages = [];
  var setting = "auto";
  var detected = "en";

  var ZERO_IS_ONE = { fr: 1, pt: 1 };
  var NO_PLURAL = { ja: 1, zh: 1, ko: 1, vi: 1, th: 1, id: 1 };

  function pluralCategory(n) {
    var p = String(lang).split("-")[0].toLowerCase();
    if (NO_PLURAL[p]) return "other";
    if (ZERO_IS_ONE[p]) return n >= 0 && n < 2 ? "one" : "other";
    return n === 1 ? "one" : "other";
  }

  function interpolate(text, vars) {
    if (!vars) return text;
    return text.replace(/\{(\w+)\}/g, function (m, name) {
      return Object.prototype.hasOwnProperty.call(vars, name) ? String(vars[name]) : m;
    });
  }

  function t(key, vars) {
    try {
      var text;
      if (vars && vars.count !== undefined) {
        var n = Number(vars.count);
        text = messages[key + "." + pluralCategory(n)] || messages[key + ".other"];
      }
      if (!text) text = messages[key];
      if (!text) return key;
      return interpolate(text, vars);
    } catch (e) {
      return key;
    }
  }

  function parseVars(el) {
    var raw = el.getAttribute("data-i18n-vars");
    if (!raw) return undefined;
    try {
      return JSON.parse(raw);
    } catch (e) {
      return undefined;
    }
  }

  function applyElement(el) {
    var key = el.getAttribute("data-i18n");
    if (key) el.textContent = t(key, parseVars(el));
    var attrs = el.getAttribute("data-i18n-attr");
    if (attrs) {
      attrs.split(";").forEach(function (pair) {
        var i = pair.indexOf(":");
        if (i < 1) return;
        var attr = pair.slice(0, i).trim();
        var k = pair.slice(i + 1).trim();
        if (attr && k) el.setAttribute(attr, t(k, parseVars(el)));
      });
    }
  }

  function apply(root) {
    root = root || document;
    if (root.nodeType === 1 && (root.hasAttribute("data-i18n") || root.hasAttribute("data-i18n-attr"))) {
      applyElement(root);
    }
    if (!root.querySelectorAll) return;
    var nodes = root.querySelectorAll("[data-i18n],[data-i18n-attr]");
    for (var i = 0; i < nodes.length; i++) applyElement(nodes[i]);
  }

  function getJson(url, init) {
    return fetch(url, init).then(function (r) {
      if (!r.ok) throw new Error(url + " -> " + r.status);
      return r.json();
    });
  }

  function loadMessages(code) {
    return getJson("/api/locale/" + encodeURIComponent(code)).then(function (m) {
      messages = m || {};
      lang = code;
      document.documentElement.setAttribute("lang", code);
    });
  }

  function loadLocales() {
    return getJson("/api/locales").then(function (info) {
      languages = info.languages || [];
      setting = info.setting || "auto";
      detected = info.detected || "en";
      return info.current || "en";
    });
  }

  function announce() {
    apply(document);
    renderSelector();
    try {
      document.dispatchEvent(new CustomEvent("i18n:change", { detail: { lang: lang } }));
    } catch (e) {
      /* ignore */
    }
  }

  function langName(code) {
    for (var i = 0; i < languages.length; i++) if (languages[i].code === code) return languages[i].name;
    return code;
  }

  /** Fills and wires the Services-tab selector (<select id="uiLanguage">) if the page has one. */
  function renderSelector() {
    var sel = document.getElementById("uiLanguage");
    if (!sel) return;
    sel.innerHTML = "";
    var auto = document.createElement("option");
    auto.value = "auto";
    auto.textContent = t("language.auto", { name: langName(detected) });
    sel.appendChild(auto);
    languages.forEach(function (l) {
      var o = document.createElement("option");
      o.value = l.code;
      o.textContent = l.name;
      sel.appendChild(o);
    });
    sel.value = setting;
    if (!sel.__i18nWired) {
      sel.__i18nWired = true;
      sel.addEventListener("change", function () {
        api.setLanguage(sel.value).catch(function (e) {
          console.error("setLanguage failed", e);
        });
      });
    }
  }

  function setLanguage(code) {
    code = String(code || "auto");
    return getJson("/api/language", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ language: code }),
    })
      .then(function (res) {
        setting = res.setting || code;
        return loadMessages(res.current || "en");
      })
      .then(function () {
        announce();
        return lang;
      });
  }

  var api = {
    t: t,
    apply: apply,
    setLanguage: setLanguage,
    get lang() {
      return lang;
    },
    get languages() {
      return languages;
    },
    get setting() {
      return setting;
    },
    ready: null,
  };

  window.t = t;
  window.i18n = api;

  api.ready = loadLocales()
    .then(loadMessages)
    .catch(function (e) {
      console.warn("i18n: could not load locale, falling back to keys", e);
    })
    .then(function () {
      function go() {
        announce();
        if (window.MutationObserver) {
          new MutationObserver(function (muts) {
            muts.forEach(function (m) {
              m.addedNodes.forEach(function (n) {
                if (n.nodeType === 1) apply(n);
              });
            });
          }).observe(document.body, { childList: true, subtree: true });
        }
      }
      if (document.readyState === "loading") {
        return new Promise(function (resolve) {
          document.addEventListener("DOMContentLoaded", function () {
            go();
            resolve();
          });
        });
      }
      go();
    });
})();
