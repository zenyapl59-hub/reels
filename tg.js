// Спільне для обох сторінок: тема Telegram, перевірка доступу, запити до Apps Script.
(function () {
  const tg = window.Telegram && window.Telegram.WebApp;
  const cfg = window.APP_CONFIG || {};
  const root = document.documentElement;

  function hex(c) {
    const m = String(c).match(/\d+/g);
    return m ? "#" + m.slice(0, 3).map((x) => (+x).toString(16).padStart(2, "0")).join("") : null;
  }
  function applyTheme() {
    const dark = tg && tg.colorScheme ? tg.colorScheme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
    root.setAttribute("data-theme", dark ? "dark" : "light");
    if (!tg) return;
    requestAnimationFrame(() => {
      const bg = hex(getComputedStyle(document.body).backgroundColor);
      try { if (bg) { tg.setHeaderColor(bg); tg.setBackgroundColor(bg); } } catch (e) {}
    });
  }
  applyTheme();
  if (tg) { tg.ready(); tg.expand(); tg.onEvent("themeChanged", applyTheme); }

  async function api(action, payload) {
    const res = await fetch(cfg.API_URL, {
      method: "POST",
      headers: { "Content-Type": "text/plain;charset=utf-8" },
      body: JSON.stringify(Object.assign({ action, initData: tg ? tg.initData : "" }, payload || {})),
    });
    const j = await res.json();
    if (!j.ok) { const e = new Error(j.error || "error"); e.code = j.error; e.id = j.id; throw e; }
    return j;
  }

  function lock(msg) {
    let g = document.getElementById("gate");
    if (!g) {
      g = document.createElement("div"); g.id = "gate";
      g.style.cssText = "position:fixed;inset:0;display:grid;place-items:center;padding:24px;text-align:center;font:15px/1.5 system-ui,sans-serif;background:inherit;z-index:99";
      document.body.append(g);
    }
    g.textContent = msg;
  }

  // Повертає користувача, якщо його ID дозволено; інакше показує пояснення і зупиняє сторінку.
  // gate({ quiet: true }) — не ховає сторінку під час перевірки (щоб було видно заготовки).
  async function gate(opts) {
    const quiet = opts && opts.quiet;
    if (!quiet) root.classList.add("locked");
    if (!tg || !tg.initData) { root.classList.add("locked"); lock("Відкрийте цю сторінку через бота в Telegram."); throw new Error("no_telegram"); }
    if (!cfg.API_URL || !/^https:\/\//.test(cfg.API_URL)) { root.classList.add("locked"); lock("Не налаштовано: вставте адресу Apps Script у файл config.js."); throw new Error("no_api"); }
    if (!quiet) lock("Перевіряю доступ…");
    try {
      const j = await api("whoami");
      root.classList.remove("locked");
      const g = document.getElementById("gate"); if (g) g.remove();
      return j.user;
    } catch (e) {
      root.classList.add("locked");
      if (e.code === "not_allowed") lock("Доступу немає. Ваш Telegram ID: " + e.id + ". Перешліть його власнику, щоб він додав вас у список.");
      else if (e.code === "expired") lock("Сесія застаріла. Закрийте і знову відкрийте сторінку з бота.");
      else lock("Не вдалося перевірити доступ (код: " + (e.code || e.name || "мережа") + "). Перевірте інтернет і відкрийте сторінку ще раз.");
      throw e;
    }
  }

  window.TG = { tg, api, gate, applyTheme };
})();
