

/* ---- static/js/auth.js ---- */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const toggleButtons = document.querySelectorAll("[data-toggle-password]");

  toggleButtons.forEach((button) => {
    const inputId = button.dataset.togglePassword;
    const input = document.getElementById(inputId);

    if (!input) {
      return;
    }

    button.addEventListener("click", () => {
      const isVisible = input.type === "text";

      input.type = isVisible ? "password" : "text";

      button.textContent = isVisible ? "表示" : "非表示";

      button.setAttribute("aria-pressed", String(!isVisible));
    });
  });
});


/* ---- static/js/clock.js ---- */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  // 日付と時刻は表示用。打刻時刻はDjangoサーバーで決定する。
  const dateElement = document.getElementById("current-date");
  const clockElement = document.getElementById("current-clock");
  const dateFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    year: "numeric",
    month: "long",
    day: "numeric",
    weekday: "short",
  });
  const timeFormatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });

  const renderClock = () => {
    const now = new Date();
    if (dateElement) dateElement.textContent = dateFormatter.format(now);
    if (clockElement) clockElement.textContent = timeFormatter.format(now);
  };
  renderClock();
  if (dateElement || clockElement) window.setInterval(renderClock, 1000);

  let submitting = false;
  const forms = [...document.querySelectorAll(".clock-form")];
  forms.forEach((form) => {
    form.addEventListener("submit", (event) => {
      if (submitting) {
        event.preventDefault();
        return;
      }
      submitting = true;
      // 同じページの他の打刻操作も押せないようにする。
      forms.forEach((otherForm) => {
        const button = otherForm.querySelector('button[type="submit"]');
        if (!button) return;
        button.disabled = true;
        if (otherForm === form) {
          button.textContent = "記録中…";
        }
      });
    });
  });

  // ブラウザの戻る操作等で無効状態が残った際は画面を再取得する。
  window.addEventListener("pageshow", (event) => {
    if (event.persisted) window.location.reload();
  });
});


/* ---- static/js/e01-clock-display.js ---- */
"use strict";

/**
 * E01 打刻ホーム
 * 表示用の日本時間時計
 *
 * サーバーから渡された表示時刻を基準にする。
 * 実際の打刻時刻はDjango側で決定する。
 */

document.addEventListener("DOMContentLoaded", () => {
  const element = document.getElementById("e01-current-time");

  if (!element) {
    return;
  }

  const rawTime = element.dataset.serverTime;
  const initialTime = Date.parse(rawTime);

  if (!Number.isFinite(initialTime)) {
    return;
  }

  const startedAt = performance.now();

  const formatter = new Intl.DateTimeFormat("ja-JP", {
    timeZone: "Asia/Tokyo",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  });

  const update = () => {
    const elapsed = performance.now() - startedAt;

    const current = new Date(initialTime + elapsed);

    element.textContent = formatter.format(current);
  };

  update();

  const interval = setInterval(update, 1000);

  window.addEventListener(
    "pagehide",
    () => {
      clearInterval(interval);
    },
    { once: true },
  );
});


/* ---- static/js/e03-breaks.js ---- */
"use strict";

document.addEventListener("DOMContentLoaded", () => {
  const addButton = document.querySelector("[data-e03-add-break]");

  const list = document.getElementById("e03-break-form-list");

  const template = document.getElementById("e03-empty-break-template");

  const totalForms = document.querySelector('input[name="breaks-TOTAL_FORMS"]');

  const maxForms = document.querySelector('input[name="breaks-MAX_NUM_FORMS"]');

  if (!addButton || !list || !template || !totalForms) {
    return;
  }

  const configuredMax = Number.parseInt(maxForms?.value || "20", 10);

  const maximum = Math.min(
    Number.isFinite(configuredMax) ? configuredMax : 20,
    20,
  );

  const updateButton = () => {
    const total = Number.parseInt(totalForms.value, 10);

    addButton.disabled = total >= maximum;
  };

  addButton.addEventListener("click", () => {
    const current = Number.parseInt(totalForms.value, 10);

    if (!Number.isFinite(current) || current >= maximum) {
      return;
    }

    const html = template.innerHTML.replaceAll("__prefix__", String(current));

    const wrapper = document.createElement("div");
    wrapper.innerHTML = html.trim();

    const newRow = wrapper.firstElementChild;

    if (!newRow) {
      return;
    }

    const heading = newRow.querySelector("h3");

    if (heading) {
      heading.textContent = `休憩 ${current + 1}`;
    }

    list.appendChild(newRow);
    totalForms.value = String(current + 1);

    updateButton();

    const firstInput = newRow.querySelector(
      "input:not([type='hidden']):not([type='checkbox'])",
    );

    firstInput?.focus();
  });

  updateButton();
});


/* ---- static/js/step4-password.js ---- */
"use strict";

/*
 * STEP 4
 * パスワード表示・非表示
 *
 * 既存の認証処理には関与しない。
 */

document.addEventListener("click", (event) => {
  const button = event.target.closest("[data-v2-password-toggle]");

  if (!button) {
    return;
  }

  const targetId = button.getAttribute("aria-controls");

  if (!targetId) {
    return;
  }

  const field = document.getElementById(targetId);

  if (!field || !["password", "text"].includes(field.type)) {
    return;
  }

  const shouldShow = field.type === "password";

  field.type = shouldShow ? "text" : "password";

  button.setAttribute("aria-pressed", String(shouldShow));

  const label = button.querySelector("[data-v2-password-label]");

  if (label) {
    label.textContent = shouldShow ? "非表示" : "表示";
  }
});
